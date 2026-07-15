from __future__ import annotations

import hashlib
import platform
import re
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def center(self) -> Tuple[int, int]:
        return ((self.left + self.right) // 2, (self.top + self.bottom) // 2)

    @property
    def area(self) -> int:
        return max(0, self.right - self.left) * max(0, self.bottom - self.top)


@dataclass(frozen=True)
class ObservedElement:
    text: str
    rect: Rect
    role: str = "unknown"
    source: str = "unknown"
    confidence: float = 1.0
    automation_id: str = ""
    selected: Optional[bool] = None
    native: Any = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class ScreenObservation:
    elements: Tuple[ObservedElement, ...]
    width: int
    height: int
    visual_hash: str = ""
    origin_x: int = 0
    origin_y: int = 0
    captured_at: float = field(default_factory=time.monotonic)

    @property
    def signature(self) -> str:
        rows = sorted(
            (
                _normalize(element.text),
                element.role.casefold(),
                round((element.rect.left - self.origin_x) / max(1, self.width), 3),
                round((element.rect.top - self.origin_y) / max(1, self.height), 3),
                element.selected,
                element.automation_id,
            )
            for element in self.elements
            if _normalize(element.text)
        )
        return hashlib.sha256(repr((rows, self.visual_hash)).encode("utf-8")).hexdigest()

    @property
    def texts(self) -> Tuple[str, ...]:
        return tuple(element.text for element in self.elements if element.text.strip())


def _normalize(value: str) -> str:
    return "".join(str(value or "").split()).casefold()


class UIAutomationProvider:
    """Read and invoke controls exposed by Windows UI Automation.

    The import stays lazy so deterministic tests and OCR-only operation remain
    platform independent.
    """

    def __init__(self, window_title: str = "", max_depth: int = 10):
        self.window_title = window_title.strip()
        self.max_depth = max_depth
        self.window_handle: Optional[int] = None
        self.last_root_rect: Optional[Rect] = None

    def bind_window(self, window_handle: Any) -> None:
        try:
            self.window_handle = int(window_handle)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("invalid target window handle") from exc

    def _root(self, automation: Any) -> Any:
        if self.window_handle is not None:
            control = automation.ControlFromHandle(self.window_handle)
            if control is None or int(
                getattr(control, "NativeWindowHandle", self.window_handle)
            ) != self.window_handle:
                raise RuntimeError("UIA target window handle did not match")
            return control
        if self.window_title:
            control = automation.WindowControl(
                searchDepth=2,
                RegexName=f"^{re.escape(self.window_title)}$",
            )
            if control.Exists(1, 0.1):
                return control
            raise RuntimeError(f"UIA window not found: {self.window_title}")
        foreground = getattr(automation, "GetForegroundControl", None)
        return foreground() if foreground else automation.GetRootControl()

    @staticmethod
    def _rect(raw: Any) -> Optional[Rect]:
        try:
            if all(hasattr(raw, name) for name in ("left", "top", "right", "bottom")):
                left, top, right, bottom = (
                    int(raw.left),
                    int(raw.top),
                    int(raw.right),
                    int(raw.bottom),
                )
            else:
                left, top, right, bottom = (int(raw[index]) for index in range(4))
        except (AttributeError, IndexError, TypeError, ValueError):
            return None
        rect = Rect(left, top, right, bottom)
        return rect if rect.area > 0 else None

    @staticmethod
    def _visible_and_enabled(control: Any) -> bool:
        try:
            return not bool(getattr(control, "IsOffscreen", False)) and bool(
                getattr(control, "IsEnabled", True)
            )
        except Exception:
            return False

    @staticmethod
    def _inside_root(rect: Rect, root_rect: Optional[Rect]) -> bool:
        if root_rect is None:
            return True
        center_x, center_y = rect.center
        return (
            root_rect.left <= center_x <= root_rect.right
            and root_rect.top <= center_y <= root_rect.bottom
        )

    def observe(self) -> List[ObservedElement]:
        if platform.system() != "Windows":
            return []
        import uiautomation as automation  # type: ignore

        root = self._root(automation)
        self.last_root_rect = self._rect(getattr(root, "BoundingRectangle", None))
        found: List[ObservedElement] = []
        stack: List[Tuple[Any, int]] = [(root, 0)]
        while stack:
            control, depth = stack.pop()
            try:
                text = str(getattr(control, "Name", "") or "").strip()
                role = str(getattr(control, "ControlTypeName", "") or "unknown")
                rect = self._rect(getattr(control, "BoundingRectangle", None))
                if (
                    text
                    and rect
                    and self._visible_and_enabled(control)
                    and self._inside_root(rect, self.last_root_rect)
                ):
                    selected = None
                    try:
                        selected = bool(control.GetSelectionItemPattern().IsSelected)
                    except Exception:
                        pass
                    found.append(
                        ObservedElement(
                            text=text,
                            rect=rect,
                            role=role,
                            source="uia",
                            confidence=1.0,
                            automation_id=str(getattr(control, "AutomationId", "") or ""),
                            selected=selected,
                            native=control,
                        )
                    )
                if depth < self.max_depth:
                    stack.extend((child, depth + 1) for child in control.GetChildren())
            except Exception:
                continue
        return found

    @staticmethod
    def invoke(element: ObservedElement) -> bool:
        control = element.native
        if control is None:
            return False
        try:
            pattern = control.GetInvokePattern()
            pattern.Invoke()
            return True
        except Exception:
            return False


class OCRProvider:
    """Capture the configured monitor and locate visible text with EasyOCR."""

    def __init__(
        self,
        monitor_index: int = 1,
        model_dir: str = "",
        allow_download: bool = False,
    ):
        self.monitor_index = monitor_index
        self.model_dir = model_dir
        self.allow_download = allow_download
        self._reader: Any = None

    def _reader_instance(self) -> Any:
        if self._reader is None:
            import easyocr  # type: ignore

            options = {"gpu": False, "download_enabled": self.allow_download}
            if self.model_dir:
                options["model_storage_directory"] = self.model_dir
            self._reader = easyocr.Reader(["ko", "en"], **options)
        return self._reader

    def observe(
        self, region: Optional[dict] = None
    ) -> Tuple[List[ObservedElement], int, int, str, int, int]:
        import mss  # type: ignore
        import numpy as np  # type: ignore

        with mss.mss() as capture:
            if region is None:
                if self.monitor_index >= len(capture.monitors):
                    raise RuntimeError(f"monitor index is unavailable: {self.monitor_index}")
                monitor = capture.monitors[self.monitor_index]
            else:
                monitor = region
            shot = capture.grab(monitor)
            image = np.asarray(shot)[:, :, :3]
            sample = image[::32, ::32].mean(axis=2)
            # Average-hash style fingerprint ignores minor color/noise changes
            # while still detecting layout, modal, and selection transitions.
            visual_hash = hashlib.sha256((sample > sample.mean()).tobytes()).hexdigest()
        offset_x, offset_y = int(monitor["left"]), int(monitor["top"])
        elements: List[ObservedElement] = []
        for box, text, confidence in self._reader_instance().readtext(image):
            if not str(text).strip() or float(confidence) < 0.30:
                continue
            xs = [int(point[0]) for point in box]
            ys = [int(point[1]) for point in box]
            elements.append(
                ObservedElement(
                    text=str(text).strip(),
                    rect=Rect(
                        min(xs) + offset_x,
                        min(ys) + offset_y,
                        max(xs) + offset_x,
                        max(ys) + offset_y,
                    ),
                    role="text",
                    source="ocr",
                    confidence=float(confidence),
                )
            )
        return (
            elements,
            int(monitor["width"]),
            int(monitor["height"]),
            visual_hash,
            offset_x,
            offset_y,
        )


class HybridScreenObserver:
    """Combine UI Automation semantics with an OCR fallback for black-box kiosks."""

    def __init__(self, cfg: Any):
        self.window_title = str(getattr(cfg, "kiosk_window_title", "")).strip()
        self._window_handle: Any = None
        self._force_ocr = False
        self.uia = (
            UIAutomationProvider(getattr(cfg, "kiosk_window_title", ""))
            if getattr(cfg, "uia_enabled", True)
            else None
        )
        self.ocr = (
            OCRProvider(
                monitor_index=int(getattr(cfg, "monitor_index", 1)),
                model_dir=str(getattr(cfg, "ocr_model_dir", "")),
                allow_download=bool(getattr(cfg, "ocr_allow_download", False)),
            )
            if getattr(cfg, "ocr_enabled", True)
            else None
        )

    def _target_region(self) -> Optional[dict]:
        if not self.window_title or platform.system() != "Windows":
            return None
        import pygetwindow  # type: ignore

        windows = [
            window
            for window in pygetwindow.getAllWindows()
            if getattr(window, "width", 0) > 0
            and getattr(window, "height", 0) > 0
            and self.window_title.casefold() in str(getattr(window, "title", "")).casefold()
        ]
        exact = [
            window
            for window in windows
            if str(getattr(window, "title", "")).strip().casefold()
            == self.window_title.casefold()
        ]
        candidates = exact or windows
        if len(candidates) != 1:
            raise RuntimeError(
                f"target window must match exactly once: {self.window_title} "
                f"(found {len(candidates)})"
            )
        window = candidates[0]
        if bool(getattr(window, "isMinimized", False)):
            raise RuntimeError("target kiosk window is minimized")
        handle = getattr(window, "_hWnd", str(getattr(window, "title", "")))
        if self._window_handle is None:
            self._window_handle = handle
        elif handle != self._window_handle:
            raise RuntimeError("target kiosk window identity changed")
        return {
            "left": int(window.left),
            "top": int(window.top),
            "width": int(window.width),
            "height": int(window.height),
        }
    @staticmethod
    def _deduplicate(elements: Iterable[ObservedElement]) -> Tuple[ObservedElement, ...]:
        kept: List[ObservedElement] = []
        for candidate in sorted(
            elements,
            key=lambda item: (item.source != "uia", -item.confidence),
        ):
            normalized = _normalize(candidate.text)
            duplicate = any(
                _normalize(existing.text) == normalized
                and abs(existing.rect.center[0] - candidate.rect.center[0]) < 20
                and abs(existing.rect.center[1] - candidate.rect.center[1]) < 20
                for existing in kept
            )
            if not duplicate:
                kept.append(candidate)
        return tuple(kept)

    def observe(self) -> ScreenObservation:
        elements: List[ObservedElement] = []
        width = height = 0
        origin_x = origin_y = 0
        errors: List[str] = []
        try:
            target_region = self._target_region()
        except Exception as exc:
            raise RuntimeError(f"target window binding failed: {exc}") from exc
        if self.uia is not None:
            try:
                if self._window_handle is not None:
                    self.uia.bind_window(self._window_handle)
                elements.extend(self.uia.observe())
                if target_region is None and self.uia.last_root_rect is not None:
                    rect = self.uia.last_root_rect
                    origin_x, origin_y = rect.left, rect.top
                    width, height = rect.right - rect.left, rect.bottom - rect.top
            except Exception as exc:
                errors.append(f"UIA: {exc}")
        if self.ocr is not None and (self._force_ocr or not elements):
            try:
                (
                    ocr_elements,
                    width,
                    height,
                    visual_hash,
                    origin_x,
                    origin_y,
                ) = self.ocr.observe(target_region)
                elements.extend(ocr_elements)
            except Exception as exc:
                errors.append(f"OCR: {exc}")
        if not elements:
            detail = "; ".join(errors) or "all perception providers are disabled"
            raise RuntimeError(f"screen observation failed: {detail}")
        if target_region is not None and (width <= 0 or height <= 0):
            origin_x = int(target_region["left"])
            origin_y = int(target_region["top"])
            width = int(target_region["width"])
            height = int(target_region["height"])
        elif width <= 0 or height <= 0:
            right = max((item.rect.right for item in elements), default=1)
            bottom = max((item.rect.bottom for item in elements), default=1)
            width, height = right - origin_x, bottom - origin_y
        return ScreenObservation(
            self._deduplicate(elements),
            width,
            height,
            visual_hash=locals().get("visual_hash", ""),
            origin_x=origin_x,
            origin_y=origin_y,
        )

    def observe_with_ocr(self) -> ScreenObservation:
        """Enable the OCR fallback after UIA could not resolve a target."""
        self._force_ocr = True
        return self.observe()

    def invoke(self, element: ObservedElement) -> bool:
        return bool(self.uia and element.source == "uia" and self.uia.invoke(element))
