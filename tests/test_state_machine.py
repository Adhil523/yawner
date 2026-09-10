from collections.abc import Callable

import pytest

from player.state_machine import MAIN, Behaviour, FrameRef, Graph, Jump, Phase, YawnStateMachine

FPS = 24.0
LOOP_FADE = "bridge_loop"
ENTRY_FADE = "bridge_entry"
EXIT_FADE = "bridge_exit"


def _loop_in_still_end() -> Graph:
    """Still start 0-9, yawn 10-29, still end 30-39. Loop 32-39; its last 4 frames are the crossfade."""
    return Graph(
        main_frames=40,
        loop_start=32,
        loop_jump=Jump(at=35, resume=32, bridge=LOOP_FADE, length=4),
        yawn_start=10,
        yawn_end=29,
        entries=(Jump(at=35, resume=7, bridge=ENTRY_FADE, length=4),),
        exits=(Jump(at=31, resume=32),),
    )


def _loop_in_still_start() -> Graph:
    """Loop 4-10 (last 3 frames crossfade), yawn 14-29, then a crossfaded exit back onto the loop."""
    return Graph(
        main_frames=40,
        loop_start=4,
        loop_jump=Jump(at=7, resume=4, bridge=LOOP_FADE, length=3),
        yawn_start=14,
        yawn_end=29,
        entries=(Jump(at=7, resume=8),),
        exits=(Jump(at=31, resume=5, bridge=EXIT_FADE, length=3),),
    )


def _play(
    machine: YawnStateMachine, ticks: int, present: Callable[[float], bool] = lambda now: False
) -> list[tuple[FrameRef, Phase]]:
    shown = []
    for tick in range(ticks):
        now = tick / FPS
        shown.append((machine.current, machine.phase))
        machine.advance(present(now), now)
    return shown


def _main(*frames: int) -> list[FrameRef]:
    return [(MAIN, frame) for frame in frames]


def _fade(name: str, length: int) -> list[FrameRef]:
    return [(name, index) for index in range(length)]


def _entries_taken(shown: list[tuple[FrameRef, Phase]], fade: str = ENTRY_FADE) -> list[int]:
    return [tick for tick, (frame, _) in enumerate(shown) if frame == (fade, 0)]


def test_idle_loops_through_its_crossfade_forever() -> None:
    frames = [frame for frame, _ in _play(YawnStateMachine(_loop_in_still_end(), Behaviour()), 16)]
    cycle = _main(32, 33, 34, 35) + _fade(LOOP_FADE, 4)
    assert frames == cycle + cycle


def test_arrival_plays_entry_yawn_and_exit_back_to_idle() -> None:
    shown = _play(YawnStateMachine(_loop_in_still_end(), Behaviour()), 39, present=lambda now: True)
    expected = (
        _main(32, 33, 34, 35) + _fade(ENTRY_FADE, 4) + _main(7, 8, 9)
        + _main(*range(10, 30)) + _main(30, 31) + _main(32, 33, 34, 35) + _fade(LOOP_FADE, 2)
    )
    assert [frame for frame, _ in shown] == expected
    phases = dict(zip(map(tuple, (frame for frame, _ in shown)), (phase for _, phase in shown)))
    assert phases[(ENTRY_FADE, 0)] is Phase.ENTERING
    assert phases[(MAIN, 7)] is Phase.ENTERING
    assert phases[(MAIN, 10)] is Phase.YAWNING
    assert phases[(MAIN, 30)] is Phase.EXITING


def test_yawn_finishes_even_if_the_person_leaves() -> None:
    shown = _play(YawnStateMachine(_loop_in_still_end(), Behaviour()), 45, present=lambda now: now < 0.05)
    frames = [frame for frame, _ in shown]
    assert all((MAIN, frame) in frames for frame in range(10, 30))


def test_no_new_yawn_during_cooldown() -> None:
    machine = YawnStateMachine(_loop_in_still_end(), Behaviour(cooldown_s=5.0))
    shown = _play(machine, round(12 * FPS), present=lambda now: now < 0.5 or 2.0 <= now < 3.0)
    assert len(_entries_taken(shown)) == 1


def test_arrival_after_cooldown_yawns_again() -> None:
    machine = YawnStateMachine(_loop_in_still_end(), Behaviour(cooldown_s=5.0))
    shown = _play(machine, round(12 * FPS), present=lambda now: now < 0.5 or 6.0 <= now < 7.0)
    assert len(_entries_taken(shown)) == 2


def test_repeat_while_present_rearms_after_interval() -> None:
    machine = YawnStateMachine(_loop_in_still_end(), Behaviour(repeat_while_present=True, repeat_interval_s=3.0))
    starts = [tick / FPS for tick in _entries_taken(_play(machine, round(10 * FPS), present=lambda now: True))]
    assert len(starts) >= 3
    assert all(later - earlier >= 3.0 for earlier, later in zip(starts, starts[1:]))


def test_loop_in_still_start_enters_without_a_cut_and_exits_through_a_crossfade() -> None:
    shown = _play(YawnStateMachine(_loop_in_still_start(), Behaviour()), 36, present=lambda now: True)
    expected = (
        _main(4, 5, 6, 7) + _main(*range(8, 14)) + _main(*range(14, 30)) + _main(30, 31)
        + _fade(EXIT_FADE, 3) + _main(5, 6, 7) + _fade(LOOP_FADE, 2)
    )
    assert [frame for frame, _ in shown] == expected
    assert shown[-3][1] is Phase.IDLE  # back on the loop at frame 7


@pytest.mark.parametrize(
    "change",
    [
        {"entries": (Jump(at=20, resume=7, bridge=ENTRY_FADE, length=4),)},  # not on the loop
        {"entries": (Jump(at=35, resume=12, bridge=ENTRY_FADE, length=4),)},  # lands mid-yawn
        {"exits": (Jump(at=25, resume=32, bridge=EXIT_FADE, length=4),)},  # cuts the yawn short
        {"exits": (Jump(at=31, resume=33),)},  # "plain step" that skips a frame
    ],
)
def test_graph_rejects_impossible_portals(change: dict[str, tuple[Jump, ...]]) -> None:
    base = _loop_in_still_end()
    fields = {name: getattr(base, name) for name in base.__dataclass_fields__} | change
    with pytest.raises(ValueError, match="invalid frame graph"):
        Graph(**fields)


def test_graph_from_manifest() -> None:
    manifest = {
        "sequences": {MAIN: {"frames": 40}, LOOP_FADE: {"frames": 4}, ENTRY_FADE: {"frames": 4}},
        "idle_loop": {"start": 32, "end": 39, "jump": {"at": 35, "bridge": LOOP_FADE, "resume": 32}},
        "yawn": {"start": 10, "end": 29},
        "entries": [{"at": 35, "bridge": ENTRY_FADE, "resume": 7}],
        "exits": [{"at": 31, "bridge": None, "resume": 32}],
    }
    assert Graph.from_manifest(manifest) == _loop_in_still_end()
