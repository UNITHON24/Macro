from __future__ import annotations

# 1) 먼저: Tcl/Tk 경로 보정
import os, sys, pathlib

def _ensure_tcl_tk_path():
    if sys.platform != "win32":
        return
    tcl_versions = ["8.7", "8.6"]
    base = pathlib.Path(sys.base_prefix)
    for ver in tcl_versions:
        tcl_dir = base / "tcl" / f"tcl{ver}"
        tk_dir  = base / "tcl" / f"tk{ver}"
        if tcl_dir.is_dir() and tk_dir.is_dir():
            os.environ.setdefault("TCL_LIBRARY", str(tcl_dir))
            os.environ.setdefault("TK_LIBRARY",  str(tcl_dir))
            return
    guesses = [
        fr"C:\\Users\\{os.getlogin()}\\AppData\\Local\\Programs\\Python\\Python313\\tcl",
        fr"C:\\Users\\{os.getlogin()}\\AppData\\Local\\Programs\\Python\\Python312\\tcl",

        r"C:\\Python313\\tcl",
        r"C:\\Python312\\tcl",
    ]
    for g in guesses:
        for ver in tcl_versions:
            tcl_dir = pathlib.Path(g) / f"tcl{ver}"
            tk_dir  = pathlib.Path(g) / f"tk{ver}"
            if tcl_dir.is_dir() and tk_dir.is_dir():
                os.environ.setdefault("TCL_LIBRARY", str(tcl_dir))
                os.environ.setdefault("TK_LIBRARY",  str(tcl_dir))
                return

_ensure_tcl_tk_path()

# 2) 그 다음에 tkinter import
import tkinter as tk
import queue
import threading
import time
import numpy as np

from .config import Config
from .index_loader import MenuIndex
from .navigator import Navigator
from .macro import OrderMacro
from .audio import AudioStreamer
from .audio_ws import AudioWSClient
from .orders_client import OrdersClient


