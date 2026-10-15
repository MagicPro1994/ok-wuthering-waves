import math
from typing import List, Optional, Tuple

import cv2
import numpy as np

from src.fishing.detect import MINIMAP_CENTRE, heading_error, plan_route

UNITS_PER_PX = 2.0      # the world raster the bumps are drawn on: 1 minimap-sized pixel = 2 coordinate units
WALL_HALF = 40.0        # a bump is taken to be part of a wall this far to each side of the boat's heading
WALL_AHEAD = 12.0       # ... and this far in front of the boat
WALL_SPACING = 6.0


def _gap(a, b):
    return abs((a - b + 180) % 360 - 180)


def _circular_mean(angles):
    return math.degrees(math.atan2(sum(math.sin(math.radians(a)) for a in angles),
                                   sum(math.cos(math.radians(a)) for a in angles))) % 360


class Navigator:
    """Remembers where the boat was blocked by things the minimap does not show (wrecks, rocks) and steers round them.

    The coordinate readout gives the boat's position in the world. The minimap is north-up but its angles need not
    match the world's (rotated, maybe mirrored), so the mapping is learnt from the way the boat actually moves.
    A boat that stops moving while W is held has hit something: a wall segment is remembered across its heading,
    and `aim` plans a route around everything remembered, so it goes round a wreck once instead of back into it.
    """

    def __init__(self, min_move: float = 10.0, still: float = 4.0, max_samples: int = 40):
        self.min_move, self.still, self.max_samples = min_move, still, max_samples
        self.samples: List[Tuple[float, float]] = []     # (minimap heading, world bearing of the motion)
        self.bumps: List[Tuple[float, float]] = []
        self.side = 1
        self.prev = None
        self.pos = None
        self.last_motion = None
        self.still_reads = 0

    # ---- learning ----------------------------------------------------

    def mapping(self) -> Optional[Tuple[int, float]]:
        """(sign, offset) with world bearing = sign * minimap bearing + offset, or None before the boat has moved.

        With one sample, or samples that disagree, it is a guess from the latest motion (not mirrored); that is
        right for bearings near the heading, which is all a first bump needs.
        """
        if not self.samples:
            return None
        if len(self.samples) < 2:
            return self._latest_guess()
        best = None
        for sign in (1, -1):
            offsets = [(world - sign * heading) % 360 for heading, world in self.samples]
            offset = _circular_mean(offsets)
            spread = abs(sum(complex(math.cos(math.radians(o)), math.sin(math.radians(o))) for o in offsets)) / len(offsets)
            if best is None or spread > best[0] + 0.02:
                best = (spread, sign, offset)
        return (best[1], best[2]) if best[0] >= 0.8 else self._latest_guess()

    def _latest_guess(self):
        heading, motion = self.samples[-1]
        return 1, (motion - heading) % 360

    def _mapping_or_identity(self):
        return self.mapping() or (1, 0.0)

    def to_world(self, minimap_bearing: float) -> float:
        sign, offset = self._mapping_or_identity()
        return (sign * minimap_bearing + offset) % 360

    def to_minimap(self, world_bearing: float) -> float:
        sign, offset = self._mapping_or_identity()
        return (sign * (world_bearing - offset)) % 360

    def update(self, pos, heading, forward: bool = True) -> bool:
        """Feed one position / arrow heading reading. True when the boat has just been judged to hit something."""
        if pos is None or heading is None:
            return False
        if not forward:
            self.prev, self.still_reads = None, 0
            self.pos = pos
            return False
        prev, self.prev, self.pos = self.prev, (pos, heading), pos
        if prev is None:
            return False
        (p0, h0) = prev
        dx, dy = pos[0] - p0[0], pos[1] - p0[1]
        distance = math.hypot(dx, dy)
        if distance >= self.min_move and _gap(h0, heading) <= 40:
            motion = math.degrees(math.atan2(dy, dx)) % 360
            self.samples.append((heading, motion))      # the boat turns first, then sails: the new heading is the one
            self.samples = self.samples[-self.max_samples:]
            self.last_motion = motion
        if distance < self.still:
            self.still_reads += 1
        else:
            self.still_reads = 0
        if self.still_reads >= 2:
            self.still_reads = 0
            return self._bump(pos, heading)
        return False

    def reset_motion(self):
        """Forget the last reading, e.g. after backing off, so the move is not mistaken for a stop."""
        self.prev, self.still_reads = None, 0

    def mark_hit(self, pos, heading):
        """Remember a wall at once, e.g. when the boat took damage at this position and heading."""
        pos = pos or self.pos
        if pos is not None and heading is not None:
            self.pos = pos
            self._bump(pos, heading)

    def _bump(self, pos, heading) -> bool:
        ahead = math.radians(self.to_world(heading))
        along = (math.cos(ahead), math.sin(ahead))
        across = (-along[1], along[0])
        centre = (pos[0] + along[0] * WALL_AHEAD, pos[1] + along[1] * WALL_AHEAD)
        steps = int(WALL_HALF / WALL_SPACING)
        for i in range(-steps, steps + 1):
            self.bumps.append((centre[0] + across[0] * i * WALL_SPACING, centre[1] + across[1] * i * WALL_SPACING))
        return True

    # ---- steering ----------------------------------------------------

    def mask(self) -> np.ndarray:
        """Remembered walls as a world-aligned 260x260 raster centred on the boat (east right, north up)."""
        raster = np.zeros((260, 260), np.uint8)
        if self.pos is None:
            return raster.astype(bool)
        cx, cy = MINIMAP_CENTRE
        for x, y in self.bumps:
            col = cx + (x - self.pos[0]) / UNITS_PER_PX
            row = cy - (y - self.pos[1]) / UNITS_PER_PX
            if -10 <= col < 270 and -10 <= row < 270:
                cv2.circle(raster, (int(round(col)), int(round(row))), 5, 1, -1)
        return raster.astype(bool)

    def aim(self, bearing: float) -> Optional[float]:
        """The minimap bearing to steer for so remembered walls are rounded; None when every way is blocked."""
        if not self.bumps or self.pos is None:
            return bearing
        wall = self.mask()
        if not wall.any():
            return bearing
        route = plan_route(wall, self.to_world(bearing), None, self.side)
        if route.blocked:
            return None
        turned = heading_error(self.to_world(bearing), route.bearing)
        if abs(turned) > 10:
            self.side = 1 if turned > 0 else -1
        return self.to_minimap(route.bearing)
