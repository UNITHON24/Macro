# voiceServer.py
# 백엔드 서버에서 받은 음성파일을 재생하는 서버

import os
import json
import time
import tempfile
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import pygame
import threading
import queue

class VoiceRequestHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        self.audio_queue = queue.Queue()
        self.is_playing = False
        
        # pygame 초기화
        try:
            pygame.mixer.init()
            print("[AUDIO] pygame 오디오 시스템 초기화 완료")
        except Exception as e:
            print(f"[AUDIO] pygame 오디오 초기화 실패: {e}")
        
        super().__init__(*args, **kwargs)
    
    def do_POST(self):
        """POST 요청으로 음성파일을 받아서 재생"""
        try:
            # Content-Length 확인
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length == 0:
                self.send_error(400, "음성파일이 전송되지 않았습니다.")
                return
            
            # 음성파일 데이터 읽기
            audio_data = self.rfile.read(content_length)
            
            # Content-Type 확인
            content_type = self.headers.get('Content-Type', '')
            
            # Content-Type에 따라 확장자 결정
            if 'audio/' in content_type:
                # audio/mp3, audio/wav 등에서 확장자 추출
                audio_format = content_type.split('/')[-1]
                if audio_format == 'mpeg' or audio_format == 'mp3':
                    suffix = '.mp3'
                elif audio_format == 'wav':
                    suffix = '.wav'
                else:
                    suffix = '.' + audio_format
            else:
                # Content-Type이 없으면 기본값
                suffix = '.mp3'
            
            # 임시 파일로 저장
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                temp_file.write(audio_data)
                temp_file_path = temp_file.name
            
            # 음성 재생 큐에 추가
            self.audio_queue.put(temp_file_path)
            
            # 응답
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            
            response = {
                "status": "success",
                "message": "음성파일이 재생 큐에 추가되었습니다.",
                "filename": os.path.basename(temp_file_path)
            }
            self.wfile.write(json.dumps(response, ensure_ascii=False).encode('utf-8'))
            
            # 음성 재생 시작 (별도 스레드)
            if not self.is_playing:
                threading.Thread(target=self._play_audio_queue, daemon=True).start()
                
        except Exception as e:
            self.send_error(500, f"오류 발생: {str(e)}")
    
    def do_GET(self):
        """GET 요청으로 상태 확인"""
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        
        if path == '/status':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            
            status = {
                "status": "running",
                "queue_size": self.audio_queue.qsize(),
                "is_playing": self.is_playing,
                "timestamp": time.time()
            }
            self.wfile.write(json.dumps(status, ensure_ascii=False).encode('utf-8'))
        
        elif path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"OK")
        
        else:
            self.send_error(404, "페이지를 찾을 수 없습니다.")
    
    def _play_audio_queue(self):
        """음성 재생 큐를 처리하는 함수"""
        self.is_playing = True
        
        while True:
            try:
                # 큐에서 음성파일 가져오기
                audio_file = self.audio_queue.get(timeout=1)
                
                if audio_file and os.path.exists(audio_file):
                    print(f"[음성재생] {os.path.basename(audio_file)} 재생 시작")
                    
                    try:
                        # pygame으로 음성 재생
                        pygame.mixer.music.load(audio_file)
                        pygame.mixer.music.play()
                        
                        # 재생이 끝날 때까지 대기
                        while pygame.mixer.music.get_busy():
                            time.sleep(0.1)
                        
                        print(f"[음성재생] {os.path.basename(audio_file)} 재생 완료")
                        
                    except Exception as e:
                        print(f"[오류] pygame 음성 재생 실패: {e}")
                    
                    # 임시 파일 삭제
                    try:
                        os.unlink(audio_file)
                        print(f"[음성재생] 파일 삭제 완료")
                    except:
                        pass
                
                self.audio_queue.task_done()
                
            except queue.Empty:
                # 큐가 비어있으면 대기
                continue
            except Exception as e:
                print(f"[오류] 음성 재생 중 오류: {e}")
                continue
    
    def log_message(self, format, *args):
        """로그 메시지 커스터마이징"""
        print(f"[VoiceServer] {format % args}")

def start_voice_server(host='localhost', port=8080):
    """음성 서버 시작"""
    server_address = (host, port)
    httpd = HTTPServer(server_address, VoiceRequestHandler)
    
    print(f"[VoiceServer] 음성 서버가 시작되었습니다.")
    print(f"[VoiceServer] 주소: http://{host}:{port}")
    print(f"[VoiceServer] 음성 재생 엔드포인트: POST http://{host}:{port}/")
    print(f"[VoiceServer] 상태 확인: GET http://{host}:{port}/status")
    print(f"[VoiceServer] 서버 중지: Ctrl+C")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[VoiceServer] 서버를 종료합니다...")
        httpd.shutdown()

if __name__ == "__main__":
    # 서버 시작
    start_voice_server()
