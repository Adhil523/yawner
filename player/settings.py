"""Load player/config.toml into typed settings."""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from player.hmmd import AUTO_DEVICE, DEFAULT_BAUD, DistanceZone
from player.state_machine import Behaviour

DEFAULT_CONFIG = Path(__file__).resolve().parent / "config.toml"
DEFAULT_MANIFEST = "../build/manifest.json"
GPIO_PINS = range(0, 28)  # BCM GPIO numbers on the 40-pin header

_ALLOWED_KEYS = {
    "top level": {"manifest", "sensor", "behaviour"},
    "sensor": {"presence_on_ms", "absence_off_s", "serial_device", "baud", "min_cm", "max_cm", "rearm_cm", "gpio_pin"},
    "behaviour": {"yawn_on_arrival", "repeat_while_present", "repeat_interval_s", "cooldown_s"},
}


@dataclass(frozen=True)
class SensorSettings:
    presence_on_s: float
    absence_off_s: float
    serial_device: str
    baud: int
    min_cm: int
    max_cm: int
    rearm_cm: int
    gpio_pin: int

    def zone(self) -> DistanceZone:
        return DistanceZone(self.min_cm, self.max_cm, self.rearm_cm)


@dataclass(frozen=True)
class Settings:
    manifest: Path
    sensor: SensorSettings
    behaviour: Behaviour


def _check_keys(section: str, table: dict[str, Any]) -> None:
    unknown = set(table) - _ALLOWED_KEYS[section]
    if unknown:
        raise ValueError(f"unknown setting(s) in [{section}]: {', '.join(sorted(unknown))}")


def load_settings(path: Path = DEFAULT_CONFIG) -> Settings:
    data = tomllib.loads(path.read_text())
    sensor = data.get("sensor", {})
    behaviour = data.get("behaviour", {})
    _check_keys("top level", data)
    _check_keys("sensor", sensor)
    _check_keys("behaviour", behaviour)

    settings = Settings(
        manifest=(path.parent / data.get("manifest", DEFAULT_MANIFEST)).resolve(),
        sensor=SensorSettings(
            presence_on_s=float(sensor.get("presence_on_ms", 200)) / 1000,
            absence_off_s=float(sensor.get("absence_off_s", 5.0)),
            serial_device=str(sensor.get("serial_device", AUTO_DEVICE)),
            baud=int(sensor.get("baud", DEFAULT_BAUD)),
            min_cm=int(sensor.get("min_cm", 50)),
            max_cm=int(sensor.get("max_cm", 200)),
            rearm_cm=int(sensor.get("rearm_cm", 260)),
            gpio_pin=int(sensor.get("gpio_pin", 17)),
        ),
        behaviour=Behaviour(
            yawn_on_arrival=bool(behaviour.get("yawn_on_arrival", True)),
            repeat_while_present=bool(behaviour.get("repeat_while_present", False)),
            repeat_interval_s=float(behaviour.get("repeat_interval_s", 20.0)),
            cooldown_s=float(behaviour.get("cooldown_s", 5.0)),
        ),
    )
    durations = (
        settings.sensor.presence_on_s,
        settings.sensor.absence_off_s,
        settings.behaviour.repeat_interval_s,
        settings.behaviour.cooldown_s,
    )
    if not GPIO_PINS.start <= settings.sensor.gpio_pin < GPIO_PINS.stop:
        raise ValueError(f"{path.name}: gpio_pin must be a BCM GPIO number {GPIO_PINS.start}-{GPIO_PINS.stop - 1}")
    try:
        settings.sensor.zone()
    except ValueError as error:
        raise ValueError(f"{path.name}: {error}") from error
    if any(value < 0 for value in durations):
        raise ValueError(f"{path.name}: times must not be negative")
    return settings
