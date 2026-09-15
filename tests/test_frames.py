import os
from collections.abc import Iterator

import pygame
import pytest

from player.frames import (
    MEMORY_BUDGET_FRACTION,
    JpegStore,
    available_memory_bytes,
    choose_mode,
    decode_jpeg,
    encode_jpeg,
)

GB = 1_000_000_000
FRAME_SIZE = (32, 24)


@pytest.fixture(autouse=True)
def headless_pygame() -> Iterator[None]:
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    yield
    pygame.quit()


def _solid(color: tuple[int, int, int]) -> pygame.Surface:
    surface = pygame.Surface(FRAME_SIZE)
    surface.fill(color)
    return surface


def test_auto_keeps_surfaces_within_budget() -> None:
    assert choose_mode("auto", needed=int(MEMORY_BUDGET_FRACTION * 4 * GB), available=4 * GB) == "surfaces"


def test_auto_falls_back_to_jpeg_over_budget() -> None:
    assert choose_mode("auto", needed=int(MEMORY_BUDGET_FRACTION * 4 * GB) + 1, available=4 * GB) == "jpeg"


def test_auto_keeps_surfaces_when_memory_is_unknown() -> None:
    assert choose_mode("auto", needed=100 * GB, available=None) == "surfaces"


def test_explicit_mode_wins() -> None:
    assert choose_mode("jpeg", needed=1, available=4 * GB) == "jpeg"
    assert choose_mode("surfaces", needed=100 * GB, available=4 * GB) == "surfaces"


def test_available_memory_is_reported() -> None:
    available = available_memory_bytes()
    assert available is None or available > 0


def test_jpeg_round_trip_keeps_size_and_colour() -> None:
    decoded = decode_jpeg(encode_jpeg(_solid((200, 40, 40))))
    assert decoded.get_size() == FRAME_SIZE
    red, green, blue, _ = decoded.get_at((16, 12))
    assert abs(red - 200) < 8 and abs(green - 40) < 8 and abs(blue - 40) < 8


def test_jpeg_store_serves_prepared_and_unprepared_frames() -> None:
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
    store = JpegStore({"main": [encode_jpeg(_solid(color)) for color in colors]})
    try:
        store.prepare(("main", 1))
        assert store.get(("main", 1)).get_at((0, 0))[1] > 200
        store.prepare(("main", 0))
        assert store.get(("main", 2)).get_at((0, 0))[2] > 200  # asked for a different frame than prepared
    finally:
        store.close()
