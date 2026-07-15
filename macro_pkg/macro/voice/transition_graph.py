from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .grounding import Target, contains_any_text
from .perception import ScreenObservation


@dataclass(frozen=True)
class Transition:
    source: str
    destination: str
    target: Target
    expected_any: Tuple[str, ...]


class TransitionGraph:
    """Small semantic UI-transition graph; coordinates never define state."""

    def __init__(
        self,
        state_markers: Mapping[str, Sequence[str]],
        transitions: Iterable[Transition],
        state_priority: Sequence[str] = (),
    ):
        self.state_markers = {
            name: tuple(markers) for name, markers in state_markers.items()
        }
        self.transitions = tuple(transitions)
        self.state_priority = {
            state: len(state_priority) - index
            for index, state in enumerate(state_priority)
        }

    def detect_state(self, observation: ScreenObservation) -> Optional[str]:
        scores = []
        for state, markers in self.state_markers.items():
            score = sum(contains_any_text(observation, (marker,)) for marker in markers)
            if score:
                scores.append(
                    (
                        self.state_priority.get(state, 0),
                        score / max(1, len(markers)),
                        score,
                        state,
                    )
                )
        scores.sort(reverse=True)
        return scores[0][3] if scores else None

    def path(self, source: str, destination: str) -> List[Transition]:
        if source == destination:
            return []
        queue = deque([(source, [])])
        visited = {source}
        while queue:
            state, path = queue.popleft()
            for transition in self.transitions:
                if transition.source != state or transition.destination in visited:
                    continue
                next_path = [*path, transition]
                if transition.destination == destination:
                    return next_path
                visited.add(transition.destination)
                queue.append((transition.destination, next_path))
        raise ValueError(f"no transition path: {source} -> {destination}")
