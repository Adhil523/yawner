import numpy as np
import pytest

from analysis.segment import (
    SegmentationError,
    Segments,
    apply_overrides,
    best_end_to_start_cuts,
    detect_segments,
    median_smooth,
    natural_drift,
)


def _energy(head: int = 16, yawn: int = 190, tail: int = 34, still: float = 0.3, peak: float = 3.0) -> np.ndarray:
    noise = np.random.default_rng(0).uniform(-0.05, 0.05, head + yawn + tail)
    parts = [np.full(head, still), np.full(yawn, peak), np.full(tail, still)]
    return (np.concatenate(parts) + noise).astype(np.float32)


def test_finds_yawn_boundaries() -> None:
    segments = detect_segments(_energy())
    assert segments.head == (0, 15)
    assert segments.yawn == (16, 205)
    assert segments.tail == (206, 239)


def test_single_frame_glitches_in_still_parts_are_ignored() -> None:
    energy = _energy()
    energy[5] = 3.0
    energy[230] = 3.0
    assert detect_segments(energy).yawn == (16, 205)


def test_pause_mid_yawn_does_not_split_it() -> None:
    energy = _energy()
    energy[90:100] = 0.3
    assert detect_segments(energy).yawn == (16, 205)


def test_rejects_clip_that_starts_mid_yawn() -> None:
    with pytest.raises(SegmentationError, match="starts in motion"):
        detect_segments(_energy(head=0, tail=50))


def test_rejects_clip_without_motion() -> None:
    with pytest.raises(SegmentationError, match="no clear yawn"):
        detect_segments(np.full(240, 0.3, dtype=np.float32))


def test_override_moves_onset_and_keeps_detected_offset() -> None:
    assert apply_overrides(detect_segments(_energy()), onset=30).yawn == (30, 205)


@pytest.mark.parametrize("overrides", [{"onset": 0}, {"onset": 210}, {"offset": 239}])
def test_override_rejects_impossible_boundaries(overrides: dict[str, int]) -> None:
    with pytest.raises(SegmentationError, match="invalid yawn boundaries"):
        apply_overrides(detect_segments(_energy()), **overrides)


def test_median_smooth_rejects_even_window() -> None:
    with pytest.raises(ValueError):
        median_smooth(np.zeros(10, dtype=np.float32), 4)


def test_natural_drift_averages_pairs_inside_ranges_only() -> None:
    distances = np.abs(np.subtract.outer(np.arange(10.0), np.arange(10.0)))  # d = |i - j|
    drift = natural_drift(distances, [(0, 2), (7, 9)], gaps=(1, 2, 5))
    assert drift == {1: 1.0, 2: 2.0}  # gap 5 doesn't fit in either range


def test_best_cut_goes_from_still_end_to_still_start() -> None:
    segments = Segments(frame_count=10, onset=3, offset=6, still_level=0.3, threshold=0.6)
    windowed = np.full((10, 10), 9.0, dtype=np.float32)
    windowed[8, 1] = 0.5  # show frame 8, then frame 2
    windowed[2, 8] = 0.1  # wrong direction (start -> end); must be ignored
    best = best_end_to_start_cuts(windowed, segments, top=1)[0]
    assert (best.from_frame, best.to_frame, best.cost) == (8, 2, 0.5)
