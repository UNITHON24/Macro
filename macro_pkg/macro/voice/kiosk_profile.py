from __future__ import annotations

import json
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .errors import ProfileError
from .grounding import Target, normalize_text
from .transition_graph import Transition, TransitionGraph


@dataclass(frozen=True)
class MenuRecord:
    name: str
    category: str
    page: int
    fallback_xy: Tuple[int, int]


@dataclass(frozen=True)
class ResolvedOrderItem:
    requested_name: str
    menu: MenuRecord
    quantity: int
    option_targets: Tuple[Target, ...] = ()


class KioskProfile:
    """Versioned semantic contract for one black-box kiosk family."""

    def __init__(self, data: Mapping[str, Any], menu_records: Sequence[MenuRecord]):
        version = int(data.get("schema_version", 0))
        if version != 2:
            raise ProfileError(f"unsupported kiosk profile schema: {version}")
        self.data = dict(data)
        self.menu_records = tuple(menu_records)
        viewport = data.get("reference_viewport", {})
        self.reference_size = (
            int(viewport.get("width", 1080)),
            int(viewport.get("height", 1920)),
        )
        self.aliases = {
            str(key): tuple(str(label) for label in labels)
            for key, labels in (data.get("aliases", {}) or {}).items()
        }
        self.modifiers = data.get("modifiers", {}) or {}
        self.cart_added_markers = tuple(data.get("cart_added_markers", ()))
        self.confirm_labels = tuple(data.get("confirm_labels", ()))
        self.item_added_markers = tuple(data.get("item_added_markers", ()))
        raw_cart_region = data.get("cart_region")
        self.cart_region = (
            tuple(float(value) for value in raw_cart_region)
            if isinstance(raw_cart_region, list) and len(raw_cart_region) == 4
            else None
        )
        raw_menu_region = data.get("menu_region")
        self.menu_region = (
            tuple(float(value) for value in raw_menu_region)
            if isinstance(raw_menu_region, list) and len(raw_menu_region) == 4
            else None
        )

    @classmethod
    def load(cls, path: str, index: Any) -> "KioskProfile":
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        records = [
            MenuRecord(name, category, page, xy)
            for name, (category, page, xy) in index.name_to_entry.items()
        ]
        return cls(data, records)

    def labels(self, key: str, *defaults: str) -> Tuple[str, ...]:
        values = self.aliases.get(key, ())
        combined = [*values, *(value for value in defaults if value)]
        return tuple(dict.fromkeys(combined))

    def target(
        self,
        key: str,
        *defaults: str,
        fallback_xy: Optional[Tuple[int, int]] = None,
        roles: Sequence[str] = ("ButtonControl", "button"),
    ) -> Target:
        return Target(
            key=key,
            labels=self.labels(key, *defaults),
            roles=tuple(roles),
            fallback_xy=fallback_xy,
        )

    def _modifier(self, group: str, raw_value: Any) -> Tuple[Optional[str], Mapping[str, Any]]:
        value = normalize_text(str(raw_value or ""))
        if not value:
            return None, {}
        choices = self.modifiers.get(group, {}) or {}
        for canonical, details in choices.items():
            aliases = [canonical, *(details.get("aliases", ()) or ())]
            if value in {normalize_text(alias) for alias in aliases}:
                return str(canonical), details
        raise ProfileError(f"unsupported {group}: {raw_value}")

    def _all_menu_tokens(self) -> Tuple[str, ...]:
        tokens: List[str] = []
        for choices in self.modifiers.values():
            for details in (choices or {}).values():
                tokens.extend(details.get("menu_tokens", ()) or ())
        return tuple(dict.fromkeys(normalize_text(token) for token in tokens if token))

    def _base_name(self, name: str) -> str:
        value = normalize_text(name)
        for token in sorted(self._all_menu_tokens(), key=len, reverse=True):
            value = value.replace(token, "")
        return value

    @staticmethod
    def _extract_name(item: Mapping[str, Any]) -> str:
        # The team backend uses menuName as an internal code and displayName
        # as the kiosk-visible Korean label.
        for key in ("displayName", "name", "menu", "item", "menuName"):
            value = str(item.get(key, "") or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _extract_quantity(item: Mapping[str, Any]) -> int:
        raw = next(
            (item[key] for key in ("quantity", "count", "qty") if item.get(key) is not None),
            1,
        )
        if isinstance(raw, bool):
            raise ProfileError("quantity must be an integer")
        try:
            quantity = int(raw)
        except (TypeError, ValueError) as exc:
            raise ProfileError("quantity must be an integer") from exc
        if isinstance(raw, float) and not raw.is_integer():
            raise ProfileError("quantity must be an integer")
        return quantity

    @staticmethod
    def _contains_token(name: str, details: Mapping[str, Any]) -> bool:
        normalized = normalize_text(name)
        return any(
            normalize_text(token) in normalized
            for token in details.get("menu_tokens", ()) or ()
            if normalize_text(token)
        )

    def resolve_order_item(self, item: Mapping[str, Any]) -> ResolvedOrderItem:
        if not isinstance(item, Mapping):
            raise ProfileError("order item must be an object")
        requested = self._extract_name(item)
        if not requested:
            raise ProfileError("menu name is required")
        quantity = self._extract_quantity(item)
        temperature, temperature_info = self._modifier("temperature", item.get("temperature"))
        size, size_info = self._modifier("size", item.get("size"))

        exact = next(
            (menu for menu in self.menu_records if normalize_text(menu.name) == normalize_text(requested)),
            None,
        )
        if exact and temperature and not self._contains_token(exact.name, temperature_info):
            other_temperature_tokens = [
                details
                for canonical, details in (self.modifiers.get("temperature", {}) or {}).items()
                if canonical != temperature
            ]
            if any(self._contains_token(exact.name, details) for details in other_temperature_tokens):
                raise ProfileError(
                    f"menu name and temperature conflict: {requested} / {temperature}"
                )

        requested_normalized = normalize_text(requested)
        requested_base = self._base_name(requested)
        ranked: List[Tuple[float, MenuRecord]] = []
        for menu in self.menu_records:
            menu_normalized = normalize_text(menu.name)
            menu_base = self._base_name(menu.name)
            if requested_normalized == menu_normalized:
                score = 1.2
            elif requested_base and requested_base == menu_base:
                score = 1.0
            else:
                score = SequenceMatcher(None, requested_base, menu_base).ratio()

            if temperature:
                score += 0.25 if self._contains_token(menu.name, temperature_info) else -0.20
            if size:
                score += 0.12 if self._contains_token(menu.name, size_info) else 0.0
            ranked.append((score, menu))

        ranked.sort(key=lambda row: row[0], reverse=True)
        if not ranked or ranked[0][0] < 0.72:
            raise ProfileError(f"menu not found: {requested}")
        if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.08:
            raise ProfileError(
                f"menu is ambiguous: {requested} "
                f"({ranked[0][1].name} / {ranked[1][1].name})"
            )
        selected = ranked[0][1]

        option_targets: List[Target] = []
        for group, canonical, details in (
            ("temperature", temperature, temperature_info),
            ("size", size, size_info),
        ):
            if not canonical or self._contains_token(selected.name, details):
                continue
            option_labels = tuple(details.get("option_labels", ()) or ())
            if not option_labels:
                raise ProfileError(f"{group} option has no visible labels: {canonical}")
            option_targets.append(
                Target(
                    key=f"{group}:{canonical}",
                    labels=option_labels,
                    roles=("ButtonControl", "RadioButtonControl", "button", "radio"),
                )
            )

        return ResolvedOrderItem(requested, selected, quantity, tuple(option_targets))

    def transition_graph(self) -> TransitionGraph:
        state_markers = self.data.get("states", {}) or {}
        transitions = []
        for raw in self.data.get("transitions", ()) or ():
            target_data = raw.get("target", {}) or {}
            target = Target(
                key=str(target_data.get("key", raw.get("destination", "action"))),
                labels=tuple(target_data.get("labels", ()) or ()),
                roles=tuple(target_data.get("roles", ()) or ("ButtonControl", "button")),
            )
            transitions.append(
                Transition(
                    source=str(raw["source"]),
                    destination=str(raw["destination"]),
                    target=target,
                    expected_any=tuple(raw.get("expected_any", ()) or ()),
                )
            )
        return TransitionGraph(
            state_markers,
            transitions,
            tuple(self.data.get("state_priority", ()) or ()),
        )
