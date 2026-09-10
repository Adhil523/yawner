"""Transcode a source clip to constant fps, target resolution, no audio (brief 2a).

    python -m analysis.normalize assets/raw/<clip>.mp4 [--width 720 --height 1280 --fps 24]

Output is FFV1 (lossless) in Matroska at build/normalized/<clip>.mkv, so later
steps see exactly the pixels the scaler produced. Raw assets are never modified.
"""

import argparse
import logging
import sys
from fractions import Fraction
from pathlib import Path

from analysis import config
from analysis.cli import existing_file, repo_relative, setup_logging
from analysis.probe import probe_video
from analysis.video_io import VideoToolError, run_tool

log = logging.getLogger("normalize")


def output_path_for(source: Path) -> Path:
    return config.NORMALIZED_DIR / f"{source.stem}.mkv"


def check_size(src_width: int, src_height: int, width: int, height: int) -> None:
    if width <= 0 or height <= 0 or width % 2 or height % 2:
        raise ValueError(f"target size must be positive and even, got {width}x{height}")
    src_aspect = src_width / src_height
    if abs(src_aspect - width / height) / src_aspect > config.MAX_ASPECT_MISMATCH:
        raise ValueError(
            f"aspect ratio mismatch: source {src_width}x{src_height}, target {width}x{height}; "
            "pass --width/--height with the source's shape"
        )


def check_destination(destination: Path) -> None:
    if destination.resolve().is_relative_to(config.RAW_DIR.resolve()):
        raise ValueError(f"refusing to write into {repo_relative(config.RAW_DIR)}: raw assets are read-only")


def parse_frame_rate(value: str) -> str:
    """argparse type: accept "24", "30000/1001", ... and keep it exact."""
    try:
        rate = Fraction(value)
    except (ValueError, ZeroDivisionError) as error:
        raise argparse.ArgumentTypeError(f"not a frame rate: {value}") from error
    if rate <= 0:
        raise argparse.ArgumentTypeError(f"frame rate must be positive: {value}")
    return f"{rate.numerator}/{rate.denominator}"


def build_command(source: Path, destination: Path, width: int, height: int, frame_rate: str) -> list[str]:
    return [
        "ffmpeg", "-v", "error", "-y", "-i", str(source),
        "-map", "0:v:0", "-an", "-sn", "-dn",
        "-vf", f"fps={frame_rate},scale={width}:{height}:flags=lanczos,format=yuv420p",
        "-c:v", "ffv1", "-level", "3", "-g", "1",
        str(destination),
    ]


def run(
    source: Path,
    width: int = config.TARGET_WIDTH,
    height: int = config.TARGET_HEIGHT,
    frame_rate: str | None = None,
    destination: Path | None = None,
) -> Path:
    info = probe_video(source)
    check_size(info.width, info.height, width, height)
    target = destination or output_path_for(source)
    check_destination(target)
    rate = frame_rate or info.frame_rate

    target.parent.mkdir(parents=True, exist_ok=True)
    run_tool(build_command(source, target, width, height, rate))

    result = probe_video(target)
    log.info(
        "%s -> %s: %dx%d @ %s fps, ~%d frames, no audio",
        Path(info.path).name, repo_relative(target), result.width, result.height, result.frame_rate, result.frame_count,
    )
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=existing_file)
    parser.add_argument("--width", type=int, default=config.TARGET_WIDTH)
    parser.add_argument("--height", type=int, default=config.TARGET_HEIGHT)
    parser.add_argument("--fps", type=parse_frame_rate, default=None, help="default: keep the source rate")
    parser.add_argument("--out", type=Path, default=None, help="default: build/normalized/<clip>.mkv")
    args = parser.parse_args()
    setup_logging()
    try:
        run(args.source, args.width, args.height, args.fps, args.out)
    except (ValueError, VideoToolError) as error:
        log.error("%s", error)
        sys.exit(1)


if __name__ == "__main__":
    main()
