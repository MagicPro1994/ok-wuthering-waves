import re
from typing import FrozenSet, Iterable, Optional, Set, Tuple

import numpy as np

Cell = Tuple[int, int]

GRID_ORIGIN = (896.5, 154.5)    # top-left corner of cell (0, 0), 1920x1080 pixels
CELL_PX = 111.0
GRID_ROWS = 7
GRID_COLS = 8
BLOCKED: FrozenSet[Cell] = frozenset({(0, 0), (0, 7), (6, 0), (6, 7)})
EMPTY_RGB = (52, 52, 52)

# Fish cards on the Catches screen, 1920x1080 pixels. Layout measured on a live crop of the Catch List: 3 cards per row,
# 222 px across and 202 px down between card centres, each card about 210x190 with its value at the bottom left.
# The panel's absolute position is not known, so slot 0's centre is found at run time from the value texts
# (see calibrate_card_origin); CARD_ORIGIN is only the fallback. Only 2 rows are visible without scrolling.
CARD_ORIGIN = (185.0, 245.0)    # centre of slot 0 (fallback)
CARD_PITCH = (222.0, 202.0)     # (x, y) distance between slot centres
CARD_COLS = 3
CARD_SIZE = (210.0, 190.0)
MAX_CARDS = 6
CARD_REGION = (0.02, 0.12, 0.47, 1.0)   # OCR region of the Catch List
VALUE_TO_CARD = (60.0, -72.0)           # card centre relative to the left edge, vertical centre of its value text


def cell_center(row: int, col: int) -> Tuple[float, float]:
    x = GRID_ORIGIN[0] + (col + 0.5) * CELL_PX
    y = GRID_ORIGIN[1] + (row + 0.5) * CELL_PX
    return x / 1920.0, y / 1080.0


def free_cells(occupied: Iterable[Cell]) -> Set[Cell]:
    every = {(r, c) for r in range(GRID_ROWS) for c in range(GRID_COLS)}
    return every - set(BLOCKED) - set(occupied)


def _interior(row: int, col: int) -> Tuple[int, int, int, int]:
    margin = int(CELL_PX // 4)
    x0 = int(GRID_ORIGIN[0] + col * CELL_PX) + margin
    y0 = int(GRID_ORIGIN[1] + row * CELL_PX) + margin
    x1 = int(GRID_ORIGIN[0] + (col + 1) * CELL_PX) - margin
    y1 = int(GRID_ORIGIN[1] + (row + 1) * CELL_PX) - margin
    return x0, y0, x1, y1


def read_preview(before: np.ndarray, after: np.ndarray, threshold: float = 18.0) -> FrozenSet[Cell]:
    found = set()
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            x0, y0, x1, y1 = _interior(r, c)
            diff = np.abs(before[y0:y1, x0:x1].astype(int) - after[y0:y1, x0:x1].astype(int)).mean()
            if diff > threshold:
                found.add((r, c))
    return frozenset(found)


def occupied_cells(rgb: np.ndarray, threshold: float = 18.0) -> FrozenSet[Cell]:
    empty = np.array(EMPTY_RGB, dtype=int)
    found = set()
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            if (r, c) in BLOCKED:
                continue
            x0, y0, x1, y1 = _interior(r, c)
            diff = np.abs(rgb[y0:y1, x0:x1].astype(int) - empty).mean()
            if diff > threshold:
                found.add((r, c))
    return frozenset(found)


def parse_value(texts: Iterable[str]) -> Optional[int]:
    for text in texts:
        match = re.search(r'\d[\d,]*', text)
        if match:
            return int(match.group().replace(',', ''))
    return None


def card_center(slot: int, origin: Optional[Tuple[float, float]] = None) -> Tuple[float, float]:
    ox, oy = origin or CARD_ORIGIN
    row, col = divmod(slot, CARD_COLS)
    x = ox + col * CARD_PITCH[0]
    y = oy + row * CARD_PITCH[1]
    return x / 1920.0, y / 1080.0


def card_box(slot: int, origin: Optional[Tuple[float, float]] = None) -> Tuple[float, float, float, float]:
    x, y = card_center(slot, origin)
    half_w, half_h = CARD_SIZE[0] / 2 / 1920.0, CARD_SIZE[1] / 2 / 1080.0
    return x - half_w, y - half_h, x + half_w, y + half_h


def calibrate_card_origin(values: Iterable[Tuple[str, float, float]]) -> Optional[Tuple[float, float]]:
    """Slot 0's centre in pixels from the card value texts: (text, left x, centre y) triples, in pixels.

    Every card shows its value at the same spot, so the top-left value text is slot 0's.
    """
    found = [(y, x) for text, x, y in values if re.fullmatch(r'\d[\d,]*', text.strip())]
    if not found:
        return None
    top = min(y for y, _ in found)
    row = [x for y, x in found if y - top < CARD_PITCH[1] / 2]      # same row as the top-most value
    return min(row) + VALUE_TO_CARD[0], top + VALUE_TO_CARD[1]
