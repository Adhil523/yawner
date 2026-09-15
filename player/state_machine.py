"""Pure playback logic: which frame to show next.

No I/O and no clock of its own. The caller passes debounced presence and the
current time (seconds) once per frame. Cuts only ever happen at the portals in
the manifest; everywhere else playback steps to the next frame of the clip.

Phases:
    IDLE      the idle loop, jumping back at its own crossfade.
    ENTERING  armed and at an entry portal: its crossfade, then the frames
              leading up to the yawn.
    YAWNING   the yawn, never interrupted.
    EXITING   the frames after the yawn until an exit lands back on the loop.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

MAIN = "main"
FrameRef = tuple[str, int]  # (sequence name, frame index)


class Phase(Enum):
    IDLE = "idle"
    ENTERING = "entering"
    YAWNING = "yawning"
    EXITING = "exiting"


@dataclass(frozen=True)
class Jump:
    at: int  # last main frame shown before the change
    resume: int  # main frame shown after it
    bridge: str | None = None  # crossfade played in between; None = carry straight on
    length: int = 0  # crossfade frame count


@dataclass(frozen=True)
class Behaviour:
    yawn_on_arrival: bool = True
    repeat_while_present: bool = False
    repeat_interval_s: float = 20.0
    cooldown_s: float = 5.0  # after someone leaves, how long before a new arrival counts


@dataclass(frozen=True)
class Graph:
    main_frames: int
    loop_start: int
    loop_jump: Jump
    yawn_start: int
    yawn_end: int
    entries: tuple[Jump, ...]
    exits: tuple[Jump, ...]

    def __post_init__(self) -> None:
        problems = []
        for jump in (self.loop_jump, *self.entries, *self.exits):
            if not (0 <= jump.at < self.main_frames and 0 <= jump.resume < self.main_frames):
                problems.append(f"jump {jump.at}->{jump.resume} is outside the {self.main_frames}-frame clip")
            if jump.bridge is None and jump.resume != jump.at + 1:
                problems.append(f"jump {jump.at}->{jump.resume} has no crossfade but isn't a plain step")
            if jump.bridge is not None and jump.length < 1:
                problems.append(f"crossfade {jump.bridge} is empty")
        loop_last = self.loop_jump.at  # last loop frame shown before its crossfade
        if not self.loop_start <= loop_last or self.loop_jump.resume != self.loop_start:
            problems.append("the loop jump must come after the loop start and return to it")
        if not 0 <= self.yawn_start <= self.yawn_end < self.main_frames:
            problems.append(f"yawn {self.yawn_start}-{self.yawn_end} is invalid")
        if not (loop_last < self.yawn_start or self.loop_start > self.yawn_end):
            problems.append("the idle loop overlaps the yawn")
        if not self.entries or not self.exits:
            problems.append("needs at least one entry and one exit")
        for entry in self.entries:
            if not self.loop_start <= entry.at <= loop_last:
                problems.append(f"entry at {entry.at} is not on the idle loop ({self.loop_start}-{loop_last})")
            if entry.resume > self.yawn_start:
                problems.append(f"entry lands on {entry.resume}, after the yawn starts ({self.yawn_start})")
        for exit_ in self.exits:
            if exit_.at < self.yawn_end:
                problems.append(f"exit at {exit_.at} would cut the yawn short (it ends at {self.yawn_end})")
            if not self.loop_start <= exit_.resume <= loop_last:
                problems.append(f"exit lands on {exit_.resume}, off the idle loop")
        if problems:
            raise ValueError("invalid frame graph: " + "; ".join(problems))

    @classmethod
    def from_manifest(cls, manifest: dict[str, Any]) -> "Graph":
        sequences = manifest["sequences"]

        def jump(data: dict[str, Any]) -> Jump:
            bridge = data.get("bridge")
            if bridge is not None and bridge not in sequences:
                raise ValueError(f"manifest refers to unknown sequence {bridge!r}")
            length = int(sequences[bridge]["frames"]) if bridge else 0
            return Jump(int(data["at"]), int(data["resume"]), bridge, length)

        loop = manifest["idle_loop"]
        return cls(
            main_frames=int(sequences[MAIN]["frames"]),
            loop_start=int(loop["start"]),
            loop_jump=jump(loop["jump"]),
            yawn_start=int(manifest["yawn"]["start"]),
            yawn_end=int(manifest["yawn"]["end"]),
            entries=tuple(jump(entry) for entry in manifest["entries"]),
            exits=tuple(jump(exit_) for exit_ in manifest["exits"]),
        )


class YawnStateMachine:
    def __init__(self, graph: Graph, behaviour: Behaviour) -> None:
        self._graph = graph
        self._behaviour = behaviour
        self._entries = {jump.at: jump for jump in graph.entries}
        self._exits = {jump.at: jump for jump in graph.exits}
        self._main = graph.loop_start
        self._bridge: Jump | None = None
        self._bridge_index = 0
        self._present = False
        self._left_at: float | None = None
        self._last_trigger: float | None = None
        self.phase = Phase.IDLE
        self.armed = False
        self.last_jump: Jump | None = None  # jump started by the latest advance(), for logging

    @property
    def current(self) -> FrameRef:
        if self._bridge is not None and self._bridge.bridge is not None:
            return (self._bridge.bridge, self._bridge_index)
        return (MAIN, self._main)

    def advance(self, present: bool, now: float) -> FrameRef:
        """Move to the next frame, given debounced presence at time `now` (seconds)."""
        self.last_jump = None
        self._update_arming(present, now)
        if self._bridge is not None:
            self._step_bridge()
        else:
            self._step_main(now)
        return self.current

    def _update_arming(self, present: bool, now: float) -> None:
        behaviour = self._behaviour
        if present and not self._present:
            cooled_down = self._left_at is None or now - self._left_at >= behaviour.cooldown_s
            # Only arrivals while idle count; someone arriving mid-yawn doesn't queue another one.
            if cooled_down and behaviour.yawn_on_arrival and self.phase is Phase.IDLE:
                self.armed = True
            self._last_trigger = now
        elif not present and self._present:
            self._left_at = now
        self._present = present

        if (
            present
            and behaviour.repeat_while_present
            and not self.armed
            and self.phase is Phase.IDLE
            and self._last_trigger is not None
            and now - self._last_trigger >= behaviour.repeat_interval_s
        ):
            self.armed = True

    def _step_main(self, now: float) -> None:
        frame = self._main
        if self.phase is Phase.IDLE:
            entry = self._entries.get(frame)
            if self.armed and entry is not None:
                self.armed = False
                self._last_trigger = now
                self.phase = Phase.ENTERING
                self._take(entry)
            elif frame == self._graph.loop_jump.at:
                self._take(self._graph.loop_jump)
            else:
                self._land(frame + 1)
            return

        if self.phase is not Phase.ENTERING and frame >= self._graph.yawn_end:
            self.phase = Phase.EXITING
            exit_jump = self._exits.get(frame)
            if exit_jump is not None:
                self._take(exit_jump)
                return
        self._land(frame + 1)

    def _step_bridge(self) -> None:
        if self._bridge is None:
            return
        self._bridge_index += 1
        if self._bridge_index >= self._bridge.length:
            resume = self._bridge.resume
            self._bridge = None
            self._land(resume)

    def _take(self, jump: Jump) -> None:
        self.last_jump = jump
        if jump.bridge is None:
            self._land(jump.resume)
            return
        self._bridge = jump
        self._bridge_index = 0

    def _land(self, frame: int) -> None:
        self._main = frame
        graph = self._graph
        if self.phase is Phase.ENTERING and frame >= graph.yawn_start:
            self.phase = Phase.YAWNING
        elif self.phase is Phase.EXITING and graph.loop_start <= frame <= graph.loop_jump.at:
            self.phase = Phase.IDLE
