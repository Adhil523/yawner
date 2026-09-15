"""Waveshare HMMD 24 GHz mmWave sensor over UART (the hardware this kiosk runs on).

The frame format, report-mode command and Pi 5 serial device come from the
working prototype (yawn-signage/signage_controller.py). The sensor streams
report frames of presence, distance and 16 gate energies; `HmmdSensor` turns
them into the plain `raw(now) -> bool` the Debouncer expects, using a distance
zone so people walking past further away don't count.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

log = logging.getLogger("hmmd")

REPORT_HEADER = b"\xF4\xF3\xF2\xF1"
REPORT_TAIL = b"\xF8\xF7\xF6\xF5"
LENGTH_BYTES = 2
MIN_PAYLOAD = 3  # presence byte + 2-byte distance
MAX_PAYLOAD = 1024
# Command 0x0012, parameter 0, value 4: enable report mode.
ENABLE_REPORT_MODE = bytes.fromhex("FD FC FB FA 08 00 12 00 00 00 04 00 00 00 04 03 02 01")

DEFAULT_BAUD = 115200
AUTO_DEVICE = "auto"
PI5_UART = "/dev/ttyAMA0"  # UART0 on GPIO14/15 once dtoverlay=uart0-pi5 is set
OTHER_PI_UART = "/dev/serial0"
DEVICE_TREE_MODEL = Path("/proc/device-tree/model")
READ_TIMEOUT_S = 0.25
REPORT_MODE_SETTLE_S = 0.15
STALE_S = 2.0  # no frames for this long -> treat as nobody there
RETRY_S = 2.0  # wait before reopening a failed serial port


@dataclass(frozen=True)
class RadarSample:
    present: bool
    distance_cm: int
    gate_energy: tuple[int, ...]


class HmmdParser:
    """Incrementally parse report-mode frames; tolerates noise and frames split across reads."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[RadarSample]:
        self._buffer.extend(data)
        samples: list[RadarSample] = []
        while True:
            start = self._buffer.find(REPORT_HEADER)
            if start < 0:
                # Keep enough bytes to catch a header split across reads.
                del self._buffer[: -(len(REPORT_HEADER) - 1)]
                return samples
            del self._buffer[:start]
            header_end = len(REPORT_HEADER) + LENGTH_BYTES
            if len(self._buffer) < header_end:
                return samples

            payload_length = int.from_bytes(self._buffer[len(REPORT_HEADER):header_end], "little")
            if not MIN_PAYLOAD <= payload_length <= MAX_PAYLOAD:
                del self._buffer[0]
                continue
            frame_length = header_end + payload_length + len(REPORT_TAIL)
            if len(self._buffer) < frame_length:
                return samples
            frame = bytes(self._buffer[:frame_length])
            if frame[-len(REPORT_TAIL):] != REPORT_TAIL:
                del self._buffer[0]
                continue
            del self._buffer[:frame_length]

            payload = frame[header_end:-len(REPORT_TAIL)]
            energies = tuple(int.from_bytes(payload[i:i + 2], "little") for i in range(3, len(payload) - 1, 2))
            samples.append(RadarSample(payload[0] != 0, int.from_bytes(payload[1:3], "little"), energies))


@dataclass
class DistanceZone:
    """In once present within min_cm..max_cm; out once gone or at/after rearm_cm (hysteresis)."""

    min_cm: int
    max_cm: int
    rearm_cm: int
    inside: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.min_cm <= self.max_cm <= self.rearm_cm:
            raise ValueError(f"distance zone needs 0 <= min_cm <= max_cm <= rearm_cm, got "
                             f"{self.min_cm}, {self.max_cm}, {self.rearm_cm}")

    def update(self, sample: RadarSample) -> bool:
        if not self.inside:
            self.inside = sample.present and self.min_cm <= sample.distance_cm <= self.max_cm
        elif not sample.present or sample.distance_cm >= self.rearm_cm:
            self.inside = False
        return self.inside


class SerialPort(Protocol):
    in_waiting: int

    def read(self, size: int) -> bytes: ...

    def write(self, data: bytes) -> int | None: ...

    def flush(self) -> None: ...

    def reset_input_buffer(self) -> None: ...

    def close(self) -> None: ...


def default_serial_device() -> str:
    """The 40-pin-header UART: ttyAMA0 on a Pi 5 (serial0 is its separate debug UART), serial0 otherwise."""
    try:
        model = DEVICE_TREE_MODEL.read_text(errors="ignore")
    except OSError:
        model = ""
    return PI5_UART if "Raspberry Pi 5" in model else OTHER_PI_UART


def pyserial_opener(device: str, baud: int) -> Callable[[], SerialPort]:
    try:
        import serial
    except ImportError as error:
        raise RuntimeError("pyserial is not installed; on the Pi: sudo apt install python3-serial") from error
    resolved = default_serial_device() if device == AUTO_DEVICE else device
    return lambda: serial.Serial(resolved, baudrate=baud, timeout=READ_TIMEOUT_S)


class HmmdSensor:
    """Reads frames on a background thread; `raw` is whether someone is in the distance zone right now."""

    def __init__(self, open_port: Callable[[], SerialPort], zone: DistanceZone, stale_s: float = STALE_S) -> None:
        self._open_port = open_port
        self._zone = zone
        self._stale_s = stale_s
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._latest: RadarSample | None = None
        self._inside = False
        self._last_frame = time.monotonic()  # grace period at startup counts from here
        self._stale_logged = False
        self._thread = threading.Thread(target=self._run, name="hmmd-reader", daemon=True)
        self._thread.start()

    @property
    def stale_s(self) -> float:
        return self._stale_s

    def raw(self, now: float) -> bool:
        _, inside, age = self.latest()
        if age > self._stale_s:
            if not self._stale_logged:
                log.warning("no sensor data for %.1f s; treating as nobody there (check wiring and serial setup)", age)
                self._stale_logged = True
            return False
        if self._stale_logged:
            log.info("sensor data is back")
            self._stale_logged = False
        return inside

    def latest(self) -> tuple[RadarSample | None, bool, float]:
        """(last sample, in zone, seconds since the last frame)."""
        with self._lock:
            return self._latest, self._inside, time.monotonic() - self._last_frame

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=READ_TIMEOUT_S * 4)

    def _run(self) -> None:
        parser = HmmdParser()
        port: SerialPort | None = None
        last_error = ""
        while not self._stop.is_set():
            try:
                if port is None:
                    port = self._open_port()
                    port.reset_input_buffer()
                    port.write(ENABLE_REPORT_MODE)
                    port.flush()
                    self._stop.wait(REPORT_MODE_SETTLE_S)
                    log.info("serial port open; report mode requested")
                    last_error = ""
                chunk = port.read(max(1, port.in_waiting))
            except OSError as error:  # pyserial's SerialException is an OSError
                if str(error) != last_error:  # once per distinct problem, not every retry
                    log.error("serial port error: %s; retrying every %.0f s", error, RETRY_S)
                    last_error = str(error)
                port = _close_quietly(port)
                self._stop.wait(RETRY_S)
                continue
            for sample in parser.feed(chunk):
                with self._lock:
                    self._latest = sample
                    self._inside = self._zone.update(sample)
                    self._last_frame = time.monotonic()
        _close_quietly(port)


def _close_quietly(port: SerialPort | None) -> None:
    if port is None:
        return None
    try:
        port.close()
    except OSError:
        pass
    return None
