from __future__ import annotations
import json
import difflib
from typing import Dict, Tuple, Optional, List

class MenuIndex:
    """
    - Loads:
        * kiosk_ui_coords_easyocr.json
        * menu_cards.json
    - Provides:
        * category_centers: {name: (x,y)}
        * prev_xy / next_xy
        * name_to_entry: {menu_name: (category, page, (x,y))}
        * fuzzy match: find_menu_best(spoken)
    """
    def __init__(self, ui_coords_path: str, menu_cards_path: str):
        with open(ui_coords_path, "r", encoding="utf-8") as f:
            self.ui = json.load(f)
        with open(menu_cards_path, "r", encoding="utf-8") as f:
            self.cards = json.load(f)

        self.category_centers: Dict[str, Tuple[int, int]] = {}
        for c in self.ui.get("categories", []):
            self.category_centers[c["name"]] = (c["center"]["x"], c["center"]["y"])

        nb = self.ui.get("nav_buttons", {})
        self.prev_xy = (nb["prev"]["center"]["x"], nb["prev"]["center"]["y"])
        self.next_xy = (nb["next"]["center"]["x"], nb["next"]["center"]["y"])

        self.name_to_entry: Dict[str, Tuple[str, int, Tuple[int, int]]] = {}
        for it in self.cards:
            nm = it["name"]
            cat = it["category"]
            pg  = it["page"]
            xy = (it["center"]["x"], it["center"]["y"])
            self.name_to_entry[nm] = (cat, pg, xy)

        self.menu_names: List[str] = list(self.name_to_entry.keys())

    @staticmethod
    def _normalize(s: str) -> str:
        return "".join(s.strip().split()).casefold()

    def find_menu_best(self, spoken: str, cutoff: float = 0.72) -> Optional[Tuple[str, str, int, Tuple[int, int]]]:
        # direct hit
        it = self.name_to_entry.get(spoken)
        if it:
            cat, pg, xy = it
            return spoken, cat, pg, xy

        # fuzzy
        cand = difflib.get_close_matches(spoken, self.menu_names, n=1, cutoff=cutoff)
        if cand:
            name = cand[0]
            cat, pg, xy = self.name_to_entry[name]
            return name, cat, pg, xy

        # normalized ratio
        norm = self._normalize(spoken)
        best = None
        best_score = 0.0
        for name in self.menu_names:
            score = difflib.SequenceMatcher(None, norm, self._normalize(name)).ratio()
            if score > best_score:
                best_score = score
                best = name
        if best and best_score >= cutoff:
            cat, pg, xy = self.name_to_entry[best]
            return best, cat, pg, xy
        return None
