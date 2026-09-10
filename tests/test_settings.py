from pathlib import Path

import pytest

from player.settings import load_settings


def test_default_config_loads() -> None:
    settings = load_settings()
    assert settings.sensor.presence_on_s == pytest.approx(0.2)
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
