"""Presence sensors and debouncing.

Every sensor exposes `raw(now) -> bool`; `Debouncer` turns that into the
debounced presence the state machine uses. The GPIO sensor arrives with the
wiring work (brief Phase 1).
"""

import bisect


class Debouncer:
    """Present once the raw signal has been high for `on_s`; absent once low for `off_s`."""

    def __init__(self, on_s: float, off_s: float) -> None:
        self._on_s = on_s
        self._off_s = off_s
        self._present = False
        self._raw: bool | None = None
        self._since = 0.0

    def update(self, raw: bool, now: float) -> bool:
        if raw != self._raw:
            self._raw = raw
            self._since = now
        held = now - self._since
        if raw and not self._present and held >= self._on_s:
            self._present = True
        elif not raw and self._present and held >= self._off_s:
            self._present = False
        return self._present


class ScriptedSensor:
    """Replays timed (seconds, present) events; for tests and previews."""

    def __init__(self, events: list[tuple[float, bool]]) -> None:
        self._events = sorted(events)
        self._times = [time for time, _ in self._events]

    def raw(self, now: float) -> bool:
        index = bisect.bisect_right(self._times, now) - 1
        return index >= 0 and self._events[index][1]


class KeyboardSensor:
    """PC testing: hold SPACE while someone is 'present', or press T to toggle presence."""

    HOLD_KEY = "space"
    TOGGLE_KEY = "t"

    def __init__(self) -> None:
        self._held = False
        self._toggled = False

    def handle_key(self, key: str, down: bool) -> None:
        if key == self.HOLD_KEY:
            self._held = down
        elif key == self.TOGGLE_KEY and down:
            self._toggled = not self._toggled

    def raw(self, now: float) -> bool:
        return self._held or self._toggled
