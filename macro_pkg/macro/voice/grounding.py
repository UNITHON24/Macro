from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable, Optional, Sequence, Tuple

from .errors import GroundingError
from .perception import ObservedElement, ScreenObservation


def normalize_text(value: str) -> str:
    return "".join(str(value or "").split()).casefold()


@dataclass(frozen=True)
class Target:
    key: str
    labels: Tuple[str, ...]
    roles: Tuple[str, ...] = ()
    fallback_xy: Optional[Tuple[int, int]] = None
    region: Optional[Tuple[float, float, float, float]] = None


@dataclass(frozen=True)
class GroundedTarget:
    target: Target
    element: ObservedElement
    score: float


def _label_score(label: str, actual: str) -> float:
    wanted = normalize_text(label)
    observed = normalize_text(actual)
    if not wanted or not observed:
        return 0.0
    if wanted == observed:
        return 1.0
    if wanted in observed or observed in wanted:
        return 0.91
    return SequenceMatcher(None, wanted, observed).ratio()


def _has_exact_label(labels: Sequence[str], actual: str) -> bool:
    observed = normalize_text(actual)
    return bool(observed) and any(
        normalize_text(label) == observed for label in labels if normalize_text(label)
    )


def ground_target(
    observation: ScreenObservation,
    target: Target,
    *,
    cutoff: float = 0.82,
    ambiguity_margin: float = 0.08,
) -> GroundedTarget:
    ranked = []
    wanted_roles = {role.casefold() for role in target.roles}
    for element in observation.elements:
        if target.region is not None:
            left, top, right, bottom = target.region
            center_x, center_y = element.rect.center
            normalized_x = (center_x - observation.origin_x) / max(1, observation.width)
            normalized_y = (center_y - observation.origin_y) / max(1, observation.height)
            if not (left <= normalized_x <= right and top <= normalized_y <= bottom):
                continue
        score = max((_label_score(label, element.text) for label in target.labels), default=0.0)
        role_match = bool(
            wanted_roles and element.role.casefold() in wanted_roles
        )
        if role_match:
            score += 0.04
        if element.source == "uia":
            score += 0.02
        if element.source == "ocr":
            # OCR confidence contributes evidence without making a correctly
            # recognized label unusable solely because its glyph score is low.
            score *= 0.75 + 0.25 * max(0.0, min(1.0, element.confidence))
        ranked.append(
            (
                min(score, 1.0),
                _has_exact_label(target.labels, element.text),
                role_match,
                element.source == "uia",
                element,
            )
        )
    ranked.sort(key=lambda item: item[:4], reverse=True)
    if not ranked or ranked[0][0] < cutoff:
        raise GroundingError(f"visible target not found: {target.key}")
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < ambiguity_margin:
        first, second = ranked[0][4], ranked[1][4]
        stronger_semantics = (
            (ranked[0][1] and not ranked[1][1])
            or (ranked[0][2] and not ranked[1][2])
        )
        same_control = (
            normalize_text(first.text) == normalize_text(second.text)
            and abs(first.rect.center[0] - second.rect.center[0]) < 20
            and abs(first.rect.center[1] - second.rect.center[1]) < 20
        )
        if not stronger_semantics and not same_control:
            raise GroundingError(
                f"ambiguous visible target: {target.key} "
                f"({first.text!r} vs {second.text!r})"
            )
    return GroundedTarget(target, ranked[0][4], ranked[0][0])


def contains_any_text(observation: ScreenObservation, labels: Iterable[str]) -> bool:
    normalized = [normalize_text(label) for label in labels if normalize_text(label)]
    return any(
        wanted == normalize_text(actual) or wanted in normalize_text(actual)
        for wanted in normalized
        for actual in observation.texts
        if normalize_text(actual)
    )


def scale_point(
    point: Tuple[int, int],
    reference_size: Tuple[int, int],
    actual_size: Tuple[int, int],
) -> Tuple[int, int]:
    ref_w, ref_h = reference_size
    width, height = actual_size
    if min(ref_w, ref_h, width, height) <= 0:
        raise ValueError("screen dimensions must be positive")
    return (round(point[0] * width / ref_w), round(point[1] * height / ref_h))
