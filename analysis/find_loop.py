"""Choose the idle loop (brief 2d): a run of still frames that can repeat forever.

The loop plays frames start..end. Its last `crossfade` frames are replaced by a
crossfade into the frames just before `start`, and playback carries on at
`start`, so the seam is "show `end`, then `start`".
"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Loop:
    start: int
    end: int  # last frame before the jump back to `start`
    cost: float  # windowed cost of showing `end`, then `start`

    @property
    def length(self) -> int:
        """Frames per cycle (the crossfade replaces frames, it doesn't add any)."""
        return self.end - self.start + 1


def loop_candidates(windowed: np.ndarray, part: tuple[int, int], crossfade: int, min_frames: int) -> list[Loop]:
    """Every loop inside one still part (inclusive range) whose crossfade stays inside it."""
    if crossfade < 1:
        raise ValueError("crossfade must be at least one frame")
    first, last = part
    shortest = max(min_frames, crossfade + 1)
    return [
        Loop(start, end, float(windowed[end, start - 1]))
        for start in range(first + crossfade, last + 1)
        for end in range(start + shortest - 1, last + 1)
    ]


def choose_loop(
    windowed: np.ndarray,
    still_parts: list[tuple[int, int]],
    crossfade: int,
    min_frames: int,
    invisible_cost: float,
) -> Loop:
    """The longest loop whose seam is no worse than natural drift; failing that, the cheapest one.

    A longer loop repeats less obviously, but only if its seam stays invisible.
    """
    candidates = [loop for part in still_parts for loop in loop_candidates(windowed, part, crossfade, min_frames)]
    if not candidates:
        raise ValueError(
            f"no still part fits a {min_frames}-frame idle loop plus a {crossfade}-frame crossfade; "
            "the clip needs a longer still hold at its start or end"
        )
    invisible = [loop for loop in candidates if loop.cost <= invisible_cost]
    if invisible:
        return max(invisible, key=lambda loop: (loop.length, -loop.cost))
    return min(candidates, key=lambda loop: (loop.cost, -loop.length))
