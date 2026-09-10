"""Thin wrappers around ffprobe / ffmpeg.

All decoding goes through here, so the analysis never depends on which codecs a
particular OpenCV build supports.
"""

import json
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np


class VideoToolError(RuntimeError):
    """ffmpeg / ffprobe is missing, failed, or returned something unexpected."""


def run_tool(args: list[str]) -> bytes:
    executable = shutil.which(args[0])
    if executable is None:
        raise VideoToolError(f"{args[0]} not found on PATH (macOS: brew install ffmpeg)")
    result = subprocess.run([executable, *args[1:]], capture_output=True, check=False)
    if result.returncode != 0:
        message = result.stderr.decode(errors="replace").strip()
        raise VideoToolError(f"{args[0]} failed: {message}")
    return result.stdout


def ffprobe(path: Path) -> dict[str, Any]:
    output = run_tool(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)])
    return json.loads(output)


def read_frames(
    path: Path,
    width: int,
    height: int,
    *,
    gray: bool = False,
    indices: Sequence[int] | None = None,
) -> np.ndarray:
    """Decode frames scaled to width x height (area filter).

    Returns uint8 (N, H, W) when gray, else (N, H, W, 3) RGB. With `indices`
    (strictly increasing), only those frames are decoded, in that order.
    """
    filters: list[str] = []
    if indices is not None:
        if not indices or list(indices) != sorted(set(indices)):
            raise ValueError("indices must be a non-empty, strictly increasing sequence")
        expression = "+".join(f"eq(n\\,{index})" for index in indices)
        filters.append(f"select='{expression}'")
    filters.append(f"scale={width}:{height}:flags=area")

    pix_fmt, channels = ("gray", 1) if gray else ("rgb24", 3)
    raw = run_tool([
        "ffmpeg", "-v", "error", "-i", str(path), "-an",
        "-vf", ",".join(filters),
        "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", pix_fmt, "-",
    ])

    frame_size = width * height * channels
    if not raw or len(raw) % frame_size != 0:
        raise VideoToolError(f"decoded {len(raw)} bytes, not a whole number of {width}x{height} {pix_fmt} frames")
    shape = (-1, height, width) if gray else (-1, height, width, 3)
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(shape)
    if indices is not None and len(frames) != len(indices):
        raise VideoToolError(f"asked for {len(indices)} frames, decoded {len(frames)}")
    return frames
