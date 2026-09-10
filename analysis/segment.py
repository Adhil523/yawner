"""Split one clip into still start / yawn / still end using motion energy.

    python -m analysis.segment build/normalized/<clip>.mkv

The clip must begin and end with the man standing still. Also measures how much
the picture drifts on its own in the still parts, and how costly the jump from
the still end back to the still start is: the idle loop and the entry into the
yawn are both built from that jump. Writes build/segments.json and review images
in build/preview/.
"""

import argparse
import json
import logging
import math
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

from analysis import config
from analysis.cli import existing_file, repo_relative, setup_logging
from analysis.features import load_descriptors, motion_energy, pairwise_distance, scaled_size, windowed_distance
from analysis.probe import VideoInfo, probe_video
from analysis.video_io import VideoToolError, read_frames
from analysis.visuals import BGR, contact_sheet, difference_strip, line_plot, rgb_to_bgr, save_png

log = logging.getLogger("segment")

HEAD_COLOR: BGR = (90, 180, 90)
YAWN_COLOR: BGR = (70, 70, 220)
TAIL_COLOR: BGR = (220, 150, 70)
DETECTED_COLOR: BGR = (150, 150, 150)
SHEET_TILES = 30
SHEET_COLUMNS = 10
SHEET_LONG_SIDE = 256
DIFF_LONG_SIDE = 640
DIFF_GAIN = 8.0


class SegmentationError(ValueError):
    """The clip doesn't have the still -> yawn -> still structure."""


@dataclass(frozen=True)
class Segments:
    frame_count: int
    onset: int  # first yawn frame
    offset: int  # last yawn frame
    still_level: float
    threshold: float

    @property
    def head(self) -> tuple[int, int]:
        return (0, self.onset - 1)

    @property
    def yawn(self) -> tuple[int, int]:
        return (self.onset, self.offset)

    @property
    def tail(self) -> tuple[int, int]:
        return (self.offset + 1, self.frame_count - 1)

    @property
    def head_frames(self) -> int:
        return self.onset

    @property
    def tail_frames(self) -> int:
        return self.frame_count - 1 - self.offset


@dataclass(frozen=True)
class Cut:
    from_frame: int  # last frame shown before the cut
    to_frame: int  # first frame shown after it
    cost: float


