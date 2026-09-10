"""Frame descriptors and distances (brief 2b / 2c)."""

from pathlib import Path

import cv2
import numpy as np

from analysis import config
from analysis.probe import probe_video
from analysis.video_io import read_frames

# Upper bound on the float32 temporaries pairwise_distance allocates per chunk.
_PAIRWISE_CHUNK_ELEMENTS = 32_000_000


def scaled_size(width: int, height: int, long_side: int) -> tuple[int, int]:
    """(width, height) with the longer side set to `long_side`, aspect kept, both even."""
    scale = long_side / max(width, height)
    return max(2, round(width * scale / 2) * 2), max(2, round(height * scale / 2) * 2)


def compute_descriptors(gray: np.ndarray, blur_sigma: float = config.DESCRIPTOR_BLUR_SIGMA) -> np.ndarray:
    """(N, H, W) uint8 grayscale -> (N, H, W) float32, lightly blurred to ignore compression noise."""
    if gray.ndim != 3:
        raise ValueError(f"expected (N, H, W) grayscale frames, got shape {gray.shape}")
    descriptors = gray.astype(np.float32)
    if blur_sigma <= 0:
        return descriptors
    for index, frame in enumerate(descriptors):
        descriptors[index] = cv2.GaussianBlur(frame, (0, 0), blur_sigma)
    return descriptors


def load_descriptors(path: Path) -> np.ndarray:
    info = probe_video(path)
    width, height = scaled_size(info.width, info.height, config.DESCRIPTOR_LONG_SIDE)
    return compute_descriptors(read_frames(path, width, height, gray=True))


def pairwise_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """d[i, j] = mean |a[i] - b[j]| over all pixels."""
    if a.shape[1:] != b.shape[1:]:
        raise ValueError(f"frame shapes differ: {a.shape[1:]} vs {b.shape[1:]}")
    flat_a = a.reshape(len(a), -1)
    flat_b = b.reshape(len(b), -1)
    rows_per_chunk = max(1, _PAIRWISE_CHUNK_ELEMENTS // (len(b) * flat_b.shape[1]))
    distances = np.empty((len(a), len(b)), dtype=np.float32)
    for start in range(0, len(a), rows_per_chunk):
        block = flat_a[start:start + rows_per_chunk, None, :] - flat_b[None, :, :]
        distances[start:start + rows_per_chunk] = np.abs(block).mean(axis=2)
    return distances


def motion_energy(descriptors: np.ndarray) -> np.ndarray:
    """energy[i] = d(frame i-1, frame i); energy[0] repeats energy[1] so lengths match."""
    if len(descriptors) < 2:
        raise ValueError("need at least two frames")
    flat = descriptors.reshape(len(descriptors), -1)
    steps = np.abs(np.diff(flat, axis=0)).mean(axis=1)
    return np.concatenate([steps[:1], steps]).astype(np.float32)


def windowed_distance(distances: np.ndarray, weights: tuple[float, ...] = config.WINDOW_WEIGHTS) -> np.ndarray:
    """D[i, j] = sum_k w_k * d[i+k, j+k], normalised by the weights actually used.

    A cut "from i to j" shows frame i and then frame j+1. Low D means pose *and*
    motion agree around the cut; single-frame distance can't tell a matching pose
    moving the opposite way. Window taps that fall off either clip are dropped
    and the remaining weights renormalised.
    """
    if len(weights) % 2 == 0 or min(weights) <= 0:
        raise ValueError("weights must be an odd-length sequence of positive numbers")
    half = len(weights) // 2
    rows, cols = distances.shape
    total = np.zeros((rows, cols), dtype=np.float64)
    weight_sum = np.zeros((rows, cols), dtype=np.float64)
    for offset, weight in zip(range(-half, half + 1), weights):
        row_start, row_end = max(0, -offset), min(rows, rows - offset)
        col_start, col_end = max(0, -offset), min(cols, cols - offset)
        if row_start >= row_end or col_start >= col_end:
            continue
        total[row_start:row_end, col_start:col_end] += weight * distances[
            row_start + offset:row_end + offset, col_start + offset:col_end + offset
        ]
        weight_sum[row_start:row_end, col_start:col_end] += weight
    return (total / weight_sum).astype(np.float32)
