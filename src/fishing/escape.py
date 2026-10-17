import math
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np

from src.fishing.detect import MINIMAP_CENTRE

POCKET_SECONDS = 45.0       # no further than POCKET_SPAN from where it was this long ago: the boat is in a pocket
POCKET_SPAN = 85.0          # world units (about metres)
ESCAPE_LEG = 130.0          # world units to aim for when leaving a pocket
FREE_REACH = 70.0           # minimap px that are looked at along each candidate direction

Point = Tuple[float, float]


def world_step(bearing: float, length: float) -> Point:
    """World (x east, y south) offset of `length` along a minimap bearing (east 0, north 90, anticlockwise)."""
    rad = math.radians(bearing)
    return math.cos(rad) * length, -math.sin(rad) * length


def in_pocket(trail: Sequence[Tuple[float, float, float]], now: float) -> bool:
    """True when the last POCKET_SECONDS of (time, x, y) samples all lie within a POCKET_SPAN box."""
    recent = [(x, y) for t, x, y in trail if now - t <= POCKET_SECONDS]
    old_enough = any(now - t >= POCKET_SECONDS * 0.9 for t, _, _ in trail)
    if len(recent) < 12 or not old_enough:
        return False
    xs, ys = zip(*recent)
    return max(xs) - min(xs) < POCKET_SPAN and max(ys) - min(ys) < POCKET_SPAN


def free_length(mask: np.ndarray, bearing: float, reach: float = FREE_REACH) -> float:
    """Minimap px from the boat along `bearing` before land (or the edge of the disc)."""
    cx, cy = MINIMAP_CENTRE
    dx, dy = math.cos(math.radians(bearing)), -math.sin(math.radians(bearing))
    for step in range(4, int(reach) + 1, 2):
        x, y = int(round(cx + dx * step)), int(round(cy + dy * step))
        if not (0 <= x < mask.shape[1] and 0 <= y < mask.shape[0]) or mask[y, x]:
            return float(step)
    return reach


def pick_escape(mask: np.ndarray, here: Point, visited: Iterable[Point], step_deg: int = 15) -> float:
    """Bearing to sail out of a pocket: long open water on the minimap, towards ground the boat has not been on."""
    visited = list(visited)
    best, best_score = 0.0, -1e9
    for bearing in range(0, 360, step_deg):
        free = free_length(mask, bearing) / FREE_REACH
        dx, dy = world_step(bearing, ESCAPE_LEG)
        goal = (here[0] + dx, here[1] + dy)
        seen = sum(1 for x, y in visited if math.hypot(x - goal[0], y - goal[1]) < 60.0)
        score = free - 0.08 * min(seen, 20)
        if score > best_score:
            best, best_score = float(bearing), score
    return best
