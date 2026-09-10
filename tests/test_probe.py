from typing import Any

from analysis.probe import VideoInfo, find_issues


def _clip(**overrides: Any) -> VideoInfo:
    base: dict[str, Any] = {
        "path": "a.mp4", "width": 1080, "height": 1920, "frame_rate": "24/1", "avg_frame_rate": "24/1",
        "frame_count": 240, "duration_s": 10.0, "codec": "h264", "pix_fmt": "yuv420p",
        "field_order": "progressive", "has_audio": False, "bit_rate": 6_000_000,
    }
    return VideoInfo(**(base | overrides))


def test_clean_clip_has_no_issues() -> None:
    assert find_issues([_clip()]) == []


def test_flags_vfr_interlacing_short_clip_and_low_bitrate() -> None:
    issues = " ".join(find_issues([
        _clip(avg_frame_rate="2997/125", field_order="tt", duration_s=2.0, bit_rate=500_000),
    ]))
    for word in ("variable frame rate", "interlaced", "very short", "low bitrate"):
        assert word in issues


def test_flags_mismatch_between_clips() -> None:
    other = _clip(path="b.mp4", width=720, height=1280, frame_rate="30/1", avg_frame_rate="30/1")
    issues = find_issues([_clip(), other])
    assert "resolution differs between clips" in issues
    assert "frame rate differs between clips" in issues
