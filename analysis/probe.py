"""Report source clip metadata and flag problems before any processing (Phase 0).

    python -m analysis.probe assets/raw/<clip>.mp4 [more clips ...]

Writes build/probe.json.
"""

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from analysis import config
from analysis.cli import existing_file, repo_relative, setup_logging
from analysis.video_io import VideoToolError, ffprobe

log = logging.getLogger("probe")


@dataclass(frozen=True)
class VideoInfo:
    path: str
    width: int
    height: int
    frame_rate: str  # exact rational from the container, e.g. "24/1"
    avg_frame_rate: str
    frame_count: int
    duration_s: float
    codec: str
    pix_fmt: str
    field_order: str
    has_audio: bool
    bit_rate: int | None

    @property
    def fps(self) -> float:
        return float(Fraction(self.frame_rate))


def _parse_rate(value: str) -> float | None:
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return None


def _first_stream(meta: dict[str, Any], kind: str) -> dict[str, Any] | None:
    return next((s for s in meta.get("streams", []) if s.get("codec_type") == kind), None)


def probe_video(path: Path) -> VideoInfo:
    meta = ffprobe(path)
    video = _first_stream(meta, "video")
    if video is None:
        raise ValueError(f"no video stream in {path}")

    container = meta.get("format", {})
    frame_rate = video["r_frame_rate"]
    duration = float(video.get("duration") or container.get("duration") or 0.0)
    nb_frames = video.get("nb_frames")  # absent in Matroska; fall back to duration x fps
    frame_count = int(nb_frames) if nb_frames else round(duration * float(Fraction(frame_rate)))
    bit_rate = video.get("bit_rate") or container.get("bit_rate")

    return VideoInfo(
        path=repo_relative(path),
        width=int(video["width"]),
        height=int(video["height"]),
        frame_rate=frame_rate,
        avg_frame_rate=video.get("avg_frame_rate", frame_rate),
        frame_count=frame_count,
        duration_s=duration,
        codec=video.get("codec_name", "unknown"),
        pix_fmt=video.get("pix_fmt", "unknown"),
        field_order=video.get("field_order", "unknown"),
        has_audio=_first_stream(meta, "audio") is not None,
        bit_rate=int(bit_rate) if bit_rate else None,
    )


def find_issues(clips: list[VideoInfo]) -> list[str]:
    issues: list[str] = []
    for clip in clips:
        name = Path(clip.path).name
        avg_fps = _parse_rate(clip.avg_frame_rate)
        if avg_fps is None or abs(avg_fps - clip.fps) > 0.01:
            issues.append(f"{name}: variable frame rate (r={clip.frame_rate}, avg={clip.avg_frame_rate})")
        if clip.field_order not in ("progressive", "unknown"):
            issues.append(f"{name}: interlaced ({clip.field_order})")
        if clip.duration_s < config.MIN_CLIP_SECONDS:
            issues.append(f"{name}: very short ({clip.duration_s:.2f} s)")
        if clip.bit_rate is not None:
            bits_per_pixel = clip.bit_rate / (clip.width * clip.height * clip.fps)
            if bits_per_pixel < config.LOW_BITS_PER_PIXEL:
                issues.append(f"{name}: low bitrate ({bits_per_pixel:.3f} bits/pixel), expect compression noise")
        if clip.has_audio:
            issues.append(f"{name}: has an audio track (normalize strips it)")
    if len({(clip.width, clip.height) for clip in clips}) > 1:
        issues.append("resolution differs between clips")
    if len({clip.frame_rate for clip in clips}) > 1:
        issues.append("frame rate differs between clips")
    return issues


def run(paths: list[Path], json_out: Path = config.PROBE_JSON) -> dict[str, Any]:
    clips = [probe_video(path) for path in paths]
    issues = find_issues(clips)
    for clip in clips:
        log.info(
            "%s: %dx%d @ %s fps, %d frames, %.2f s, %s/%s, %s, audio=%s",
            Path(clip.path).name, clip.width, clip.height, clip.frame_rate, clip.frame_count,
            clip.duration_s, clip.codec, clip.pix_fmt, clip.field_order, clip.has_audio,
        )
    for issue in issues:
        log.info("flag: %s", issue)

    report = {"clips": [asdict(clip) | {"fps": clip.fps} for clip in clips], "issues": issues}
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(report, indent=2) + "\n")
    log.info("wrote %s", repo_relative(json_out))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("clips", nargs="+", type=existing_file, help="source video(s)")
    parser.add_argument("--json-out", type=Path, default=config.PROBE_JSON)
    args = parser.parse_args()
    setup_logging()
    try:
        run(args.clips, args.json_out)
    except (ValueError, VideoToolError) as error:
        log.error("%s", error)
        sys.exit(1)


if __name__ == "__main__":
    main()
