import argparse
from pathlib import Path

import pytest

from analysis import config
from analysis.normalize import build_command, check_destination, check_size, parse_frame_rate


def test_command_strips_audio_and_fixes_rate_and_size(tmp_path: Path) -> None:
    command = build_command(Path("in.mp4"), tmp_path / "out.mkv", 720, 1280, "24/1")
    assert "-an" in command
    assert command[command.index("-vf") + 1].startswith("fps=24/1,scale=720:1280")
    assert command[command.index("-c:v") + 1] == "ffv1"


def test_rejects_aspect_ratio_change() -> None:
    with pytest.raises(ValueError, match="aspect"):
        check_size(1080, 1920, 1280, 720)


def test_rejects_odd_size() -> None:
    with pytest.raises(ValueError, match="even"):
        check_size(1080, 1920, 721, 1282)


def test_refuses_to_write_into_raw_assets() -> None:
    with pytest.raises(ValueError, match="read-only"):
        check_destination(config.RAW_DIR / "clip.mkv")


def test_frame_rate_parsing_is_exact() -> None:
    assert parse_frame_rate("24") == "24/1"
    assert parse_frame_rate("30000/1001") == "30000/1001"
    with pytest.raises(argparse.ArgumentTypeError):
        parse_frame_rate("0")
