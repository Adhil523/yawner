"""Entry and exit portals (brief 2e / 2f) between the idle loop and the yawn.

A portal means "after showing main frame `at`, continue at `resume`". A bridged
portal crossfades the `crossfade` frames after `at` into the ones before
`resume`; a natural portal just carries on (resume = at + 1) and costs nothing.

If the loop sits in the still end, the yawn finishes by playing straight into it
(natural exit) and entering needs a bridged jump into the still start. If the
loop sits in the still start, it's the other way round.
"""

from dataclasses import dataclass

import numpy as np

from analysis.find_loop import Loop


@dataclass(frozen=True)
class Portal:
    at: int
    resume: int
    cost: float
    bridged: bool
    lead_in: int = 0  # entries: main frames between `resume` and the yawn's first frame


@dataclass(frozen=True)
class PortalPlan:
    entries: list[Portal]
    exits: list[Portal]
    worst_entry_latency: int  # frames from a worst-timed arrival to the yawn's first frame


def decision_frame(loop: Loop, crossfade: int) -> int:
    """Last loop frame shown before the loop's own crossfade starts."""
    return loop.end - crossfade


def portal_transition(portal: Portal, crossfade: int) -> int:
    """Frames from taking an entry to the yawn's first frame."""
    return (crossfade if portal.bridged else 0) + portal.lead_in


def _latencies(entries: list[Portal], loop: Loop, crossfade: int) -> list[tuple[Portal, Portal, int]]:
    """(portal, previous portal on the loop, worst wait if you arrive just after `previous`)."""
    ordered = sorted(entries, key=lambda portal: portal.at)
    result = []
    for index, portal in enumerate(ordered):
        previous = ordered[index - 1]
        gap = (portal.at - previous.at) % loop.length or loop.length
        result.append((portal, previous, gap + portal_transition(portal, crossfade)))
    return result


def worst_entry_latency(entries: list[Portal], loop: Loop, crossfade: int) -> int:
    return max(latency for _, _, latency in _latencies(entries, loop, crossfade))


def _spread(candidates: list[Portal], loop: Loop, crossfade: int, max_latency: int) -> list[Portal]:
    """Fewest, cheapest entries keeping the worst wait within max_latency (brief 2e's suppression).

    Start with the cheapest candidate, then keep adding the cheapest one inside
    whichever wait is currently too long.
    """
    chosen = [min(candidates, key=lambda portal: portal.cost)]
    while True:
        portal, previous, latency = max(_latencies(chosen, loop, crossfade), key=lambda item: item[2])
        if latency <= max_latency:
            break
        span = (portal.at - previous.at) % loop.length or loop.length
        inside = [c for c in candidates if c not in chosen and 0 < (c.at - previous.at) % loop.length < span]
        if not inside:
            break  # can't do better; export flags the latency
        chosen.append(min(inside, key=lambda portal: portal.cost))
    return sorted(chosen, key=lambda portal: portal.at)


def _bridged_entries(
    windowed: np.ndarray, loop: Loop, still_start: tuple[int, int], yawn_start: int, crossfade: int, max_latency: int
) -> list[Portal]:
    # Blend into the real onset frames so the yawn begins during the bridge rather than after a neutral lead-in.
    targets = np.array([yawn_start])
    if len(targets) == 0:
        raise ValueError("still start is too short for an entry crossfade")
    leads = yawn_start - targets
    feasible = np.flatnonzero(crossfade + leads < max_latency)
    pool = feasible if len(feasible) else np.arange(len(targets))

    candidates = []
    for at in range(loop.start, decision_frame(loop, crossfade) + 1):
        costs = windowed[at + crossfade, targets[pool] - 1]
        best = pool[np.lexsort((-targets[pool], costs))[0]]  # cheapest, then the latest landing
        candidates.append(Portal(at, int(targets[best]), float(windowed[at + crossfade, targets[best] - 1]), True, int(leads[best])))
    return _spread(candidates, loop, crossfade, max_latency)


def _bridged_exit(
    windowed: np.ndarray, loop: Loop, still_end: tuple[int, int], yawn_end: int, crossfade: int
) -> Portal:
    exits = [
        Portal(at, resume, float(windowed[at + crossfade, resume - 1]), True)
        for at in range(yawn_end, still_end[1] - crossfade + 1)
        for resume in range(loop.start, decision_frame(loop, crossfade) + 1)
    ]
    if not exits:
        raise ValueError("still end is too short for an exit crossfade")
    return min(exits, key=lambda portal: (portal.cost, portal.at))


def plan_portals(
    windowed: np.ndarray,
    loop: Loop,
    still_start: tuple[int, int],
    yawn: tuple[int, int],
    still_end: tuple[int, int],
    crossfade: int,
    max_latency: int,
) -> PortalPlan:
    yawn_start, yawn_end = yawn
    if loop.start > yawn_end:
        entries = _bridged_entries(windowed, loop, still_start, yawn_start, crossfade, max_latency)
        exits = [Portal(at=loop.start - 1, resume=loop.start, cost=0.0, bridged=False)]
    elif loop.end < yawn_start:
        at = decision_frame(loop, crossfade)
        entries = [Portal(at=at, resume=at + 1, cost=0.0, bridged=False, lead_in=yawn_start - at - 1)]
        exits = [_bridged_exit(windowed, loop, still_end, yawn_end, crossfade)]
    else:
        raise ValueError("idle loop overlaps the yawn")
    return PortalPlan(entries, exits, worst_entry_latency(entries, loop, crossfade))
