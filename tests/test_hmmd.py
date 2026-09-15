import struct
import threading
import time
from collections.abc import Callable

import pytest

from player.hmmd import (
    ENABLE_REPORT_MODE,
    REPORT_HEADER,
    REPORT_TAIL,
    DistanceZone,
    HmmdParser,
    HmmdSensor,
    RadarSample,
)

GATES = 16
WAIT_S = 2.0


def _frame(present: bool, distance_cm: int) -> bytes:
    """Same layout as the prototype's make_test_frame."""
    payload = bytes([int(present)]) + struct.pack("<H", distance_cm) + struct.pack(f"<{GATES}H", *range(GATES))
    return REPORT_HEADER + struct.pack("<H", len(payload)) + payload + REPORT_TAIL


def _sample(present: bool, distance_cm: int) -> RadarSample:
    return RadarSample(present, distance_cm, ())


def _wait_for(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + WAIT_S
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


class FakePort:
    """Stands in for pyserial: frames queued with `send` come back from `read`."""

    def __init__(self) -> None:
        self.written = bytearray()
        self.closed = False
        self._pending = bytearray()
        self._lock = threading.Lock()

    @property
    def in_waiting(self) -> int:
        with self._lock:
            return len(self._pending)

    def send(self, data: bytes) -> None:
        with self._lock:
            self._pending.extend(data)

    def read(self, size: int) -> bytes:
        with self._lock:
            chunk = bytes(self._pending[:size])
            del self._pending[:size]
        if not chunk:
            time.sleep(0.01)
        return chunk

    def write(self, data: bytes) -> int:
        self.written.extend(data)
        return len(data)

    def flush(self) -> None:
        pass

    def reset_input_buffer(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def test_parser_handles_noise_and_split_frames() -> None:
    parser = HmmdParser()
    frame = _frame(True, 137)
    samples = parser.feed(b"noise" + frame[:9]) + parser.feed(frame[9:])
    assert samples == [RadarSample(True, 137, tuple(range(GATES)))]


def test_parser_reads_back_to_back_frames() -> None:
    samples = HmmdParser().feed(_frame(True, 80) + _frame(False, 0))
    assert [(s.present, s.distance_cm) for s in samples] == [(True, 80), (False, 0)]


def test_parser_skips_a_corrupt_frame_and_recovers() -> None:
    corrupt = _frame(True, 99)[:-1] + b"\x00"
    samples = HmmdParser().feed(corrupt + _frame(True, 120))
    assert [s.distance_cm for s in samples] == [120]


def test_zone_needs_presence_inside_min_max() -> None:
    zone = DistanceZone(50, 200, 260)
    assert zone.update(_sample(True, 30)) is False  # too close
    assert zone.update(_sample(True, 230)) is False  # too far
    assert zone.update(_sample(False, 150)) is False  # distance without presence
    assert zone.update(_sample(True, 150)) is True


def test_zone_holds_until_gone_or_past_rearm_distance() -> None:
    zone = DistanceZone(50, 200, 260)
    zone.update(_sample(True, 150))
    assert zone.update(_sample(True, 240)) is True  # between max and rearm: still counts
    assert zone.update(_sample(True, 260)) is False
    zone.update(_sample(True, 150))
    assert zone.update(_sample(False, 0)) is False


def test_zone_rejects_bad_limits() -> None:
    with pytest.raises(ValueError, match="rearm_cm"):
        DistanceZone(50, 200, 150)


def test_sensor_enables_report_mode_and_follows_frames() -> None:
    port = FakePort()
    sensor = HmmdSensor(lambda: port, DistanceZone(50, 200, 260))
    try:
        _wait_for(lambda: bytes(port.written) == ENABLE_REPORT_MODE)
        port.send(_frame(True, 120))
        _wait_for(lambda: sensor.raw(0.0))
        port.send(_frame(False, 0))
        _wait_for(lambda: not sensor.raw(0.0))
    finally:
        sensor.close()
    assert port.closed


def test_sensor_reports_nobody_when_data_stops() -> None:
    port = FakePort()
    sensor = HmmdSensor(lambda: port, DistanceZone(50, 200, 260), stale_s=0.2)
    try:
        port.send(_frame(True, 120))
        _wait_for(lambda: sensor.raw(0.0))
        time.sleep(0.3)
        assert sensor.raw(0.0) is False
    finally:
        sensor.close()


def test_sensor_retries_when_the_port_fails_to_open() -> None:
    attempts = []

    def failing_open() -> FakePort:
        attempts.append(1)
        raise OSError("no such device")

    sensor = HmmdSensor(failing_open, DistanceZone(50, 200, 260), stale_s=0.1)
    try:
        _wait_for(lambda: len(attempts) >= 1)
        time.sleep(0.2)
        assert sensor.raw(0.0) is False
    finally:
        sensor.close()
