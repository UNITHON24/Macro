from __future__ import annotations
import asyncio
import json
import base64
import threading
import queue
import websockets
from typing import Optional, Callable
from .config import Config
from .tts_player import TTSPlayer

class AudioWSClient:
    def __init__(self, cfg: Config, frame_q: "queue.Queue[bytes]", on_server_stop: Optional[Callable[[], None]] = None):
        self.cfg = cfg
        self.frame_q = frame_q
        self.on_server_stop = on_server_stop
        self.ws = None
        self.running = False
        self.loop = None
        self.thread: Optional[threading.Thread] = None
        self._sender_task = None
        self._receiver_task = None
        self.connected = False
        self.tts_player = TTSPlayer()

    async def _connect(self):
        try:
            print(f"[WS] 연결 시도: {self.cfg.audio_ws_url}")
            self.ws = await asyncio.wait_for(
                websockets.connect(
                    self.cfg.audio_ws_url, 
                    max_size=self.cfg.ws_max_size
                ), 
                timeout=self.cfg.ws_connect_timeout
            )
            
            # 연결 성공 시 초기 설정 전송
            await self.ws.send(json.dumps({
                "type": "audio.start",
                "config": {
                    "sampleRate": self.cfg.sample_rate, 
                    "encoding": "pcm_s16le",
                    "channels": 1
                }
            }))
            
            self.connected = True
            print("[WS] 연결 성공")
            
        except asyncio.TimeoutError:
            print(f"[WS] 연결 타임아웃: {self.cfg.audio_ws_url}")
            raise
        except Exception as e:
            print(f"[WS] 연결 실패: {e}")
            raise

    async def _sender(self):
        loop = asyncio.get_event_loop()
        while self.running:
            try:
                frame = await loop.run_in_executor(None, self.frame_q.get, True, 0.1)
                if not self.running:
                    break
                # WS 연결되어 있으면 오디오 데이터를 JSON으로 감싸서 전송
                if self.ws and self.connected:
                    # 오디오 데이터를 base64로 인코딩하여 JSON으로 전송
                    audio_data_b64 = base64.b64encode(frame).decode('utf-8')
                    message = json.dumps({
                        "type": "audio.chunk",
                        "audioData": audio_data_b64
                    })
                    await self.ws.send(message)
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[WS] 음성 데이터 전송 오류: {e}")
                break

    async def _receiver(self):
        try:
            async for msg in self.ws:
                if isinstance(msg, bytes):
                    continue
                try:
                    data = json.loads(msg)
                except Exception:
                    continue
                    
                t = data.get("type")
                if t == "stop" and self.on_server_stop:
                    print("[WS] 서버에서 중지 신호 수신")
                    self.on_server_stop()
                elif t == "error":
                    print(f"[WS] 서버 오류: {data.get('message', 'Unknown error')}")
                elif t == "tts.chunk":
                    # TTS 오디오 청크 수신
                    audio_data = data.get("audioData")
                    if audio_data:
                        print(f"[TTS] 오디오 청크 수신: {len(audio_data)} bytes")
                        self.tts_player.add_chunk(audio_data)
                elif t == "tts.complete":
                    print("[TTS] TTS 완료 - 오디오 재생 시작")
                    # 별도 스레드에서 재생 (블로킹 방지)
                    threading.Thread(target=self.tts_player.play_complete, daemon=True).start()
                elif t == "bot.reply":
                    message = data.get("message", "")
                    print(f"[BOT] 봇 응답: {message}")
                elif t == "transcript.partial":
                    transcript = data.get("transcript", "")
                    print(f"[STT] 부분 인식: {transcript}")
                elif t == "transcript.final":
                    transcript = data.get("transcript", "")
                    print(f"[STT] 최종 인식: {transcript}")
                else:
                    print(f"[WS] 알 수 없는 메시지 타입: {t}")
                    
        except websockets.exceptions.ConnectionClosed:
            print("[WS] 서버와의 연결이 끊어짐")
            if self.on_server_stop:
                self.on_server_stop()
        except Exception as e:
            print(f"[WS] 메시지 수신 오류: {e}")

    async def _start(self):
        self.running = True
        await self._connect()
        self._sender_task = asyncio.create_task(self._sender())
        self._receiver_task = asyncio.create_task(self._receiver())

    async def _stop(self):
        self.running = False
        self.connected = False
        
        try:
            if self.ws and self.connected:
                # 오디오 스트림 종료 신호 전송
                await self.ws.send(json.dumps({"type": "audio.end"}))
                await self.ws.close()
        finally:
            self.ws = None
            
        if self._sender_task:
            self._sender_task.cancel()
        if self._receiver_task:
            self._receiver_task.cancel()

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        def run():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            try:
                self.loop.run_until_complete(self._start())
                self.loop.run_forever()
            except Exception as e:
                print(f"[WS] WebSocket 실행 오류: {e}")
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        print("[WS] WebSocket 시작")

    def stop(self):
        if not self.loop:
            return
        try:
            # 오디오 종료 신호 먼저 전송
            if self.ws and self.connected:
                fut_end = asyncio.run_coroutine_threadsafe(
                    self.ws.send(json.dumps({"type": "audio.end"})), 
                    self.loop
                )
                fut_end.result(timeout=1)
                print("[WS] 오디오 종료 신호 전송")
            
            fut = asyncio.run_coroutine_threadsafe(self._stop(), self.loop)
            fut.result(timeout=2)
        except Exception as e:
            print(f"[WS] WebSocket 중지 오류: {e}")
        try: 
            self.loop.call_soon_threadsafe(self.loop.stop)
        except Exception:
            pass
        print("[WS] WebSocket 중지")
