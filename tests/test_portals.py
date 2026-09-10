"""Loop and portal search on synthetic frames with a known answer."""

import numpy as np
import pytest

from analysis.bridges import bridge_sources, crossfade
from analysis.features import pairwise_distance, windowed_distance
from analysis.find_loop import choose_loop
from analysis.find_portals import Portal, decision_frame, plan_portals

FADE = 4
PERIOD = 12  # the still parts "breathe" with this period, so loops of 12k frames are seamless


def _clip(head: int, yawn: int, tail: int) -> tuple[np.ndarray, tuple[int, int], tuple[int, int], tuple[int, int]]:
    """Flat 2x2 frames: gentle periodic motion when still, a big swing during the yawn,
    and a small brightness offset in the still end so end -> start jumps cost something."""
    values = []
    for i in range(head + yawn + tail):
        if head <= i < head + yawn:
            values.append(10 + 40 * np.sin(np.pi * (i - head) / yawn))
        else:
            values.append(10 + 0.5 * np.sin(2 * np.pi * i / PERIOD) + (0.8 if i >= head + yawn else 0.0))
    frames = np.stack([np.full((2, 2), value, dtype=np.float32) for value in values])
    parts = (0, head - 1), (head, head + yawn - 1), (head + yawn, head + yawn + tail - 1)
    return windowed_distance(pairwise_distance(frames, frames)), *parts


def test_picks_the_longest_seamless_loop() -> None:
    windowed, head, _, tail = _clip(head=30, yawn=60, tail=40)
    loop = choose_loop(windowed, [head, tail], FADE, min_frames=8, invisible_cost=0.05)
    assert tail[0] <= loop.start and loop.end <= tail[1]
    assert loop.length == 3 * PERIOD
    assert loop.cost == pytest.approx(0.0, abs=1e-4)


def test_loop_in_still_end_exits_naturally_and_enters_through_crossfades() -> None:
    windowed, head, yawn, tail = _clip(head=30, yawn=60, tail=40)
    loop = choose_loop(windowed, [head, tail], FADE, min_frames=8, invisible_cost=0.05)
    plan = plan_portals(windowed, loop, head, yawn, tail, FADE, max_latency=60)

    assert plan.exits == [Portal(at=loop.start - 1, resume=loop.start, cost=0.0, bridged=False)]
    for entry in plan.entries:
        assert entry.bridged
        assert loop.start <= entry.at <= decision_frame(loop, FADE)
        assert FADE <= entry.resume <= yawn[0]
    assert plan.worst_entry_latency <= 60


def test_adds_entries_until_the_wait_fits() -> None:
    windowed, head, yawn, tail = _clip(head=30, yawn=60, tail=40)
    loop = choose_loop(windowed, [head, tail], FADE, min_frames=8, invisible_cost=0.05)
    plan = plan_portals(windowed, loop, head, yawn, tail, FADE, max_latency=30)
    assert len(plan.entries) > 1
    assert plan.worst_entry_latency <= 30


def test_loop_in_still_start_enters_naturally_and_exits_through_a_crossfade() -> None:
    windowed, head, yawn, tail = _clip(head=40, yawn=60, tail=30)
    loop = choose_loop(windowed, [head, tail], FADE, min_frames=8, invisible_cost=0.05)
    assert loop.end < yawn[0]

    plan = plan_portals(windowed, loop, head, yawn, tail, FADE, max_latency=100)
    at = decision_frame(loop, FADE)
    assert plan.entries == [Portal(at=at, resume=at + 1, cost=0.0, bridged=False, lead_in=yawn[0] - at - 1)]
    (exit_,) = plan.exits
    assert exit_.bridged and exit_.at >= yawn[1]
    assert loop.start <= exit_.resume <= at


def test_rejects_clips_without_room_for_a_loop() -> None:
    windowed, head, _, tail = _clip(head=6, yawn=60, tail=6)
    with pytest.raises(ValueError, match="longer still hold"):
        choose_loop(windowed, [head, tail], FADE, min_frames=8, invisible_cost=0.05)


def test_crossfade_moves_evenly_between_the_two_runs() -> None:
    outgoing = np.zeros((2, 1, 1, 3), dtype=np.uint8)
    incoming = np.full((2, 1, 1, 3), 90, dtype=np.uint8)
    assert crossfade(outgoing, incoming)[:, 0, 0, 0].tolist() == [30, 60]


def test_bridge_blends_the_frames_after_at_with_the_ones_before_resume() -> None:
    assert bridge_sources(at=10, resume=50, length=3) == ([11, 12, 13], [47, 48, 49])
