"""Thin wrappers around ffprobe / ffmpeg.

All decoding and encoding goes through here, so the analysis never depends on
which codecs a particular OpenCV build supports.
"""

import json
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from types import TracebackType
from typing import Any

import numpy as np

# Lossless; used for everything the player loads.
FFV1_ARGS = ["-c:v", "ffv1", "-level", "3", "-g", "1", "-pix_fmt", "yuv420p"]
# Visually lossless and small; used for review videos.
H264_ARGS = ["-c:v", "libx264", "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv420p"]


class VideoToolError(RuntimeError):
    """ffmpeg / ffprobe is missing, failed, or returned something unexpected."""


def _executable(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise VideoToolError(f"{name} not found on PATH (macOS: brew install ffmpeg)")
    return path


def run_tool(args: list[str]) -> bytes:
    result = subprocess.run([_executable(args[0]), *args[1:]], capture_output=True, check=False)
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


class VideoWriter:
    """Stream (H, W, 3) RGB uint8 frames into an ffmpeg encoder. Use as a context manager."""

    def __init__(self, path: Path, width: int, height: int, frame_rate: str, codec_args: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._shape = (height, width, 3)
        self._process = subprocess.Popen(
            [
                _executable("ffmpeg"), "-v", "error", "-y",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", frame_rate, "-i", "-",
                *codec_args, str(path),
            ],
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def write(self, frame: np.ndarray) -> None:
        if frame.shape != self._shape or frame.dtype != np.uint8:
            raise ValueError(f"expected a {self._shape} uint8 frame, got {frame.shape} {frame.dtype}")
        stdin = self._process.stdin
        if stdin is None:
            raise VideoToolError("ffmpeg encoder has no input pipe")
        stdin.write(np.ascontiguousarray(frame).tobytes())

    def close(self) -> None:
        _, stderr = self._process.communicate()
        if self._process.returncode != 0:
            raise VideoToolError(f"ffmpeg failed: {stderr.decode(errors='replace').strip()}")

    def __enter__(self) -> "VideoWriter":
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None
    ) -> None:
        self.close()


def write_frames(path: Path, frames: np.ndarray, frame_rate: str) -> None:
    """Encode (N, H, W, 3) RGB frames losslessly (FFV1)."""
    height, width = frames.shape[1:3]
    with VideoWriter(path, width, height, frame_rate, FFV1_ARGS) as writer:
        for frame in frames:
            writer.write(frame)
