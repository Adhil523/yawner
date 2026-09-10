"""Review images drawn with OpenCV: contact sheets, difference strips, line plots.

Images are BGR uint8 (OpenCV's channel order) throughout.
"""

from pathlib import Path

import cv2
import numpy as np

BGR = tuple[int, int, int]

BACKGROUND: BGR = (32, 32, 32)
TEXT: BGR = (235, 235, 235)
GRID: BGR = (70, 70, 70)
FONT = cv2.FONT_HERSHEY_SIMPLEX
PADDING = 4
BAR_HEIGHT = 8


def rgb_to_bgr(frames: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(frames[..., ::-1])


def save_png(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), image):
        raise OSError(f"could not write {path}")


def label(image: np.ndarray, text: str, origin: tuple[int, int], scale: float = 0.45) -> None:
    (width, height), baseline = cv2.getTextSize(text, FONT, scale, 1)
    x, y = origin
    cv2.rectangle(image, (x, y), (x + width + 6, y + height + baseline + 4), (0, 0, 0), thickness=-1)
    cv2.putText(image, text, (x + 3, y + height + 2), FONT, scale, TEXT, 1, cv2.LINE_AA)


def contact_sheet(tiles: np.ndarray, labels: list[str], bar_colors: list[BGR], columns: int) -> np.ndarray:
    """Grid of BGR tiles, each labelled, with a coloured bar underneath (e.g. which segment it's in)."""
    if not len(tiles) == len(labels) == len(bar_colors):
        raise ValueError("tiles, labels and bar_colors must have the same length")
    count, tile_height, tile_width = tiles.shape[:3]
    rows = -(-count // columns)
    cell_height = tile_height + BAR_HEIGHT
    sheet = np.full(
        (PADDING + rows * (cell_height + PADDING), PADDING + columns * (tile_width + PADDING), 3),
        BACKGROUND, dtype=np.uint8,
    )
    for index, (tile, text, color) in enumerate(zip(tiles, labels, bar_colors)):
        row, column = divmod(index, columns)
        y = PADDING + row * (cell_height + PADDING)
        x = PADDING + column * (tile_width + PADDING)
        sheet[y:y + tile_height, x:x + tile_width] = tile
        sheet[y + tile_height:y + cell_height, x:x + tile_width] = color
        label(sheet, text, (x + 2, y + 2))
    return sheet


def stack_vertical(images: list[np.ndarray]) -> np.ndarray:
    """Stack images top to bottom, padding narrower ones on the right."""
    width = max(image.shape[1] for image in images)
    padded = [
        np.hstack([image, np.full((image.shape[0], width - image.shape[1], 3), BACKGROUND, dtype=np.uint8)])
        if image.shape[1] < width else image
        for image in images
    ]
    return np.vstack(padded)


def difference_strip(first: np.ndarray, second: np.ndarray, gain: float, labels: tuple[str, str, str]) -> np.ndarray:
    """first | second | amplified grayscale |first - second|, side by side."""
    difference = cv2.absdiff(cv2.cvtColor(first, cv2.COLOR_BGR2GRAY), cv2.cvtColor(second, cv2.COLOR_BGR2GRAY))
    amplified = np.clip(difference.astype(np.float32) * gain, 0, 255).astype(np.uint8)
    strip = np.hstack([first, second, cv2.cvtColor(amplified, cv2.COLOR_GRAY2BGR)])
    for index, text in enumerate(labels):
        label(strip, text, (index * first.shape[1] + 4, 4))
    return strip


def line_plot(
    series: list[tuple[str, np.ndarray, BGR]],
    hlines: list[tuple[str, float, BGR]],
    vlines: list[tuple[str, int, BGR]],
    fps: float,
    size: tuple[int, int] = (1200, 400),
) -> np.ndarray:
    """Per-frame values against frame index, with a grid line every second."""
    width, height = size
    left, right, top, bottom = 50, 20, 30, 40
    plot_width, plot_height = width - left - right, height - top - bottom
    frame_count = max(len(values) for _, values, _ in series)
    y_max = max(float(np.max(values)) for _, values, _ in series) * 1.1 or 1.0
    image = np.full((height, width, 3), BACKGROUND, dtype=np.uint8)

    def to_x(index: float) -> int:
        return int(left + index * plot_width / max(1, frame_count - 1))

    def to_y(value: float) -> int:
        return int(top + plot_height - value * plot_height / y_max)

    for index in range(0, frame_count, max(1, round(fps))):
        cv2.line(image, (to_x(index), top), (to_x(index), top + plot_height), GRID, 1)
        cv2.putText(image, str(index), (to_x(index) - 10, height - bottom + 18), FONT, 0.4, TEXT, 1, cv2.LINE_AA)
    for fraction in (0.0, 0.5, 1.0):
        value = y_max * fraction
        cv2.putText(image, f"{value:.2f}", (4, to_y(value) + 4), FONT, 0.4, TEXT, 1, cv2.LINE_AA)
    cv2.putText(image, "frame", (width - right - 45, height - 6), FONT, 0.4, TEXT, 1, cv2.LINE_AA)

    for label, value, color in hlines:
        cv2.line(image, (left, to_y(value)), (left + plot_width, to_y(value)), color, 1, cv2.LINE_AA)
        cv2.putText(image, label, (left + plot_width - 90, to_y(value) - 4), FONT, 0.4, color, 1, cv2.LINE_AA)
    for label, index, color in vlines:
        cv2.line(image, (to_x(index), top), (to_x(index), top + plot_height), color, 2)
        cv2.putText(image, f"{label} {index}", (to_x(index) + 4, top + 14), FONT, 0.4, color, 1, cv2.LINE_AA)
    for position, (label, values, color) in enumerate(series):
        points = np.array([[to_x(i), to_y(float(v))] for i, v in enumerate(values)], dtype=np.int32)
        cv2.polylines(image, [points], isClosed=False, color=color, thickness=1, lineType=cv2.LINE_AA)
        cv2.putText(image, label, (left + 8 + position * 110, 18), FONT, 0.45, color, 1, cv2.LINE_AA)
    return image
