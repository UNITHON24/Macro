import base64
import queue
import threading
import time
import pygame
import io
import tempfile
import os
from typing import List

class TTSPlayer:
    def __init__(self):
        pygame.mixer.init()  # 기본 설정 사용 (MP3 지원)
        self.audio_queue: queue.Queue[bytes] = queue.Queue()
        self.playing = False
        self.chunks: List[bytes] = []
        
    def add_chunk(self, audio_data_b64: str):
        """TTS 오디오 청크 추가"""
        try:
            audio_bytes = base64.b64decode(audio_data_b64)
            self.chunks.append(audio_bytes)
            print(f"[TTS] 청크 추가: {len(audio_bytes)} bytes, 총 {len(self.chunks)}개")
        except Exception as e:
            print(f"[TTS] 청크 디코딩 오류: {e}")
    
    def play_complete(self):
        """모든 청크를 합쳐서 재생"""
        if not self.chunks:
            print("[TTS] 재생할 오디오 청크가 없음")
            return
            
        temp_file = None
        try:
            # 모든 청크를 하나로 합치기
            combined_audio = b''.join(self.chunks)
            print(f"[TTS] 전체 오디오 크기: {len(combined_audio)} bytes")
            
            # 임시 파일로 저장해서 재생 (MP3 형식)
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:
                temp_file.write(combined_audio)
                temp_file_path = temp_file.name
            
            print(f"[TTS] 임시 파일 생성: {temp_file_path}")
            
            # pygame으로 재생
            pygame.mixer.music.load(temp_file_path)
            pygame.mixer.music.play()
            
            print("[TTS] 오디오 재생 시작")
            
            # 재생 완료까지 대기
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
                
            print("[TTS] 오디오 재생 완료")
            
        except Exception as e:
            print(f"[TTS] 오디오 재생 오류: {e}")
        finally:
            # 임시 파일 삭제
            if temp_file and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                    print(f"[TTS] 임시 파일 삭제: {temp_file_path}")
                except Exception as e:
                    print(f"[TTS] 임시 파일 삭제 실패: {e}")
            
            # 청크 초기화
            self.chunks.clear()
    
    def stop(self):
        """재생 중지"""
        pygame.mixer.music.stop()
        self.chunks.clear()
        print("[TTS] 재생 중지") 