def median_smooth(values: np.ndarray, window: int) -> np.ndarray:
    if window < 1 or window % 2 == 0:
        raise ValueError("window must be a positive odd number")
    padded = np.pad(values, window // 2, mode="edge")
    return np.median(np.lib.stride_tricks.sliding_window_view(padded, window), axis=1).astype(np.float32)


def detect_segments(
    energy: np.ndarray,
    edge_fraction: float = config.EDGE_FRACTION,
    smooth_window: int = config.ENERGY_SMOOTH_WINDOW,
    onset_fraction: float = config.ONSET_FRACTION,
) -> Segments:
    """The yawn spans from the first to the last frame whose smoothed motion is above threshold.

    Using the outermost crossings keeps a pause mid-yawn from splitting it; the
    median filter keeps single-frame glitches in the still parts from extending it.
    """
    count = len(energy)
    edge = max(3, int(count * edge_fraction))
    if count < 4 * edge:
        raise SegmentationError(f"clip too short to segment ({count} frames)")

    smoothed = median_smooth(energy, smooth_window)
    # The quieter end sets the still level, so one end being in motion can't hide it.
    still_level = float(min(np.median(smoothed[:edge]), np.median(smoothed[-edge:])))
    peak = float(smoothed.max())
    if peak < 2 * still_level:
        raise SegmentationError("no clear yawn: peak motion is less than twice the still level")

    threshold = still_level + onset_fraction * (peak - still_level)
    moving = np.flatnonzero(smoothed > threshold)
    onset, offset = int(moving[0]), int(moving[-1])
    if onset == 0:
        raise SegmentationError("clip starts in motion; it must begin with the man standing still")
    if offset == count - 1:
        raise SegmentationError("clip ends in motion; it must end with the man standing still")
    return Segments(count, onset, offset, still_level, threshold)


def apply_overrides(segments: Segments, onset: int | None = None, offset: int | None = None) -> Segments:
    """Swap in yawn boundaries a human chose after reviewing the contact sheet."""
    updated = replace(
        segments,
        onset=segments.onset if onset is None else onset,
        offset=segments.offset if offset is None else offset,
    )
    if not 0 < updated.onset <= updated.offset < updated.frame_count - 1:
        raise SegmentationError(
            f"invalid yawn boundaries {updated.onset}-{updated.offset} for a {updated.frame_count}-frame clip; "
            "the clip needs still frames before and after the yawn"
        )
    return updated


def natural_drift(distances: np.ndarray, ranges: list[tuple[int, int]], gaps: tuple[int, ...]) -> dict[int, float]:
    """Mean d(i, i + gap) inside the given (inclusive) still ranges.

    How much the picture changes on its own over `gap` frames; the yardstick for
    judging whether a seam cost is visible.
    """
    drift: dict[int, float] = {}
    for gap in gaps:
        values = [distances[i, i + gap] for start, end in ranges for i in range(start, end - gap + 1)]
        if values:
            drift[gap] = float(np.mean(values))
    return drift


def best_end_to_start_cuts(windowed: np.ndarray, segments: Segments, top: int) -> list[Cut]:
    """Lowest-cost cuts from a still-end frame i to a still-start frame j + 1."""
    tail_start, tail_end = segments.tail
    head_end = segments.head[1]
    if head_end < 1:
        return []
    block = windowed[tail_start:tail_end + 1, 0:head_end]  # column j -> shows frame j + 1 next
    cuts: list[Cut] = []
    for flat_index in np.argsort(block, axis=None)[:top]:
        row, column = np.unravel_index(flat_index, block.shape)
        cuts.append(Cut(tail_start + int(row), int(column) + 1, float(block[row, column])))
    return cuts


def find_issues(segments: Segments, fps: float, drift: dict[int, float], cuts: list[Cut]) -> list[str]:
    issues: list[str] = []
    idle_seconds = (segments.head_frames + segments.tail_frames) / fps
    if idle_seconds < config.MIN_IDLE_SECONDS:
        issues.append(
            f"only {idle_seconds:.1f} s of still footage (start {segments.head_frames / fps:.1f} s + "
            f"end {segments.tail_frames / fps:.1f} s); the brief asks for at least "
            f"{config.MIN_IDLE_SECONDS:g} s, so the idle loop will be short"
        )
    reference = drift.get(config.DRIFT_REFERENCE_GAP)
    if cuts and reference:
        ratio = cuts[0].cost / reference
        if ratio > config.CUT_DRIFT_RATIO_FLAG:
            issues.append(
                f"best end-to-start jump costs {ratio:.1f}x the natural drift over "
                f"{config.DRIFT_REFERENCE_GAP} frames; it will need a crossfade bridge"
            )
    return issues


def _segment_color(frame: int, segments: Segments) -> BGR:
    if frame < segments.onset:
        return HEAD_COLOR
    if frame <= segments.offset:
        return YAWN_COLOR
    return TAIL_COLOR


def _write_previews(
    clip: Path, info: VideoInfo, segments: Segments, detected: Segments, energy: np.ndarray, cuts: list[Cut]
) -> dict[str, str]:
    previews: dict[str, Path] = {}

    step = math.ceil(segments.frame_count / SHEET_TILES)
    indices = list(range(0, segments.frame_count, step))
    tile_width, tile_height = scaled_size(info.width, info.height, SHEET_LONG_SIDE)
    tiles = rgb_to_bgr(read_frames(clip, tile_width, tile_height, indices=indices))
    colors = [_segment_color(index, segments) for index in indices]
    previews["contact_sheet"] = config.PREVIEW_DIR / "contact_sheet.png"
    save_png(previews["contact_sheet"], contact_sheet(tiles, [str(i) for i in indices], colors, SHEET_COLUMNS))

    plot = line_plot(
        series=[
            ("raw", energy, (130, 130, 130)),
            ("smoothed", median_smooth(energy, config.ENERGY_SMOOTH_WINDOW), (245, 245, 245)),
        ],
        hlines=[("threshold", segments.threshold, (0, 200, 255))],
        vlines=[("onset", segments.onset, YAWN_COLOR), ("offset", segments.offset, YAWN_COLOR)] + [
            ("auto", auto, DETECTED_COLOR)
            for auto, final in ((detected.onset, segments.onset), (detected.offset, segments.offset))
            if auto != final
        ],
        fps=info.fps,
    )
    previews["motion"] = config.PREVIEW_DIR / "motion.png"
    save_png(previews["motion"], plot)

    tail_start, tail_end = segments.tail
    if cuts and tail_end - tail_start >= config.DRIFT_REFERENCE_GAP:
        best = cuts[0]
        natural = (tail_end - config.DRIFT_REFERENCE_GAP, tail_end)
        wanted = sorted({best.from_frame, best.to_frame, *natural})
        width, height = scaled_size(info.width, info.height, DIFF_LONG_SIDE)
        frames = dict(zip(wanted, rgb_to_bgr(read_frames(clip, width, height, indices=wanted))))
        seam = difference_strip(
            frames[best.from_frame], frames[best.to_frame], DIFF_GAIN,
            (f"end: frame {best.from_frame}", f"start: frame {best.to_frame}", f"|difference| x{DIFF_GAIN:g}"),
        )
        baseline = difference_strip(
            frames[natural[0]], frames[natural[1]], DIFF_GAIN,
            (f"frame {natural[0]}", f"frame {natural[1]}", f"natural {config.DRIFT_REFERENCE_GAP}-frame drift"),
        )
        previews["seam_difference"] = config.PREVIEW_DIR / "seam_difference.png"
        save_png(previews["seam_difference"], np.vstack([seam, baseline]))

    return {name: repo_relative(path) for name, path in previews.items()}


def run(clip: Path, json_out: Path = config.SEGMENTS_JSON) -> dict[str, Any]:
    info = probe_video(clip)
    descriptors = load_descriptors(clip)
    energy = motion_energy(descriptors)
    detected = detect_segments(energy)
    overrides = config.SEGMENT_OVERRIDES.get(clip.stem, {})
    segments = apply_overrides(detected, **overrides)
    distances = pairwise_distance(descriptors, descriptors)
    drift = natural_drift(distances, [segments.head, segments.tail], config.DRIFT_GAPS)
    cuts = best_end_to_start_cuts(windowed_distance(distances), segments, config.TOP_CUTS)
    issues = find_issues(segments, info.fps, drift, cuts)
    previews = _write_previews(clip, info, segments, detected, energy, cuts)

    log.info(
        "still start %s, yawn %s, still end %s (threshold %.3f)",
        segments.head, segments.yawn, segments.tail, segments.threshold,
    )
    if overrides:
        log.info("boundaries corrected in config %s; auto-detected yawn was %s", overrides, detected.yawn)
    for cut in cuts[:1]:
        log.info("best end-to-start cut: %d -> %d, cost %.3f", cut.from_frame, cut.to_frame, cut.cost)
    for issue in issues:
        log.info("flag: %s", issue)

    result = {
        "clip": repo_relative(clip),
        "fps": info.fps,
        "frame_count": segments.frame_count,
        "segments": {"head": segments.head, "yawn": segments.yawn, "tail": segments.tail},
        "detected_yawn": detected.yawn,
        "overrides": overrides,
        "still_level": round(segments.still_level, 4),
        "threshold": round(segments.threshold, 4),
        "natural_drift": {str(gap): round(value, 4) for gap, value in drift.items()},
        "best_end_to_start_cuts": [asdict(cut) | {"cost": round(cut.cost, 4)} for cut in cuts],
        "issues": issues,
        "previews": previews,
        "motion_energy": [round(float(value), 4) for value in energy],
    }
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(result, indent=2) + "\n")
    log.info("wrote %s", repo_relative(json_out))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("clip", type=existing_file, help="normalised clip, e.g. build/normalized/<clip>.mkv")
    parser.add_argument("--json-out", type=Path, default=config.SEGMENTS_JSON)
    args = parser.parse_args()
    setup_logging()
    try:
        run(args.clip, args.json_out)
    except (ValueError, VideoToolError) as error:
        log.error("%s", error)
        sys.exit(1)


if __name__ == "__main__":
    main()
