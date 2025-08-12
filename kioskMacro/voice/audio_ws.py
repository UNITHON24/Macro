from __future__ import annotations
import asyncio
import json
import base64
import threading
import queue
import time
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
        self.tts_player = TTSPlayer(prefer_pygame_fallback=cfg.tts_prefer_pygame_fallback)
        self._fallback_timer = None

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
                    print(f"[WS] 원본 메시지: {msg[:200]}...")  # 처음 200자만 출력
                    data = json.loads(msg)
                except Exception as e:
                    print(f"[WS] JSON 파싱 실패: {e}")
                    continue
                    
                t = data.get("type")
                print(f"[WS] 메시지 타입: {t}")  # 모든 메시지 타입 출력
                
                if t == "stop" and self.on_server_stop:
                    print("[WS] 서버에서 중지 신호 수신")
                    self.on_server_stop()
                elif t == "error":
                    print(f"[WS] 서버 오류: {data.get('message', 'Unknown error')}")
                elif t == "tts.chunk":
                    # TTS 오디오 청크 수신 (HTML과 동일한 방식)
                    audio_data = data.get("audioData")
                    if audio_data:
                        print(f"[TTS] 오디오 청크 수신: {len(audio_data)} bytes (Base64)")
                        self.tts_player.add_chunk(audio_data)
                        # 폴백: 마지막 청크 시간 기록 (tts.complete가 안 올 경우 대비)
                        self.tts_player.last_chunk_time = time.time()
                        # 폴백 타이머: 설정값 후에도 tts.complete가 안 오면 재생
                        if hasattr(self, '_fallback_timer') and self._fallback_timer:
                            self._fallback_timer.cancel()
                        self._fallback_timer = threading.Timer(self.cfg.tts_fallback_sec, self._fallback_play)
                        self._fallback_timer.start()
                    else:
                        print("[TTS] audioData 필드가 없음!")
                        print(f"[TTS] 데이터 키들: {list(data.keys())}")
                elif t in ("tts.complete", "tts.end", "tts.done"):
                    print(f"[TTS] TTS 완료 신호 수신({t}) - 오디오 재생 시작 (총 {len(self.tts_player.chunks)}개 청크)")
                    # 폴백 타이머 취소
                    if hasattr(self, '_fallback_timer') and self._fallback_timer:
                        self._fallback_timer.cancel()
                    # HTML처럼 완료 신호에서 재생
                    threading.Thread(target=self.tts_player.play_complete, daemon=True).start()
                elif t == "bot.reply":
                    message = data.get("message", "")
                    print(f"[BOT] 봇 응답: {message}")
                    # TTS 청크가 설정 시간 내에 오지 않으면 강제 TTS 요청 (로그만)
                    self._wait_for_tts_or_request()
                elif t == "transcript.partial":
                    transcript = data.get("transcript", "")
                    print(f"[STT] 부분 인식: {transcript}")
                elif t == "transcript.final":
                    transcript = data.get("transcript", "")
                    print(f"[STT] 최종 인식: {transcript}")
                else:
                    print(f"[WS] 알 수 없는 메시지 타입: {t}")
                    print(f"[WS] 전체 데이터: {data}")
                    
        except websockets.exceptions.ConnectionClosed:
            print("[WS] 서버와의 연결이 끊어짐")
            if self.on_server_stop:
                self.on_server_stop()
        except Exception as e:
            print(f"[WS] 메시지 수신 오류: {e}")

    def _wait_for_tts_or_request(self):
        """TTS 청크를 기다리거나 설정 시간 후 강제 경고"""
        def check_tts():
            time.sleep(self.cfg.tts_fallback_sec)
            if not self.tts_player.chunks:
                print("[TTS] 시간 내 TTS 청크 없음 - 백엔드 TTS 서비스 확인 필요")
        
        threading.Thread(target=check_tts, daemon=True).start()

    def _fallback_play(self):
        """설정 시간 후에도 tts.complete가 오지 않으면 폴백으로 재생"""
        print(f"[TTS] 폴백 타이머 실행됨! 청크 수: {len(self.tts_player.chunks) if self.tts_player.chunks else 0}")
        if self.tts_player.chunks:
            print(f"[TTS] 폴백 재생 시작 (청크 수: {len(self.tts_player.chunks)}) - 완료 신호 미수신")
            threading.Thread(target=self.tts_player.play_complete, daemon=True).start()
        else:
            print("[TTS] 폴백 타이머 실행되었지만 청크가 없음")

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

    # ===== Public controls for utterance-level control =====
    def send_audio_end(self):
        if not (self.ws and self.loop and self.connected):
            return
        try:
            fut = asyncio.run_coroutine_threadsafe(
                self.ws.send(json.dumps({"type": "audio.end"})),
                self.loop
            )
            fut.result(timeout=1)
            print("[WS] audio.end 전송 (utterance)")
        except Exception as e:
            print(f"[WS] audio.end 전송 실패: {e}")

    def send_audio_start(self):
        if not (self.ws and self.loop and self.connected):
            return
        try:
            message = json.dumps({
                "type": "audio.start",
                "config": {
                    "sampleRate": self.cfg.sample_rate,
                    "encoding": "pcm_s16le",
                    "channels": 1
                }
            })
            fut = asyncio.run_coroutine_threadsafe(
                self.ws.send(message),
                self.loop
            )
            fut.result(timeout=1)
            print("[WS] audio.start 전송 (utterance)")
        except Exception as e:
            print(f"[WS] audio.start 전송 실패: {e}")
