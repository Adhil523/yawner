"""Load player/config.toml into typed settings."""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from player.state_machine import Behaviour

DEFAULT_CONFIG = Path(__file__).resolve().parent / "config.toml"
DEFAULT_MANIFEST = "../build/manifest.json"

_ALLOWED_KEYS = {
    "top level": {"manifest", "sensor", "behaviour"},
    "sensor": {"gpio_pin", "presence_on_ms", "absence_off_s"},
    "behaviour": {"yawn_on_arrival", "repeat_while_present", "repeat_interval_s", "cooldown_s"},
}


@dataclass(frozen=True)
class SensorSettings:
    gpio_pin: int
    presence_on_s: float
    absence_off_s: float


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
            gpio_pin=int(sensor.get("gpio_pin", 17)),
            presence_on_s=float(sensor.get("presence_on_ms", 200)) / 1000,
            absence_off_s=float(sensor.get("absence_off_s", 5.0)),
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
    if any(value < 0 for value in durations):
        raise ValueError(f"{path.name}: times must not be negative")
    return settings
