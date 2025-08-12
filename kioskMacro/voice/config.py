import os
from dataclasses import dataclass

@dataclass
class Config:
    # Base paths (match your repo: kioskMacro/settingPack/*.json)
    ui_coords_path: str = os.environ.get("KIOSK_UI_COORDS", os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "settingPack", "kiosk_ui_coords_easyocr.json"))
    menu_cards_path: str = os.environ.get("KIOSK_MENU_CARDS", os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "settingPack", "menu_cards.json"))

    # Audio WebSocket endpoint
    audio_ws_url: str = os.environ.get("KIOSK_AUDIO_WS_URL", "ws://localhost:8080/api/chat")

    # Orders API (HTTP polling)
    orders_url: str = os.environ.get("KIOSK_ORDERS_URL", "http://localhost:9999/api/orders")
    orders_poll_interval_sec: float = float(os.environ.get("KIOSK_ORDERS_POLL_SEC", "0.1"))

    # Audio/VAD
    sample_rate: int = int(os.environ.get("KIOSK_SAMPLE_RATE", "16000"))
    frame_ms: int = int(os.environ.get("KIOSK_FRAME_MS", "20"))
    vad_level: int = int(os.environ.get("KIOSK_VAD_LEVEL", "2"))  # 0..3 (낮출수록 민감)
    rms_min_speech: int = int(os.environ.get("KIOSK_RMS_MIN_SPEECH", "35"))
    silence_timeout_sec: int = int(os.environ.get("KIOSK_SILENCE_TIMEOUT_SEC", "60"))

    # Macro behavior
    dry_run: bool = os.environ.get("KIOSK_DRY_RUN", "0") == "1"
    page_click_delay: float = float(os.environ.get("KIOSK_PAGE_DELAY", "1.00"))
    cat_click_delay: float = float(os.environ.get("KIOSK_CAT_DELAY", "1.00"))
    item_click_delay: float = float(os.environ.get("KIOSK_ITEM_DELAY", "1.00"))
    
    # WebSocket connection settings
    ws_connect_timeout: float = float(os.environ.get("KIOSK_WS_TIMEOUT", "5.0"))
    ws_max_size: int = int(os.environ.get("KIOSK_WS_MAX_SIZE", "1048576"))  # 1MB
