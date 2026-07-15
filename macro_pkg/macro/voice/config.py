from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = PACKAGE_ROOT.parent
SETTINGS_ROOT = PACKAGE_ROOT / "settingPack"


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _env_positive_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _env_positive_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


@dataclass
class Config:
    """Runtime configuration evaluated when a client instance is created."""

    ui_coords_path: str = field(
        default_factory=lambda: _env(
            "KIOSK_UI_COORDS", str(SETTINGS_ROOT / "kiosk_ui_coords_easyocr.json")
        )
    )
    menu_cards_path: str = field(
        default_factory=lambda: _env(
            "KIOSK_MENU_CARDS", str(SETTINGS_ROOT / "menu_cards.json")
        )
    )
    profile_path: str = field(
        default_factory=lambda: _env(
            "KIOSK_PROFILE", str(SETTINGS_ROOT / "kiosk_profile.json")
        )
    )

    audio_ws_url: str = field(
        default_factory=lambda: _env("KIOSK_AUDIO_WS_URL", "ws://localhost:8080/chat")
    )
    orders_url: str = field(
        default_factory=lambda: _env("KIOSK_ORDERS_URL", "http://localhost:9999/api/orders")
    )
    orders_token: str = field(
        default_factory=lambda: _env("KIOSK_ORDER_TOKEN", "").strip()
    )
    orders_poll_interval_sec: float = field(
        default_factory=lambda: float(_env("KIOSK_ORDERS_POLL_SEC", "0.1"))
    )

    sample_rate: int = field(default_factory=lambda: int(_env("KIOSK_SAMPLE_RATE", "16000")))
    frame_ms: int = field(default_factory=lambda: int(_env("KIOSK_FRAME_MS", "20")))
    vad_level: int = field(default_factory=lambda: int(_env("KIOSK_VAD_LEVEL", "2")))
    rms_min_speech: int = field(default_factory=lambda: int(_env("KIOSK_RMS_MIN_SPEECH", "35")))
    silence_timeout_sec: int = field(
        default_factory=lambda: int(_env("KIOSK_SILENCE_TIMEOUT_SEC", "60"))
    )

    # Real desktop input and navigation beyond the cart are separate opt-ins.
    dry_run: bool = field(default_factory=lambda: _env_bool("KIOSK_DRY_RUN", True))
    allow_payment_navigation: bool = field(
        default_factory=lambda: _env_bool(
            "KIOSK_ALLOW_PAYMENT_NAVIGATION",
            _env_bool("KIOSK_ALLOW_CHECKOUT", False),
        )
    )
    # Compatibility for callers written against the original prototype.
    allow_checkout: bool = field(init=False)
    checkout_x: int = field(default_factory=lambda: int(_env("KIOSK_CHECKOUT_X", "989")))
    checkout_y: int = field(default_factory=lambda: int(_env("KIOSK_CHECKOUT_Y", "1880")))
    page_click_delay: float = field(
        default_factory=lambda: float(_env("KIOSK_PAGE_DELAY", "1.00"))
    )
    cat_click_delay: float = field(
        default_factory=lambda: float(_env("KIOSK_CAT_DELAY", "1.00"))
    )
    item_click_delay: float = field(
        default_factory=lambda: float(_env("KIOSK_ITEM_DELAY", "1.00"))
    )
    transition_timeout_sec: float = field(
        default_factory=lambda: _env_positive_float("KIOSK_TRANSITION_TIMEOUT_SEC", 4.0)
    )
    transition_poll_sec: float = field(
        default_factory=lambda: _env_positive_float("KIOSK_TRANSITION_POLL_SEC", 0.20)
    )
    match_cutoff: float = field(
        default_factory=lambda: _env_positive_float("KIOSK_MATCH_CUTOFF", 0.82)
    )
    ambiguity_margin: float = field(
        default_factory=lambda: _env_positive_float("KIOSK_AMBIGUITY_MARGIN", 0.08)
    )
    allow_coordinate_fallback: bool = field(
        default_factory=lambda: _env_bool("KIOSK_ALLOW_COORDINATE_FALLBACK", False)
    )
    reference_width: int = field(
        default_factory=lambda: _env_positive_int("KIOSK_REFERENCE_WIDTH", 1080)
    )
    reference_height: int = field(
        default_factory=lambda: _env_positive_int("KIOSK_REFERENCE_HEIGHT", 1920)
    )

    uia_enabled: bool = field(default_factory=lambda: _env_bool("KIOSK_UIA_ENABLED", True))
    ocr_enabled: bool = field(default_factory=lambda: _env_bool("KIOSK_OCR_ENABLED", True))
    kiosk_window_title: str = field(
        default_factory=lambda: _env("KIOSK_WINDOW_TITLE", "")
    )
    monitor_index: int = field(
        default_factory=lambda: _env_positive_int("KIOSK_MONITOR_INDEX", 1)
    )
    ocr_model_dir: str = field(
        default_factory=lambda: _env("KIOSK_OCR_MODEL_DIR", str(PACKAGE_ROOT / "models"))
    )
    ocr_allow_download: bool = field(
        default_factory=lambda: _env_bool("KIOSK_OCR_ALLOW_DOWNLOAD", False)
    )
    max_order_items: int = field(
        default_factory=lambda: _env_positive_int("KIOSK_MAX_ORDER_ITEMS", 10)
    )
    max_item_quantity: int = field(
        default_factory=lambda: _env_positive_int("KIOSK_MAX_ITEM_QUANTITY", 10)
    )

    ws_connect_timeout: float = field(
        default_factory=lambda: float(_env("KIOSK_WS_TIMEOUT", "5.0"))
    )
    ws_max_size: int = field(
        default_factory=lambda: int(_env("KIOSK_WS_MAX_SIZE", "1048576"))
    )

    tts_fallback_sec: float = field(
        default_factory=lambda: float(_env("KIOSK_TTS_FALLBACK_SEC", "0.8"))
    )
    tts_prefer_pygame_fallback: bool = field(
        default_factory=lambda: _env_bool("KIOSK_TTS_PYGAME_ONLY", False)
    )

    order_result_retries: int = field(
        default_factory=lambda: _env_positive_int("KIOSK_ORDER_RESULT_RETRIES", 3)
    )

    def __post_init__(self) -> None:
        self.allow_checkout = self.allow_payment_navigation