class MicOverlay:
    def __init__(self):
        self.cfg = Config()
        self.root = tk.Tk()
        # DPI 스케일 고정 (좌표 일치 보장)
        try:
            self.root.tk.call('tk', 'scaling', 1.0)
        except Exception:
            pass
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.95)
        self.root.geometry("80x80+50+50")  # 1080x1920 해상도에 맞게 크기 조정
        # Windows 투명색 설정: 캔버스와 루트 배경을 동일한 키 컬러로 지정
        try:
            self.root.configure(bg="magenta")
            self.root.attributes("-transparentcolor", "magenta")
        except Exception:
            pass

        self.canvas = tk.Canvas(self.root, width=80, height=80, highlightthickness=0, bg="magenta")
        self.canvas.pack(fill="both", expand=True)

        self.state = "idle"  # idle | rec
        self._pulse = 0       # 녹음 상태 맥동 애니메이션 프레임
        self.canvas.bind("<Button-1>", self._on_click)

        # drag move
        self._drag_start = None
        self.canvas.bind("<Button-1>", self._on_press, add="+")
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        # pipeline
        try:
            self.index = MenuIndex(self.cfg.ui_coords_path, self.cfg.menu_cards_path)
            self.nav = Navigator(self.index, self.cfg)
            self.macro = OrderMacro(self.nav)
            print("[INIT] 메뉴 인덱스 로드 성공")
        except Exception as e:
            print(f"[ERR] 메뉴 인덱스 로드 실패: {e}")
            self.index = None
            self.nav = None
            self.macro = None

        self.frame_q: "queue.Queue[bytes]" = queue.Queue(maxsize=50)
        self.audio = AudioStreamer(self.cfg, self.frame_q)
        # 매크로/오버레이 참조를 WebSocket 클라이언트에도 넘겨 macro.trigger 즉시 실행
        self.ws = AudioWSClient(self.cfg, self.frame_q, on_server_stop=self.stop_from_server, macro=self.macro, overlay=self)
        self.orders = OrdersClient(self.cfg, self.macro, on_server_stop=self.stop_from_server)
        
        # 주문 처리 중 마이크 종료 방지
        self.processing_order = False
        self.last_speech_time = time.monotonic()
        
        # 백엔드 요청: 5초마다 마이크 껐다가 켜기
        self.mic_pulse_enabled = False  # 백엔드에서 활성화 요청 시 True
        self.mic_pulse_timer = None
        self.mic_pulse_interval = 5.0  # 5초 간격
        self.mic_pulse_auto = False  # 자동 펄스 모드 (백엔드 신호 없이 자동 동작)
        
        # 자동 펄스 모드 비활성화 (마이크 활성화 시 자동 시작하지 않음)
        self.auto_pulse_on_recording = False

        # 짧은 무음 기반 발화 단위 펄스 설정
        self.utterance_pulse_enabled = True
        self.utterance_silence_sec = 0.8   # 이 시간 이상 무음이면 한 번 끊어 최종 인식 유도
        self.utterance_resume_delay_ms = 300  # 끊은 뒤 재개까지 대기 시간
        self.utterance_cooldown_sec = 1.5  # 펄스 간 최소 간격
        self._last_utterance_pulse_ts = 0.0
        
        # orders_client에 오버레이 참조 설정
        self.orders.set_overlay(self)
        
        # 마이크 버튼 이미지 설정 (1.5배 크기)
        self.mic_images = self._load_mic_images()
        
        # 이미지 파일 안내
        if not self.mic_images.get("idle") or not self.mic_images.get("active"):
            print("\n" + "="*60)
            print("📸 마이크 버튼 이미지 설정 안내")
            print("="*60)
            print("다음 이미지 파일을 kioskMacro/micPic 폴더에 넣어주세요:")
            print("• unmic.png      - 비활성화 상태 이미지 (80x80 권장)")
            print("• mic.png        - 활성화 상태 이미지 (80x80 권장)")
            print("이미지가 없으면 기본 도형으로 그려집니다.")
            print("="*60)
        
        # 주문 수신 시작
        if self.orders:
            self.orders.set_overlay(self)  # 오버레이 참조 설정
            self.orders.start()
            print("[INIT] 주문 수신 시작")

        self._draw()
        self._tick()

    def _load_mic_images(self):
        """마이크 버튼 이미지 로딩 (1.5배 크기)"""
        try:
            from PIL import Image, ImageTk
            
            # 이미지 파일 경로 (kioskMacro/micPic 폴더에 위치)
            # run_voice.py가 kioskMacro 폴더에서 실행되므로 한 단계 더 위로
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            mic_pic_dir = os.path.join(project_root, "micPic")
            idle_image_path = os.path.join(mic_pic_dir, "unmic.png")      # 비활성화 상태 이미지
            active_image_path = os.path.join(mic_pic_dir, "mic.png")      # 활성화 상태 이미지
            
            print(f"[DEBUG] 프로젝트 루트: {project_root}")
            print(f"[DEBUG] micPic 폴더: {mic_pic_dir}")
            print(f"[DEBUG] 비활성화 이미지 경로: {idle_image_path}")
            print(f"[DEBUG] 활성화 이미지 경로: {active_image_path}")
            
            images = {}
            
            # 비활성화 상태 이미지 로드 (1.5배 크기: 72x72 -> 108x108)
            if os.path.exists(idle_image_path):
                idle_img = Image.open(idle_image_path)
                print(f"[DEBUG] 비활성화 이미지 크기: {idle_img.size}")
                
                # 하얀색 배경 제거 (투명하게 만들기)
                idle_img = self._remove_white_background(idle_img)
                
                idle_img = idle_img.resize((80, 80), Image.Resampling.LANCZOS)
                images["idle"] = ImageTk.PhotoImage(idle_img)
                print(f"[IMAGE] 비활성화 이미지 로드 성공: {idle_image_path} (80x80, 배경 제거됨)")
            else:
                print(f"[IMAGE] 비활성화 이미지 없음: {idle_image_path}")
                images["idle"] = None
            
            # 활성화 상태 이미지 로드 (1.5배 크기: 72x72 -> 108x108)
            if os.path.exists(active_image_path):
                active_img = Image.open(active_image_path)
                print(f"[DEBUG] 활성화 이미지 크기: {active_img.size}")
                
                # 하얀색 배경 제거 (투명하게 만들기)
                active_img = self._remove_white_background(active_img)
                
                active_img = active_img.resize((80, 80), Image.Resampling.LANCZOS)
                images["active"] = ImageTk.PhotoImage(active_img)
                print(f"[IMAGE] 활성화 이미지 로드 성공: {active_image_path} (80x80, 배경 제거됨)")
            else:
                print(f"[IMAGE] 활성화 이미지 없음: {active_image_path}")
                images["active"] = None
            
            print(f"[DEBUG] 로드된 이미지: {list(images.keys())}")
            print(f"[DEBUG] images['idle'] 존재: {images.get('idle') is not None}")
            print(f"[DEBUG] images['active'] 존재: {images.get('active') is not None}")
                
            return images
            
        except ImportError:
            print("[IMAGE] PIL 라이브러리 없음 - 기본 도형으로 그리기")
            return {}
        except Exception as e:
            print(f"[IMAGE] 이미지 로드 오류: {e}")
            return {}

    def _remove_white_background(self, img):
        """하얀색 배경을 투명하게 만들어 동그라미 모양만 남기기"""
        try:
            # RGBA 모드로 변환 (투명도 지원)
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            
            # 이미지 데이터를 numpy 배열로 변환
            data = np.array(img)
            
            # 하얀색 픽셀 찾기 (RGB 값이 모두 높은 픽셀)
            # R, G, B가 모두 240 이상인 픽셀을 투명하게 만들기
            white_pixels = (data[:, :, 0] >= 240) & (data[:, :, 1] >= 240) & (data[:, :, 2] >= 240)
            
            # 투명도 채널(Alpha)을 0으로 설정 (완전 투명)
            data[white_pixels, 3] = 0
            
            # numpy 배열을 다시 PIL 이미지로 변환
            result_img = Image.fromarray(data)
            
            print(f"[IMAGE] 하얀색 배경 제거 완료: {img.size} -> 투명 배경")
            return result_img
            
        except Exception as e:
            print(f"[IMAGE] 배경 제거 실패: {e}")
            return img  # 실패하면 원본 이미지 반환

    def _draw(self):
        self.canvas.delete("all")

        # 이미지가 있으면 이미지 사용, 없으면 기본 도형 그리기
        print(f"[DEBUG] _draw 호출 - state: {self.state}")
        print(f"[DEBUG] mic_images 존재: {self.mic_images is not None}")
        print(f"[DEBUG] mic_images['idle'] 존재: {self.mic_images.get('idle') is not None if self.mic_images else False}")
        print(f"[DEBUG] mic_images['active'] 존재: {self.mic_images.get('active') is not None if self.mic_images else False}")
        
        if self.mic_images and self.mic_images.get("idle") and self.mic_images.get("active"):
            print(f"[DEBUG] 이미지 기반 그리기 사용")
            # 이미지 기반 그리기 (80x80 크기)
            if self.state == "idle":
                # 비활성화 상태 이미지
                self.canvas.create_image(40, 40, image=self.mic_images["idle"], anchor="center")
                print(f"[DEBUG] 비활성화 이미지 표시")
            else:
                # 활성화 상태 이미지
                self.canvas.create_image(40, 40, image=self.mic_images["active"], anchor="center")
                print(f"[DEBUG] 활성화 이미지 표시")
                
                # 활성화 상태에서만 맥동 링 추가 (이미지 위에 오버레이)
                if self.state == "rec":
                    ring = (self._pulse % 6)
                    ring_r = 35 + ring * 1.5  # 80x80 크기에 맞춰 조정
                    ring_color = "#86EFAC"  # 연한 그린
                    self.canvas.create_oval(40 - ring_r, 40 - ring_r, 40 + ring_r, 40 + ring_r,
                                            outline=ring_color, width=1)
        else:
            print(f"[DEBUG] 기본 도형 그리기 사용")
            # 기본 도형 그리기 (80x80 크기에 맞춰 조정)
            cx, cy = 40, 40  # 80x80 크기의 중심
            r_bg = 35        # 80x80 크기에 맞는 반지름

            if self.state == "idle":
                # 배경(흰색 원 + 연한 테두리)
                self.canvas.create_oval(cx - r_bg, cy - r_bg, cx + r_bg, cy + r_bg,
                                        fill="white", outline="#E5E7EB", width=2)

                # 마이크 본체(크기 2배)
                self.canvas.create_oval(cx - 22, cy - 22, cx + 22, cy + 22,
                                        fill="#F8FAFC", outline="#9BE7C4", width=2)
                # 스탠드(두께 약간 증가)
                self.canvas.create_rectangle(cx - 3, cy + 18, cx + 3, cy + 40,
                                             fill="#9BE7C4", outline="#7CCFAE", width=2)
                self.canvas.create_oval(cx - 15, cy + 40, cx + 15, cy + 48,
                                        fill="#9BE7C4", outline="#7CCFAE", width=2)
            else:
                # 녹음 배경(초록색)
                self.canvas.create_oval(cx - r_bg, cy - r_bg, cx + r_bg, cy + r_bg,
                                        fill="#22C55E", outline="#16A34A", width=2)

                # 맥동 링(부드러운 파장 느낌)
                ring = (self._pulse % 6)
                ring_r = r_bg + ring * 1.5
                ring_color = "#86EFAC"  # 연한 그린
                self.canvas.create_oval(cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r,
                                        outline=ring_color, width=1)

                # 마이크 본체(화이트, 크기 2배)
                self.canvas.create_oval(cx - 22, cy - 22, cx + 22, cy + 22,
                                        fill="white", outline="#14532D", width=2)
                # 스탠드(두께/길이 증가)
                self.canvas.create_rectangle(cx - 3, cy + 18, cx + 4, cy + 40,
                                             fill="#16A34A", outline="#14532D", width=2)
                self.canvas.create_oval(cx - 15, cy + 40, cx + 15, cy + 48,
                                        fill="#16A34A", outline="#7CCFAE", width=2)
                # 작은 빨간 REC 점
                self.canvas.create_oval(cx + 15, cy - 29, cx + 22, cy - 22, fill="#EF4444", outline="")

    # dragging
    def _on_press(self, e):
        self._drag_start = (e.x_root, e.y_root)

    def _on_drag(self, e):
        if not self._drag_start: return
        dx = e.x_root - self._drag_start[0]
        dy = e.y_root - self._drag_start[1]
        x = self.root.winfo_x() + dx
        y = self.root.winfo_y() + dy
        self.root.geometry(f"+{x}+{y}")
        self._drag_start = (e.x_root, e.y_root)

    def _on_release(self, _):
        self._drag_start = None

    def _on_click(self, _):
        if self.state == "idle":
            self.start_recording()
        else:
            self.stop_recording(user=True)

    def start_recording(self):
        if self.state == "rec": return
        self.state = "rec"
        self._draw()
        self.audio.start()
        self.ws.start()
        self.last_speech_time = time.monotonic()
        print("[REC] 녹음 시작")
        
        # 자동 펄스 모드 활성화 (마이크 활성화 시 자동 시작)
        if self.auto_pulse_on_recording:
            self.enable_auto_pulse(True)

    def stop_recording(self, user=False):
        if self.state != "rec": return
        
        # 주문 처리 중이면 마이크 종료 방지
        if self.processing_order:
            print("[REC] 주문 처리 중 - 마이크 종료 방지")
            return
            
        # 자동 펄스 모드 중지
        if self.auto_pulse_on_recording:
            self.enable_auto_pulse(False)
            
        self.state = "idle"
        self._draw()
        self.ws.stop()
        self.audio.stop()
        print(f"[REC] 녹음 종료 ({'사용자' if user else '서버'})")

    def stop_from_server(self):
        """백엔드 서버에서 마이크 종료 요청"""
        print("[SERVER] 서버에서 마이크 종료 요청")
        self.root.after(0, lambda: self.stop_recording(user=False))

    def set_processing_order(self, processing: bool):
        """주문 처리 상태 설정"""
        self.processing_order = processing
        if processing:
            print("[ORDER] 주문 처리 시작 - 마이크 종료 방지")
            # 오버레이가 클릭을 가로채지 않도록 일시적으로 숨김
            try:
                self._saved_geometry = self.root.geometry()
            except Exception:
                self._saved_geometry = None
            try:
                self.root.withdraw()
            except Exception:
                pass
        else:
            print("[ORDER] 주문 처리 완료 - 마이크 종료 가능")
            # 주문 처리 종료 후 오버레이 복원
            try:
                self.root.deiconify()
                if getattr(self, "_saved_geometry", None):
                    self.root.geometry(self._saved_geometry)
            except Exception:
                pass

    def enable_mic_pulse(self, enabled: bool):
        """백엔드 요청: 5초마다 마이크 껐다가 켜기 활성화/비활성화"""
        if enabled == self.mic_pulse_enabled:
            return  # 상태 변경 없음
            
        self.mic_pulse_enabled = enabled
        
        if enabled:
            print("[PULSE] 마이크 펄스 모드 활성화 (5초마다 껐다가 켜기)")
            self._start_mic_pulse()
        else:
            print("[PULSE] 마이크 펄스 모드 비활성화")
            self._stop_mic_pulse()

    def enable_auto_pulse(self, enabled: bool):
        """자동 펄스 모드 활성화/비활성화 (백엔드 신호 없이 자동 동작)"""
        if enabled == self.mic_pulse_auto:
            return  # 상태 변경 없음
            
        self.mic_pulse_auto = enabled
        
        if enabled:
            print("[AUTO-PULSE] 자동 마이크 펄스 모드 활성화 (5초마다 자동으로 껐다가 켜기)")
            self._start_auto_pulse()
        else:
            print("[AUTO-PULSE] 자동 마이크 펄스 모드 비활성화")
            self._stop_auto_pulse()

    def _start_mic_pulse(self):
        """마이크 펄스 타이머 시작"""
        if self.mic_pulse_timer:
            self.root.after_cancel(self.mic_pulse_timer)
        
        self._mic_pulse_cycle()

    def _stop_mic_pulse(self):
        """마이크 펄스 타이머 중지"""
        if self.mic_pulse_timer:
            self.root.after_cancel(self.mic_pulse_timer)
            self.mic_pulse_timer = None

    def _mic_pulse_cycle(self):
        """마이크 펄스 사이클 실행"""
        if not self.mic_pulse_enabled or self.state != "rec":
            return
            
        # 마이크 끄기
        print("[PULSE] 마이크 일시 중지 (백엔드 신호)")
        self.ws.stop()
        self.audio.stop()
        
        # 0.5초 후 마이크 다시 켜기
        self.root.after(500, self._mic_pulse_resume)
        
        # 다음 펄스 타이머 설정
        self.mic_pulse_timer = self.root.after(
            int(self.mic_pulse_interval * 1000), 
            self._mic_pulse_cycle
        )

    def _mic_pulse_resume(self):
        """마이크 펄스 후 재개"""
        if not self.mic_pulse_enabled or self.state != "rec":
            return
            
        print("[PULSE] 마이크 재개 (백엔드 신호)")
        self.audio.start()
        self.ws.start()

    def _start_auto_pulse(self):
        """자동 마이크 펄스 타이머 시작"""
        if self.mic_pulse_timer:
            self.root.after_cancel(self.mic_pulse_timer)
        
        self._auto_pulse_cycle()

    def _stop_auto_pulse(self):
        """자동 마이크 펄스 타이머 중지"""
        if self.mic_pulse_timer:
            self.root.after_cancel(self.mic_pulse_timer)
            self.mic_pulse_timer = None

    def _auto_pulse_cycle(self):
        """자동 마이크 펄스 사이클 실행"""
        if not self.mic_pulse_auto or self.state != "rec":
            return
            
        # 백엔드 서버로 마이크 꺼짐 신호 전송
        self._send_mic_status_to_backend("off")
        
        # 마이크 끄기 (오버레이 시각적 변화 없음)
        print("[AUTO-PULSE] 마이크 일시 중지 (백엔드 신호 전송)")
        self.ws.stop()
        self.audio.stop()
        
        # 0.5초 후 마이크 다시 켜기
        self.root.after(500, self._auto_pulse_resume)
        
        # 다음 펄스 타이머 설정
        self.mic_pulse_timer = self.root.after(
            int(self.mic_pulse_interval * 1000), 
            self._auto_pulse_cycle
        )

    def _auto_pulse_resume(self):
        """자동 마이크 펄스 후 재개"""
        if not self.mic_pulse_auto or self.state != "rec":
            return
            
        # 백엔드 서버로 마이크 켜짐 신호 전송
        self._send_mic_status_to_backend("on")
        
        print("[AUTO-PULSE] 마이크 재개 (백엔드 신호 전송)")
        self.audio.start()
        self.ws.start()

    def _send_mic_status_to_backend(self, status: str):
        """백엔드 서버로 마이크 상태 전송"""
        try:
            import requests
            payload = {
                "mic_status": status,
                "timestamp": time.time(),
                "auto_pulse": True
            }
            
            # 백엔드 서버로 마이크 상태 전송
            response = requests.post(
                f"{self.cfg.orders_url.replace('/api/orders', '/api/mic-status')}",
                json=payload,
                timeout=1
            )
            
            if response.status_code == 200:
                print(f"[BACKEND] 마이크 상태 전송 성공: {status}")
            else:
                print(f"[BACKEND] 마이크 상태 전송 실패: {response.status_code}")
                
        except Exception as e:
            print(f"[BACKEND] 마이크 상태 전송 오류: {e}")

    def _tick(self):
        if self.state == "rec":
            # 1분 무음 체크 (주문 처리 중이 아닐 때만)
            if not self.processing_order and self.audio.silence_timed_out():
                print("[AUTO] 1분 무음 종료")
                self.stop_recording(user=False)
            
            # 음성 감지 시간 업데이트
            if self.audio.last_speech_time > self.last_speech_time:
                self.last_speech_time = self.audio.last_speech_time
            
            # 발화 단위 펄스: 짧은 무음 구간에서만 1회 끊고 재개하여 STT 최종 인식 유도
            if (self.utterance_pulse_enabled and not self.mic_pulse_enabled and not self.mic_pulse_auto):
                now = time.monotonic()
                silence_for = now - self.audio.last_speech_time
                since_last_pulse = now - self._last_utterance_pulse_ts
                if (silence_for >= self.utterance_silence_sec and
                    since_last_pulse >= self.utterance_cooldown_sec):
                    print(f"[UTT] 짧은 무음 감지({silence_for:.2f}s) → 발화 단위 펄스 수행")
                    # 끊기: WebSocket은 유지하고 STT 최종화를 위해 audio.end만 전송
                    try:
                        self.ws.send_audio_end()
                    except Exception:
                        pass
                    self._last_utterance_pulse_ts = now
                    # 짧게 대기 후 재개: audio.start만 전송
                    self.root.after(self.utterance_resume_delay_ms, self._resume_after_utterance_pulse)
            
            # 마이크 펄스 모드가 활성화되어 있으면 1분 무음 체크 건너뛰기
            if not self.mic_pulse_enabled:
                # 녹음 중 애니메이션 프레임 증가 및 리드로우
                self._pulse = (self._pulse + 1) % 60
                self._draw()
                
        self.root.after(500, self._tick)

    def _resume_after_utterance_pulse(self):
        if self.state != "rec":
            return
        print("[UTT] 발화 단위 펄스 재개: audio.start 전송")
        try:
            self.ws.send_audio_start()
        except Exception as e:
            print(f"[UTT] 재개 오류: {e}")

    def run(self):
        try:
            self.root.mainloop()
        finally:
            try: self.ws.stop()
            except: pass
            try: self.audio.stop()
            except: pass
            try: self.orders.stop()
            except: pass
