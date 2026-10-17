import re
from typing import FrozenSet, Iterable, Optional, Set, Tuple

import cv2
import numpy as np

Cell = Tuple[int, int]

GRID_ORIGIN = (896.5, 154.5)    # top-left corner of cell (0, 0), 1920x1080 pixels
CELL_PX = 111.0
GRID_ROWS = 7
GRID_COLS = 8
BLOCKED: FrozenSet[Cell] = frozenset({(0, 0), (0, 7), (6, 0), (6, 7)})
EMPTY_RGB = (52, 52, 52)

# Fish cards on the Catches screen, 1920x1080 pixels. Measured live: the Catch List shows 3 cards per row and 2 rows,
# card 0 is centred at (180, 268), the pitch is (222, 202) and a card is about 210x188 with its value at the bottom left.
# The panel sits at a fixed absolute position. A placed card leaves the list and the others reflow to lower slots.
CARD_ORIGIN = (180.0, 268.0)    # centre of slot 0
CARD_PITCH = (222.0, 202.0)     # (x, y) distance between slot centres
CARD_COLS = 3
CARD_SIZE = (210.0, 188.0)
MAX_CARDS = 6
# The details panel under the list prints the clicked card's price in large type: far easier to read than the card.
PRICE_BOX = (0.30, 0.735, 0.39, 0.78)
CARGO_COUNT_BOX = (0.42, 0.04, 0.56, 0.10)   # the "Cargo: 7/52" counter at the top


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


DIM_RESIDUAL = 15.0     # mean abs error of the "same cell, just dimmed" model above which a cell really changed


def _is_dimmed(before: np.ndarray, after: np.ndarray, row: int, col: int) -> bool:
    """True when `after` is `before` scaled by one factor: a placed fish dimmed while a draft is up."""
    x0, y0, x1, y1 = _interior(row, col)
    b = before[y0:y1, x0:x1].astype(float).reshape(-1, 3)
    a = after[y0:y1, x0:x1].astype(float).reshape(-1, 3)
    denom = (b * b).sum()
    if denom == 0:
        return False
    k = (a * b).sum() / denom
    return float(np.abs(a - k * b).mean()) < DIM_RESIDUAL


def read_draft(before: np.ndarray, after: np.ndarray, occupied: Iterable[Cell]) -> FrozenSet[Cell]:
    """Cells of the draft showing in `after`, against `before` (no draft showing) with `occupied` its placed cells.

    While a draft is up the game dims every placed fish, so those cells change too. An occupied cell only counts when
    the change is more than a dimming (the draft sits on it, tinted); then cells hidden under the fish art are filled in.
    """
    occupied = set(occupied)
    found = set()
    for cell in read_preview(before, after):
        if cell not in occupied or not _is_dimmed(before, after, *cell):
            found.add(cell)
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            if (r, c) in found or (r, c) in BLOCKED:
                continue
            if all(n in found for n in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1))):
                found.add((r, c))
    return frozenset(found)


# The Space confirm button (a green check) only shows while a draft is up. Measured on real frames: about 17% of the box
# has a greenish pixel with a draft and none without, so any cutoff in between works.
CONFIRM_BOX_PX = (1495, 945, 1575, 1025)    # x0, y0, x1, y1 in 1920x1080 pixels
CONFIRM_MIN = 0.04


def draft_active(rgb: np.ndarray) -> bool:
    x0, y0, x1, y1 = CONFIRM_BOX_PX
    patch = rgb[y0:y1, x0:x1].astype(int)
    r, g, b = patch[..., 0], patch[..., 1], patch[..., 2]
    green = (g > 130) & (g - r > 25) & (g - b > 25)
    return bool(green.mean() >= CONFIRM_MIN)


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


def parse_cargo_used(texts: Iterable[str]) -> Optional[int]:
    for text in texts:
        match = re.search(r'(\d+)\s*/\s*52', text)
        if match:
            return int(match.group(1))
    return None


BADGE_OFFSET = (-89.0, -78.0)    # centre of a card's purple request badge from the card's centre, 1920x1080 pixels
BADGE_RADIUS = 14
BADGE_MIN_PX = 60


def request_badge(rgb: np.ndarray, slot: int) -> bool:
    """True when the card in `slot` carries the purple badge of the tracked request (the fish is one it asks for)."""
    cx, cy = card_center(slot)
    x, y = int(cx * 1920 + BADGE_OFFSET[0]), int(cy * 1080 + BADGE_OFFSET[1])
    patch = np.ascontiguousarray(rgb[max(0, y - BADGE_RADIUS):y + BADGE_RADIUS, max(0, x - BADGE_RADIUS):x + BADGE_RADIUS])
    if patch.size == 0:
        return False
    hsv = cv2.cvtColor(patch, cv2.COLOR_RGB2HSV)
    h, sat, v = hsv[..., 0].astype(int), hsv[..., 1].astype(int), hsv[..., 2].astype(int)
    return int(((h >= 125) & (h <= 155) & (sat >= 70) & (v >= 110)).sum()) >= BADGE_MIN_PX
