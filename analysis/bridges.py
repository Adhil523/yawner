"""Pre-rendered crossfade bridges (brief 2g). The player never blends at runtime."""

import numpy as np


def bridge_sources(at: int, resume: int, length: int) -> tuple[list[int], list[int]]:
    """Main frames a bridge blends: the ones that would have followed `at`,
    and the ones leading up to `resume`."""
    return list(range(at + 1, at + 1 + length)), list(range(resume - length, resume))


def crossfade(outgoing: np.ndarray, incoming: np.ndarray) -> np.ndarray:
    """Linear blend with the weight moving from outgoing to incoming.

    Neither end is a pure copy, so every bridge frame sits strictly between the
    frames shown around it.
    """
    if outgoing.shape != incoming.shape:
        raise ValueError(f"frame runs differ: {outgoing.shape} vs {incoming.shape}")
    count = len(outgoing)
    weights = (np.arange(1, count + 1, dtype=np.float32) / (count + 1)).reshape((-1,) + (1,) * (outgoing.ndim - 1))
    blended = outgoing.astype(np.float32) * (1 - weights) + incoming.astype(np.float32) * weights
    return np.clip(np.rint(blended), 0, 255).astype(np.uint8)
