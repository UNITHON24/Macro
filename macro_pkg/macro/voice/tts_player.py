import base64
import queue
import threading
import time
import pygame
import io
import tempfile
import os
import subprocess
from typing import List
from pydub import AudioSegment
from pydub.playback import play

class TTSPlayer:
    def __init__(self, prefer_pygame_fallback: bool = False):
        pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
        self.chunks: List[bytes] = []
        self.last_chunk_time = None
        self.playing = False
        self.prefer_pygame_fallback = prefer_pygame_fallback
        
    def add_chunk(self, audio_data_b64: str):
        """TTS 오디오 청크 추가"""
        try:
            audio_bytes = base64.b64decode(audio_data_b64)
            self.chunks.append(audio_bytes)
            print(f"[TTS] 청크 추가: {len(audio_bytes)} bytes, 총 {len(self.chunks)}개")
        except Exception as e:
            print(f"[TTS] 청크 디코딩 오류: {e}")
    
    def play_complete(self):
        """MP3 청크들을 하나로 결합하여 한 번에 디코딩/재생 (부분 청크 디코딩 금지)"""
        if not self.chunks:
            print("[TTS] 재생할 오디오 청크가 없음")
            return
        
        if self.playing:
            print("[TTS] 이미 재생 중...")
            return
            
        self.playing = True
        print(f"[TTS] 결합 재생 시작 - 총 {len(self.chunks)}개 청크")
        
        temp_file_path = None
        try:
            # 1) 모든 MP3 청크를 바이트로 결합 (프레임 경계 무관하게 그대로 연결)
            combined_bytes = b"".join(self.chunks)
            print(f"[TTS] 결합 바이트 길이: {len(combined_bytes)} bytes")

            # 2) 설정상 pygame 폴백 선호 시, 바로 파일로 쓰고 pygame으로 재생
            if self.prefer_pygame_fallback:
                print("[TTS] 설정에 의해 pygame 경로 사용 (직접 결합 파일 재생)")
                with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:
                    temp_file_path = temp_file.name
                    temp_file.write(combined_bytes)
                self._play_with_pygame(temp_file_path)
                return

            # 3) pydub으로 한 번만 디코딩 (청크별 X)
            try:
                audio_seg = AudioSegment.from_file(io.BytesIO(combined_bytes), format="mp3")
                print(f"[TTS] pydub 디코딩 성공 - 길이: {len(audio_seg)}ms")
                # pygame 재생을 위해 임시 WAV 파일로 저장 (mp3 대신 wav로 변환)
                with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
                    temp_file_path = temp_file.name
                    audio_seg.export(temp_file_path, format="wav")
                self._play_with_pygame(temp_file_path)
            except Exception as e:
                print(f"[TTS] pydub 단일 디코딩 오류: {e}")
                # 4) 폴백: 결합된 MP3를 그대로 재생
                with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:
                    temp_file_path = temp_file.name
                    temp_file.write(combined_bytes)
                self._play_with_pygame(temp_file_path)
        except Exception as e:
            print(f"[TTS] 결합 재생 오류: {e}")
        finally:
            # 임시 파일 정리
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                    print(f"[TTS] 임시 파일 삭제: {temp_file_path}")
                except Exception as e:
                    print(f"[TTS] 임시 파일 삭제 실패: {e}")
            # 청크 초기화
            self.chunks.clear()
            self.playing = False
    
    def _play_with_pygame(self, file_path: str):
        print("[TTS] pygame 재생 시작")
        try:
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.play()
            start_ts = time.time()
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
            print(f"[TTS] pygame 재생 완료 ({time.time() - start_ts:.2f}s)")
        except Exception as e:
            print(f"[TTS] pygame 재생 오류: {e} → afplay 폴백 시도")
            self._play_with_afplay(file_path)
    
    def _play_with_afplay(self, file_path: str):
        try:
            # macOS 기본 플레이어
            subprocess.run(["afplay", file_path], check=True)
            print("[TTS] afplay 재생 완료")
        except Exception as e:
            print(f"[TTS] afplay 재생 실패: {e}")
    
    def _fallback_pygame_play(self):
        """(호환) 폴백: pygame으로 단순 결합 재생 (구 방식)"""
        print("[TTS] 폴백 모드: pygame 단순 결합 재생")
        
        try:
            # 모든 청크를 바이트로 단순 결합
            temp_file_path = None
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:
                temp_file_path = temp_file.name
                
                total_size = 0
                for chunk in self.chunks:
                    temp_file.write(chunk)
                    total_size += len(chunk)
            
            print(f"[TTS] 폴백 파일 생성: {total_size} bytes")
            
            # pygame으로 재생
            pygame.mixer.music.load(temp_file_path)
            pygame.mixer.music.play()
            
            # 재생 완료까지 대기
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
            
            print("[TTS] 폴백 재생 완료")
            
        except Exception as e:
            print(f"[TTS] 폴백 재생 오류: {e}")
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except:
                    pass
    
    def stop(self):
        """재생 중지"""
        pygame.mixer.music.stop()
        self.chunks.clear()
        self.playing = False
        print("[TTS] 재생 중지") 