"""Load the manifest and hold every frame in RAM, ready for the render loop.

Frames are decoded once at startup, already scaled to the window. If they fit
the memory budget they are kept as display-ready pygame Surfaces, so the render
loop only ever blits. Otherwise they are kept as JPEG bytes and a worker thread
decodes the next frame while the current one is on screen (brief Phase 3).
"""

import io
import json
import logging
import os
import shutil
import subprocess
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal, Protocol, TypeVar

import pygame

from player.state_machine import FrameRef

log = logging.getLogger("frames")

MANIFEST_VERSION = 1
BYTES_PER_PIXEL = 4  # pygame display surfaces are 32-bit
RGB_BYTES_PER_PIXEL = 3
MEMORY_BUDGET_FRACTION = 0.6  # Surfaces above this share of available RAM -> JPEG fallback
JPEG_NAME_HINT = "frame.jpg"  # tells pygame which format to write and read
MEMINFO = Path("/proc/meminfo")
MB = 1e6

FrameMode = Literal["auto", "surfaces", "jpeg"]
FRAME_MODES: tuple[FrameMode, ...] = ("auto", "surfaces", "jpeg")
T = TypeVar("T")


class FrameStore(Protocol):
    def prepare(self, ref: FrameRef) -> None:
        """Hint that `ref` is the next frame to be shown."""

    def get(self, ref: FrameRef) -> pygame.Surface: ...

    def close(self) -> None: ...


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"{path} missing; run the analysis pipeline first (python -m analysis.pipeline ...)")
    manifest = json.loads(path.read_text())
    if manifest.get("version") != MANIFEST_VERSION:
        raise ValueError(f"{path.name} is version {manifest.get('version')}, this player reads {MANIFEST_VERSION}")
    return manifest


def available_memory_bytes() -> int | None:
    """MemAvailable on Linux (the Pi); total physical memory elsewhere; None if unknown."""
    if MEMINFO.is_file():
        for line in MEMINFO.read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    try:
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError, AttributeError):
        return None


def choose_mode(mode: FrameMode, needed: int, available: int | None) -> Literal["surfaces", "jpeg"]:
    if mode != "auto":
        return mode
    if available is None:
        return "surfaces"
    return "jpeg" if needed > available * MEMORY_BUDGET_FRACTION else "surfaces"


def iter_frames(path: Path, width: int, height: int) -> Iterator[bytes]:
    """RGB frames of `path`, scaled to width x height, one at a time (never the whole clip in memory)."""
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise RuntimeError("ffmpeg not found on PATH")
    frame_size = width * height * RGB_BYTES_PER_PIXEL
    process = subprocess.Popen(
        [
            executable, "-v", "error", "-i", str(path), "-an",
            "-vf", f"scale={width}:{height}:flags=area",
            "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None and process.stderr is not None
    try:
        while frame := process.stdout.read(frame_size):
            if len(frame) != frame_size:
                raise RuntimeError(f"ffmpeg returned a truncated frame from {path.name}")
            yield frame
    finally:
        process.stdout.close()
        stderr = process.stderr.read().decode(errors="replace").strip()
        process.stderr.close()
        if process.wait() != 0:
            raise RuntimeError(f"ffmpeg could not decode {path.name}: {stderr}")


def encode_jpeg(surface: pygame.Surface) -> bytes:
    buffer = io.BytesIO()
    pygame.image.save(surface, buffer, JPEG_NAME_HINT)
    return buffer.getvalue()


def decode_jpeg(data: bytes) -> pygame.Surface:
    return pygame.image.load(io.BytesIO(data), JPEG_NAME_HINT)


class SurfaceStore:
    def __init__(self, sequences: dict[str, list[pygame.Surface]]) -> None:
        self._sequences = sequences

    def prepare(self, ref: FrameRef) -> None:
        pass

    def get(self, ref: FrameRef) -> pygame.Surface:
        name, index = ref
        return self._sequences[name][index]

    def close(self) -> None:
        pass


class JpegStore:
    """JPEG bytes in RAM; one worker thread decodes the frame asked for by `prepare`."""

    def __init__(self, sequences: dict[str, list[bytes]]) -> None:
        self._sequences = sequences
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="frame-decode")
        self._pending: tuple[FrameRef, Future[pygame.Surface]] | None = None

    def prepare(self, ref: FrameRef) -> None:
        if self._pending is not None and self._pending[0] == ref:
            return
        self._pending = (ref, self._worker.submit(decode_jpeg, self._data(ref)))

    def get(self, ref: FrameRef) -> pygame.Surface:
        pending, self._pending = self._pending, None
        if pending is not None and pending[0] == ref:
            return pending[1].result()
        log.warning("frame %s:%d was not decoded ahead", *ref)
        return decode_jpeg(self._data(ref))

    def close(self) -> None:
        self._worker.shutdown(cancel_futures=True)

    def _data(self, ref: FrameRef) -> bytes:
        name, index = ref
        return self._sequences[name][index]


def load_frames(manifest: dict[str, Any], base_dir: Path, size: tuple[int, int], mode: FrameMode) -> FrameStore:
    """Needs an open display in Surface mode (Surface.convert matches its pixel format)."""
    width, height = size
    total = sum(int(sequence["frames"]) for sequence in manifest["sequences"].values())
    needed = total * width * height * BYTES_PER_PIXEL
    available = available_memory_bytes()
    chosen = choose_mode(mode, needed, available)
    log.info(
        "%d frames at %dx%d need ~%.0f MB as Surfaces; available RAM %s; keeping them as %s",
        total, width, height, needed / MB,
        f"~{available / MB:.0f} MB" if available is not None else "unknown", chosen,
    )

    sequences = manifest["sequences"]
    if chosen == "surfaces":
        return SurfaceStore({name: _load_sequence(base_dir, name, sequences[name], size, pygame.Surface.convert)
                             for name in sequences})
    jpegs = {name: _load_sequence(base_dir, name, sequences[name], size, encode_jpeg) for name in sequences}
    log.info("JPEG frames use ~%.0f MB", sum(len(data) for frames in jpegs.values() for data in frames) / MB)
    return JpegStore(jpegs)


def _load_sequence(
    base_dir: Path, name: str, sequence: dict[str, Any], size: tuple[int, int], keep: Callable[[pygame.Surface], T]
) -> list[T]:
    frames = [keep(pygame.image.frombuffer(raw, size, "RGB")) for raw in iter_frames(base_dir / sequence["file"], *size)]
    if len(frames) != sequence["frames"]:
        raise ValueError(f"{name}: manifest says {sequence['frames']} frames, file has {len(frames)}")
    return frames
