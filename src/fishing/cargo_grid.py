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

# Fish cards on the Catches screen, 1920x1080 pixels.
# UNVERIFIED ESTIMATES: cargo_cards.png is not in the repo (it needs the live game), so these
# values were NOT measured. Measure them live from cargo_cards.png and replace them before relying on card_center/card_box.
CARD_ORIGIN = (180.0, 259.0)    # centre of slot 0
CARD_PITCH = (227.0, 190.0)     # (x, y) distance between slot centres
CARD_COLS = 2
CARD_SIZE = (200.0, 170.0)
MAX_CARDS = 12


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


def card_center(slot: int) -> Tuple[float, float]:
    row, col = divmod(slot, CARD_COLS)
    x = CARD_ORIGIN[0] + col * CARD_PITCH[0]
    y = CARD_ORIGIN[1] + row * CARD_PITCH[1]
    return x / 1920.0, y / 1080.0


def card_box(slot: int) -> Tuple[float, float, float, float]:
    x, y = card_center(slot)
    half_w, half_h = CARD_SIZE[0] / 2 / 1920.0, CARD_SIZE[1] / 2 / 1080.0
    return x - half_w, y - half_h, x + half_w, y + half_h
