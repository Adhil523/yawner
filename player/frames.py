"""Load the manifest and decode every sequence into display-ready pygame Surfaces.

Frames are decoded once at startup, already scaled to the window, so the render
loop only ever blits.
"""

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pygame

log = logging.getLogger("frames")

MANIFEST_VERSION = 1
BYTES_PER_PIXEL = 4  # pygame display surfaces are 32-bit


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"{path} missing; run the analysis pipeline first (python -m analysis.pipeline ...)")
    manifest = json.loads(path.read_text())
    if manifest.get("version") != MANIFEST_VERSION:
        raise ValueError(f"{path.name} is version {manifest.get('version')}, this player reads {MANIFEST_VERSION}")
    return manifest


def decode(path: Path, width: int, height: int) -> np.ndarray:
    """All frames of `path` as (N, H, W, 3) RGB, scaled to width x height."""
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise RuntimeError("ffmpeg not found on PATH")
    result = subprocess.run(
        [
            executable, "-v", "error", "-i", str(path), "-an",
            "-vf", f"scale={width}:{height}:flags=area",
            "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg could not decode {path.name}: {result.stderr.decode(errors='replace').strip()}")
    return np.frombuffer(result.stdout, dtype=np.uint8).reshape(-1, height, width, 3)


def load_sequences(manifest: dict[str, Any], base_dir: Path, size: tuple[int, int]) -> dict[str, list[pygame.Surface]]:
    """Needs an open display (Surface.convert matches its pixel format)."""
    width, height = size
    total = sum(int(sequence["frames"]) for sequence in manifest["sequences"].values())
    log.info("decoding %d frames at %dx%d (~%.0f MB in memory)", total, width, height,
             total * width * height * BYTES_PER_PIXEL / 1e6)
    sequences = {}
    for name, sequence in manifest["sequences"].items():
        frames = decode(base_dir / sequence["file"], width, height)
        if len(frames) != sequence["frames"]:
            raise ValueError(f"{name}: manifest says {sequence['frames']} frames, file has {len(frames)}")
        sequences[name] = [pygame.image.frombuffer(frame.tobytes(), size, "RGB").convert() for frame in frames]
    return sequences
