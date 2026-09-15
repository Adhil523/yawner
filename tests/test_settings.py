from pathlib import Path

import pytest

from player.settings import load_settings


def test_default_config_loads() -> None:
    settings = load_settings()
    assert settings.sensor.presence_on_s == pytest.approx(0.2)
    assert settings.behaviour.repeat_while_present is True
    assert settings.behaviour.repeat_interval_s == 5.0
    assert settings.behaviour.cooldown_s == 5.0
    assert settings.manifest.name == "manifest.json"


def test_rejects_misspelt_setting(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[behaviour]\ncooldwn_s = 3\n")
    with pytest.raises(ValueError, match="cooldwn_s"):
        load_settings(path)


def test_rejects_negative_time(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[sensor]\nabsence_off_s = -1\n")
    with pytest.raises(ValueError, match="negative"):
        load_settings(path)


def test_rejects_gpio_pin_off_the_header(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[sensor]\ngpio_pin = 40\n")
    with pytest.raises(ValueError, match="gpio_pin"):
        load_settings(path)


def test_default_config_has_the_hmmd_zone() -> None:
    sensor = load_settings().sensor
    assert (sensor.serial_device, sensor.baud) == ("auto", 115200)
    assert (sensor.min_cm, sensor.max_cm, sensor.rearm_cm) == (50, 200, 260)


def test_rejects_zone_that_clears_inside_itself(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[sensor]\nmax_cm = 300\nrearm_cm = 250\n")
    with pytest.raises(ValueError, match="rearm_cm"):
        load_settings(path)
