import heapq
import math
from typing import List, Optional, Tuple

import numpy as np

from src.fishing.detect import MINIMAP_CENTRE

CELL = 6.0              # world units per grid cell
SIZE = 1500             # cells per side: the coordinates the game reads stay well inside 0..9000
UNITS_PER_PX = 0.88     # world units per minimap pixel, measured by registering minimaps against the coordinates; north-up
SEEN_RADIUS = 64        # minimap px around the boat that are trusted; the rim and the arrow are not
SCORE_LIMIT = 6
WALL_SCORE = SCORE_LIMIT

_STEPS = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
          (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414)]


def bearing_of(dx: float, dy_south: float) -> float:
    """Minimap bearing (east 0, north 90, anticlockwise) of a world offset (x east, y south)."""
    return math.degrees(math.atan2(-dy_south, dx)) % 360


class WorldMap:
    """The sea as the minimap showed it, drawn into world coordinates, and a planner over it.

    Every minimap read marks the cells around the boat as land (not open water) or water, so a lagoon that was entered
    once is known to be closed from then on. `plan` finds the cheapest way over the cells known so far, treating
    ground not yet seen as sailable: towards a far target that goes straight until the minimap shows land, and a bay
    that turned out closed is never entered again.
    """

    def __init__(self, cell: float = CELL, size: int = SIZE):
        self.cell, self.size = cell, size
        self.score = np.zeros((size, size), dtype=np.int8)      # >0 land, <0 water, 0 unknown
        self.seen = np.zeros((size, size), dtype=bool)
        self.goal = None        # the frontier cell the last plan went for
        self.last_path = []     # the route planned last time
        self._walled_off = False
        step = max(1, int(round(cell / UNITS_PER_PX / 2)))
        cx, cy = MINIMAP_CENTRE
        ys, xs = np.mgrid[0:260:step, 0:260:step]
        keep = np.hypot(xs - cx, ys - cy) <= SEEN_RADIUS
        self.px_ys, self.px_xs = ys[keep], xs[keep]
        self.off_x = (self.px_xs - cx) * UNITS_PER_PX
        self.off_y = (self.px_ys - cy) * UNITS_PER_PX

    # ---- keeping it -------------------------------------------------

    FORMAT = 1

    def save(self, path) -> None:
        """Keep the map between runs: the sea does not change, so a later run starts out knowing its bays."""
        np.savez_compressed(path, score=self.score, seen=self.seen, cell=self.cell, size=self.size,
                            scale=UNITS_PER_PX, format=self.FORMAT)

    def load(self, path) -> bool:
        """Read a map saved by `save`; False (and nothing changed) when it is missing or was drawn differently."""
        try:
            with np.load(path) as data:
                same = (int(data['format']) == self.FORMAT and float(data['cell']) == self.cell
                        and int(data['size']) == self.size and abs(float(data['scale']) - UNITS_PER_PX) < 1e-9)
                if not same:
                    return False
                self.score, self.seen = data['score'].copy(), data['seen'].copy()
        except (OSError, KeyError, ValueError):
            return False
        return True

    # ---- drawing ----------------------------------------------------

    def _index(self, x, y):
        return (np.floor(np.asarray(y) / self.cell).astype(int), np.floor(np.asarray(x) / self.cell).astype(int))

    def inside(self, row, col):
        return 0 <= row < self.size and 0 <= col < self.size

    def observe(self, danger: np.ndarray, pos: Tuple[float, float]) -> None:
        """Mark what the minimap's danger mask (260x260, True = not open water) shows around `pos`."""
        rows, cols = self._index(pos[0] + self.off_x, pos[1] + self.off_y)
        ok = (rows >= 0) & (rows < self.size) & (cols >= 0) & (cols < self.size)
        rows, cols = rows[ok], cols[ok]
        land = danger[self.px_ys[ok], self.px_xs[ok]]
        # several minimap pixels land in one cell: land wins only when most of them say so
        votes = np.zeros((self.size, self.size), dtype=np.int16)
        np.add.at(votes, (rows, cols), np.where(land, 1, -1))
        touched = np.zeros((self.size, self.size), dtype=bool)
        touched[rows, cols] = True
        delta = np.sign(votes).astype(np.int16)
        new = self.score.astype(np.int16) + delta * touched
        # a wall that was bumped into stays: only a bump is allowed to sit at the limit
        self.score = np.clip(new, -SCORE_LIMIT + 1, SCORE_LIMIT).astype(np.int8) \
            if not (self.score == WALL_SCORE).any() else self._merge_walls(new)
        self.seen |= touched

    def _merge_walls(self, new):
        walls = self.score == WALL_SCORE
        out = np.clip(new, -SCORE_LIMIT + 1, SCORE_LIMIT - 1)
        out[walls] = WALL_SCORE
        return out.astype(np.int8)

    def new_trip(self) -> None:
        """A fresh sail: nothing planned before applies, and the walls bumped into last time may have been misread."""
        self.goal, self.last_path = None, []
        self.clear_walls()

    def clear_walls(self) -> None:
        """Forget the walls bumped into (they may have been a misreading); what the minimap showed stays."""
        self.score[self.score == WALL_SCORE] = 0

    def mark_wall(self, pos: Tuple[float, float], world_bearing: float, ahead: float = 14.0, half: float = 36.0,
                  spacing: float = 5.0) -> None:
        """Something the minimap does not show stopped the boat: a wall across its heading, `ahead` units in front."""
        a = math.radians(world_bearing)
        along = (math.cos(a), math.sin(a))
        across = (-along[1], along[0])
        centre = (pos[0] + along[0] * ahead, pos[1] + along[1] * ahead)
        for i in range(-int(half / spacing), int(half / spacing) + 1):
            row, col = self._index(centre[0] + across[0] * i * spacing, centre[1] + across[1] * i * spacing)
            if self.inside(row, col):
                self.score[row, col] = WALL_SCORE

    # ---- planning ---------------------------------------------------

    def land_at(self, x: float, y: float) -> bool:
        row, col = self._index(x, y)
        return self.inside(row, col) and self.score[row, col] > 0

    MARGINS = (18.0, 10.0, 5.0)     # clearance from land tried in turn when the target is walled off at the first

    def plan(self, pos: Tuple[float, float], target: Tuple[float, float], margin: float = 28.0, half: float = 300.0,
             prefer: int = 1, lookahead: float = 60.0) -> 'Plan':
        """Cheapest way from `pos` to `target` (world units) over the map; unseen cells count as sailable.

        The search runs on a window around the boat. A target beyond the window is replaced by the cheapest cell
        on its rim, measured as path length plus the straight distance left to the target. A target in a harbour or
        behind a narrow channel, seen on the map but walled off by the clearance kept from land, is tried again with
        less and less clearance.
        """
        result = self._plan(pos, target, margin, half, prefer, lookahead)
        if not self._walled_off:
            return result
        for tighter in self.MARGINS:
            if tighter >= margin:
                continue
            result = self._plan(pos, target, tighter, half, prefer, lookahead)
            if not self._walled_off:
                break
        return result

    def _plan(self, pos, target, margin, half, prefer, lookahead) -> 'Plan':
        cell = self.cell
        r0, c0 = self._index(pos[0], pos[1])
        n = int(half / cell)
        lo_r, hi_r = max(0, r0 - n), min(self.size, r0 + n + 1)
        lo_c, hi_c = max(0, c0 - n), min(self.size, c0 + n + 1)
        win = self.score[lo_r:hi_r, lo_c:hi_c] > 0
        grow = int(math.ceil(margin / cell))
        hard = _dilate(win, max(1, grow // 2))              # too close to land to sail through
        blocked = hard
        soft = _dilate(win, grow) & ~hard                   # room enough, but the open sea is preferred
        h, w = blocked.shape
        start = (r0 - lo_r, c0 - lo_c)
        near_start = (slice(max(0, start[0] - grow), start[0] + grow + 1), slice(max(0, start[1] - grow), start[1] + grow + 1))
        blocked[near_start] = win[near_start]       # the boat may start inside the clearance, never inside land
        unseen = ~self.seen[lo_r:hi_r, lo_c:hi_c]

        # cell centre coordinates of the window
        rows, cols = np.mgrid[0:h, 0:w]
        wx = (cols + lo_c + 0.5) * cell
        wy = (rows + lo_r + 0.5) * cell
        left = np.hypot(wx - target[0], wy - target[1])

        tx, ty = target[0] - pos[0], target[1] - pos[1]
        side_x, side_y = -ty, tx
        wrong = ((wx - pos[0]) * side_x + (wy - pos[1]) * side_y) * prefer < 0 if prefer else np.zeros((h, w), bool)
        factor = np.where(unseen, 1.25, 1.0) * np.where(wrong, 1.04, 1.0) * np.where(soft, 1.5, 1.0)
        if self.last_path:
            # the way planned last time is a little cheaper, so new sightings do not swing the route from side to side
            import cv2
            near = np.zeros((h, w), np.uint8)
            pts = np.array([[(x / cell) - lo_c, (y / cell) - lo_r] for x, y in self.last_path], np.float32)
            cv2.polylines(near, [np.round(pts).astype(np.int32)], False, 1, thickness=max(1, int(round(24 / cell))))
            factor = factor * np.where(near > 0, 0.88, 1.0)
        flat_blocked = blocked.ravel().tolist()
        flat_factor = (factor * cell).ravel().tolist()
        dist = [math.inf] * (h * w)
        parent = {}
        s_idx = start[0] * w + start[1]
        dist[s_idx] = 0.0
        queue = [(0.0, s_idx)]
        moves = [(dr * w + dc, dr, dc, length) for dc, dr, length in _STEPS]
        while queue:
            cost, idx = heapq.heappop(queue)
            if cost > dist[idx]:
                continue
            r, c = divmod(idx, w)
            for off, dr, dc, length in moves:
                nr, nc = r + dr, c + dc
                if not (0 <= nr < h and 0 <= nc < w):
                    continue
                n_idx = idx + off
                if flat_blocked[n_idx]:
                    continue
                if dr and dc and (flat_blocked[idx + dc] or flat_blocked[idx + dr * w]):
                    continue
                new_cost = cost + length * flat_factor[n_idx]
                if new_cost < dist[n_idx]:
                    dist[n_idx] = new_cost
                    parent[n_idx] = idx
                    heapq.heappush(queue, (new_cost, n_idx))
        best = np.array(dist).reshape(h, w)
        reached = np.isfinite(best)
        # goals are cells at the edge of what is known (or the window's rim), not any cell: the end of a bay that is
        # known to be closed lies nearer to the target than the way round, but leads nowhere
        edge = reached & (_dilate(unseen, 1) | _border(h, w))
        weight = np.ones((h, w))
        tr, tc = int(target[1] // cell) - lo_r, int(target[0] // cell) - lo_c
        self._walled_off = False
        if 0 <= tr < h and 0 <= tc < w:
            if reached[tr, tc]:
                edge[tr, tc] = True
            else:
                # a fish spot sits by an islet more often than not: its own cell lies inside the clearance kept from
                # land and cannot be reached, so the reachable cells close to it are the goal instead
                near = reached & (left <= 2 * margin)
                edge |= near
                weight = np.where(near, 4.0, 1.0)       # the closest of them wins, not the first one the boat gets to
                self._walled_off = bool(self.seen[tr + lo_r, tc + lo_c]) and not near.any()
        if not edge.any():
            edge = reached
        score = np.where(edge, best + left * weight, np.inf)
        end = np.unravel_index(int(np.argmin(score)), score.shape)
        end = (int(end[0]), int(end[1]))
        # stick to the goal chosen last time unless another is clearly better, or the boat flips between two
        if self.goal is not None:
            gr, gc = int(self.goal[1] // cell) - lo_r, int(self.goal[0] // cell) - lo_c
            if 0 <= gr < h and 0 <= gc < w and np.isfinite(score[gr, gc]) and score[gr, gc] <= score[end] * 1.35:
                end = (gr, gc)
        self.goal = ((end[1] + lo_c + 0.5) * cell, (end[0] + lo_r + 0.5) * cell)
        path: List[Tuple[float, float]] = []
        node = end[0] * w + end[1]
        while node != s_idx:
            r, c = divmod(node, w)
            path.append(((c + lo_c + 0.5) * cell, (r + lo_r + 0.5) * cell))
            node = parent[node]
        path.append((pos[0], pos[1]))
        path.reverse()
        self.last_path = list(path)
        closed = bool(np.isfinite(best).sum() < 12)
        return Plan(path=path, blocked=closed, cost=float(best[end]), left=float(left[end]),
                    waypoint=self._pull(path, blocked, (lo_r, lo_c), lookahead))

    def _pull(self, path, blocked, origin, lookahead):
        """String-pulling: the farthest path point within `lookahead` that is in a clear straight line."""
        lo_r, lo_c = origin
        cell = self.cell

        def clear(a, b):
            steps = int(math.hypot(b[0] - a[0], b[1] - a[1]) / (cell / 2)) + 1
            for i in range(steps + 1):
                x = a[0] + (b[0] - a[0]) * i / steps
                y = a[1] + (b[1] - a[1]) * i / steps
                r, c = int(y // cell) - lo_r, int(x // cell) - lo_c
                if not (0 <= r < blocked.shape[0] and 0 <= c < blocked.shape[1]) or blocked[r, c]:
                    return False
            return True

        here = path[0]
        pick = path[1] if len(path) > 1 else path[0]
        for point in path[1:]:
            if math.hypot(point[0] - here[0], point[1] - here[1]) > lookahead:
                break
            if clear(here, point):
                pick = point
        return pick


class Plan:
    def __init__(self, path, blocked, cost, left, waypoint):
        self.path, self.blocked, self.cost, self.left, self.waypoint = path, blocked, cost, left, waypoint

    def bearing(self, pos) -> float:
        """Minimap bearing of the next waypoint seen from `pos`."""
        return bearing_of(self.waypoint[0] - pos[0], self.waypoint[1] - pos[1])


def _border(h: int, w: int) -> np.ndarray:
    ring = np.zeros((h, w), dtype=bool)
    ring[0, :] = ring[-1, :] = ring[:, 0] = ring[:, -1] = True
    return ring


def _dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    if radius <= 0 or not mask.any():
        return mask.copy()
    import cv2
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
    return cv2.dilate(mask.astype(np.uint8), kernel) > 0


class TargetTracker:
    """Where the request icon is in the world, from the minimap.

    Inside the disc the icon gives the spot exactly. At the rim only its bearing is true, so bearings seen from
    different places are intersected (least squares); with no baseline yet the target is taken far along the bearing.
    """

    EDGE = 74.0             # minimap px: an icon farther out sits clamped at the rim

    def __init__(self):
        self.rays: List[Tuple[float, float, float, float]] = []     # x, y, unit direction
        self.exact: Optional[Tuple[float, float]] = None
        self.far = 1500.0

    def reset(self):
        self.rays, self.exact = [], None

    def observe(self, pos, bearing: Optional[float], radius: Optional[float]):
        if bearing is None or radius is None:
            return
        b = math.radians(bearing)
        ux, uy = math.cos(b), -math.sin(b)
        if radius < self.EDGE:
            self.exact = (pos[0] + ux * radius * UNITS_PER_PX, pos[1] + uy * radius * UNITS_PER_PX)
            return
        self.exact = None
        if self.rays and math.hypot(pos[0] - self.rays[-1][0], pos[1] - self.rays[-1][1]) < 12:
            return
        self.rays.append((pos[0], pos[1], ux, uy))
        self.rays = self.rays[-12:]

    def estimate(self, pos, bearing: Optional[float]) -> Optional[Tuple[float, float]]:
        if self.exact is not None:
            return self.exact
        if bearing is None:
            return None
        b = math.radians(bearing)
        fallback = (pos[0] + math.cos(b) * self.far, pos[1] - math.sin(b) * self.far)
        if len(self.rays) < 2:
            return fallback
        # point closest to every ray: minimise the squared distances to the lines
        a = np.zeros((2, 2))
        rhs = np.zeros(2)
        for x, y, ux, uy in self.rays:
            proj = np.eye(2) - np.outer((ux, uy), (ux, uy))
            a += proj
            rhs += proj @ (x, y)
        if abs(np.linalg.det(a)) < 0.05:
            return fallback
        point = np.linalg.solve(a, rhs)
        # the target must lie ahead of the latest ray; else the rays are nearly parallel and the answer is noise
        x, y, ux, uy = self.rays[-1]
        ahead = (point[0] - x) * ux + (point[1] - y) * uy
        if ahead < 20 or ahead > 4000:
            return fallback
        return float(point[0]), float(point[1])
