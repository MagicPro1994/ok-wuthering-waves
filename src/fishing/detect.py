import heapq
import re
from collections import namedtuple
from typing import Iterable, Optional, Tuple

import cv2
import numpy as np

FULL_HEARTS_PX = 5633
MAX_HEARTS = 8
_PROGRESS = re.compile(r'\(\s*(\d+)\s*/\s*(\d+)\s*\)')


def find_marker(rgb: np.ndarray) -> Optional[Tuple[float, float, int]]:
    """Round purple fish marker in the 3D view, as (x, y, area) in 1920x1080 pixels."""
    r, g, b = [rgb[..., i].astype(int) for i in range(3)]
    mask = ((r > 110) & (r < 200) & (b > 150) & (g < 110) & (b - g > 70)).astype(np.uint8)
    mask[:430, :340] = 0      # minimap and quest tracker
    mask[0:140, :] = 0        # top bar
    mask[600:, 1560:] = 0     # bottom-right action icons
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    count, _, stats, centroids = cv2.connectedComponentsWithStats(mask)
    best = None
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if 250 < area < 1500 and 0.75 < w / h < 1.33 and area / (w * h) > 0.55:
            if best is None or area > best[2]:
                best = (float(centroids[i][0]), float(centroids[i][1]), int(area))
    return best


def heart_px(rgb: np.ndarray) -> int:
    row = rgb[1000:1030, 680:1200].astype(int)
    r, g, b = row[..., 0], row[..., 1], row[..., 2]
    return int(((r > 200) & (g < 80) & (b < 90)).sum())


def hearts_from_px(px: int, full_px: int = FULL_HEARTS_PX, max_hearts: int = MAX_HEARTS) -> int:
    return max(0, min(max_hearts, round(px * max_hearts / full_px)))


def hearts_state(px: int, full_px: int = FULL_HEARTS_PX) -> str:
    """'hidden' when almost no heart pixels show (a menu covers the HUD), 'low' at 2 hearts or fewer, else 'ok'."""
    if px < full_px * 0.02:
        return 'hidden'
    return 'low' if hearts_from_px(px, full_px) <= 2 else 'ok'


def marker_error_deg(marker_x: float, centre_x: float = 960.0, px_per_deg: float = 21.0) -> float:
    return (marker_x - centre_x) / px_per_deg


MINIMAP_CENTRE = (130.0, 121.0)     # 1920x1080 frame; the player arrow sits at the minimap centre


def _angle(dx: float, dy_down: float) -> float:
    """Screen angle in degrees: east 0, north 90, anticlockwise positive."""
    return float(np.degrees(np.arctan2(-dy_down, dx)) % 360)


def arrow_heading(rgb: np.ndarray) -> Optional[float]:
    """Boat heading from the yellow minimap arrow: its narrow end is the tip."""
    cx, cy = MINIMAP_CENTRE
    r, g, b = [rgb[:260, :260, i].astype(int) for i in range(3)]
    yy, xx = np.mgrid[0:260, 0:260]
    mask = (r > 200) & (g > 150) & (b < 130) & (r - b > 110) & (np.hypot(xx - cx, yy - cy) < 40)
    ys, xs = np.nonzero(mask)
    if len(xs) < 40:
        return None
    pts = np.stack([xs - xs.mean(), -(ys - ys.mean())], 1).astype(float)
    axis = np.linalg.eigh(np.cov(pts.T))[1][:, 1]
    along = pts @ axis
    lo, hi = along.min(), along.max()
    side = np.array([-axis[1], axis[0]])

    def width(sel):
        perp = pts[sel] @ side
        return perp.max() - perp.min() if sel.any() else 0.0

    tip = axis if width(along > hi - 0.25 * (hi - lo)) < width(along < lo + 0.25 * (hi - lo)) else -axis
    return _angle(tip[0], -tip[1])


ICON_MIN_PX = 8      # the icon shrinks inside 50 m; the full size is about 250 px


def _target_icon(rgb: np.ndarray) -> Optional[Tuple[float, float]]:
    """Centre of the purple request icon on the minimap, relative to the arrow, or None when it is not shown.

    The minimap is translucent, so the icon's purple shifts with the scenery under it: it is picked by hue, not
    by a fixed RGB window. The biggest blob is taken, so purple coral at the rim does not pull the centre aside.
    """
    cx, cy = MINIMAP_CENTRE
    hsv = cv2.cvtColor(np.ascontiguousarray(rgb[:260, :260]), cv2.COLOR_RGB2HSV)
    h, s, v = [hsv[..., i].astype(int) for i in range(3)]
    yy, xx = np.mgrid[0:260, 0:260]
    mask = ((h >= 122) & (h <= 150) & (s >= 60) & (v >= 110) & (np.hypot(xx - cx, yy - cy) < 92)).astype(np.uint8)
    if mask.sum() < ICON_MIN_PX:
        return None
    # the white fish inside the icon splits it: join the pieces before picking the biggest blob
    count, labels, _, _ = cv2.connectedComponentsWithStats(cv2.dilate(mask, np.ones((5, 5), np.uint8)))
    sizes = np.bincount(labels[mask > 0], minlength=count)
    sizes[0] = 0
    best = int(np.argmax(sizes))
    if sizes[best] < ICON_MIN_PX:
        return None
    ys, xs = np.nonzero((labels == best) & (mask > 0))
    return xs.mean() - cx, ys.mean() - cy


def minimap_target_bearing(rgb: np.ndarray) -> Optional[float]:
    """Bearing of the purple request icon on the minimap, seen from the player arrow."""
    icon = _target_icon(rgb)
    return None if icon is None else _angle(*icon)


def minimap_target_radius(rgb: np.ndarray) -> Optional[float]:
    """Distance of the request icon from the arrow in minimap pixels; a far target sits at the rim."""
    icon = _target_icon(rgb)
    return None if icon is None else float(np.hypot(*icon))


def _minimap_grid():
    cx, cy = MINIMAP_CENTRE
    yy, xx = np.mgrid[0:260, 0:260]
    return np.hypot(xx - cx, yy - cy), np.degrees(np.arctan2(-(yy - cy), xx - cx)) % 360


WATER_RGB = np.array([16.0, 46.0, 60.0])    # open water on the minimap is this colour in every scene (spread about 3)
# The view cone blends the minimap towards white, most near the arrow and fading out to the rim. Open water under
# it follows this share (measured over many frames at these minimap radii), so the cone is not mistaken for land.
CONE_RADII = np.array([0.0, 22.0, 30.0, 38.0, 46.0, 54.0, 62.0, 80.0])
CONE_BLEND = np.array([0.24, 0.236, 0.22, 0.196, 0.17, 0.138, 0.092, 0.05])
CONE_HALF = 32.0                            # half the angle the cone spans
LAND_STEP = 16.0                            # colour distance from open water that counts as not water
CONE_LAND_STEP = 26.0                       # the same under the cone, where the blend itself varies a little


def _cone_water(rad: np.ndarray, water: np.ndarray) -> np.ndarray:
    blend = np.interp(rad, CONE_RADII, CONE_BLEND)[..., None]
    return water * (1 - blend) + 255.0 * blend


def _edge_samples(delta: float):
    angles = np.radians(np.arange(360))[:, None] + np.radians(delta) + 0 * CONE_EDGE_RADII[None, :]
    cx, cy = MINIMAP_CENTRE
    xs = cx + CONE_EDGE_RADII[None, :] * np.cos(angles)
    ys = cy - CONE_EDGE_RADII[None, :] * np.sin(angles)
    return xs.astype(np.float32), ys.astype(np.float32)


CONE_EDGE_RADII = np.arange(26, 63, 3.0)
_EDGE_CCW = _edge_samples(3.0)
_EDGE_CW = _edge_samples(-3.0)
CONE_EDGE_MIN = 45.0


def find_cone(rgb: np.ndarray) -> Optional[float]:
    """Minimap angle the view cone points to, or None when its edges do not show.

    The cone is a bright wedge with straight edges through the arrow, and the step in brightness across each edge
    is the same whatever lies beneath (water or land), unlike a land coast, which never lines up on the arrow.
    """
    green = cv2.GaussianBlur(rgb[:260, :260, 1].astype(np.float32), (3, 3), 0)
    ccw = cv2.remap(green, _EDGE_CCW[0], _EDGE_CCW[1], cv2.INTER_LINEAR)
    cw = cv2.remap(green, _EDGE_CW[0], _EDGE_CW[1], cv2.INTER_LINEAR)
    step = np.median(ccw - cw, axis=1)          # brighter on the CCW side of the angle: the cone starts there
    centres = np.arange(360)
    score = step[np.round(centres - CONE_HALF).astype(int) % 360] - step[np.round(centres + CONE_HALF).astype(int) % 360]
    best = int(np.argmax(score))
    return float(best) if score[best] >= CONE_EDGE_MIN else None


class _ConeMemory:
    angle: Optional[float] = None       # where the cone pointed last time it could be seen; the camera turns slowly


def minimap_danger(rgb: np.ndarray) -> np.ndarray:
    """Pixels of the minimap that are not open water (land, shallows, structures), as a 260x260 mask.

    Open water is one flat colour, and under the view cone another that is known too, so land is whatever differs
    from them: the cone is told apart by its wedge (found from the picture), and the soft band along its two
    edges is left out rather than guessed.
    """
    a = rgb[:260, :260].astype(float)
    rad, ang = _minimap_grid()
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    yellow = (r > 180) & (g > 130) & (b < 140)
    purple = (r > 100) & (b > 130) & (g < 120) & (b - g > 40)
    white = (r > 190) & (g > 190) & (b > 190)
    over = cv2.dilate((yellow | purple | white).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    ring = (rad > 12) & (rad < 68) & ~over
    near = ring & (np.abs(a - WATER_RGB).sum(2) < 14)
    water = np.median(a[near], axis=0) if near.sum() > 150 else WATER_RGB
    plain_gap = np.abs(a - water).sum(2)
    cone_gap = np.abs(a - _cone_water(rad, water)).sum(2)
    centre = find_cone(rgb)
    if centre is None:
        centre = _ConeMemory.angle      # land under the whole cone hides it: it points where it did
    else:
        _ConeMemory.angle = centre
    if centre is None:
        bad = plain_gap > LAND_STEP
        in_band = np.zeros_like(bad)
    else:
        off = np.abs((ang - centre + 180) % 360 - 180)
        inside = off <= CONE_HALF - 4
        in_band = (off > CONE_HALF - 4) & (off < CONE_HALF + 4)
        bad = np.where(inside, cone_gap > CONE_LAND_STEP, plain_gap > LAND_STEP)
    bad = bad & ~in_band & ~over & (rad < 68)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    return cv2.morphologyEx(bad.astype(np.uint8), cv2.MORPH_OPEN, kernel) > 0


def sector_danger(mask: np.ndarray, bearing: float, half_width: float = 15.0) -> float:
    """Share of the wedge around a bearing (minimap angle, east 0 anticlockwise) that is not open water."""
    rad, ang = _minimap_grid()
    wedge = (rad > 20) & (rad < 74) & (np.abs((ang - bearing + 180) % 360 - 180) <= half_width)
    return float(mask[wedge].mean()) if wedge.any() else 0.0


Route = namedtuple('Route', 'bearing blocked path')

_STEPS = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
          (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414)]


def plan_route(mask: np.ndarray, bearing: float, radius: Optional[float], prefer: int = 1, reach: float = 72.0,
               margin: int = 10, cell: int = 4, lookahead: float = 36.0) -> Route:
    """Route over the whole minimap disc to the request icon, as the bearing to steer, a blocked flag and the path.

    Land is grown by `margin` px so the boat keeps clear of it, then the cheapest path from the boat is searched
    on a coarse grid. Where the icon lies beyond the disc (`radius` None or past `reach`) the goal is the edge of
    what is visible: a bay that is closed on the far side is never a goal, only a cell on the rim is, so the boat
    goes round it instead of into it. `prefer` (+1 anticlockwise, -1 clockwise) breaks ties towards the side
    already being rounded. `path` is a list of minimap (x, y) pixels.
    """
    cx, cy = MINIMAP_CENTRE
    grown = cv2.dilate(mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * margin + 1,) * 2))
    size = 260 // cell
    centre = (int(cx // cell), int(cy // cell))
    ys, xs = np.mgrid[0:size, 0:size]
    px, py = xs * cell + cell / 2, ys * cell + cell / 2
    dist = np.hypot(px - cx, py - cy)
    free = (grown[(py).astype(int), (px).astype(int)] == 0) & (dist <= reach)
    free[dist <= margin] = True                      # the boat's own surroundings are never an obstacle
    tx, ty = np.cos(np.radians(bearing)), np.sin(np.radians(bearing))
    inside = radius is not None and radius <= reach
    goal = (cx + tx * radius, cy - ty * radius) if inside else (cx + tx * 1000.0, cy - ty * 1000.0)
    away = np.hypot(px - goal[0], py - goal[1])      # straight-line distance of every cell to the icon
    side = tx * (cy - py) - ty * (px - cx)           # >0: anticlockwise of the bearing

    best = np.full((size, size), np.inf)
    parent = {}
    best[centre[1], centre[0]] = 0.0
    queue = [(0.0, centre)]
    while queue:
        cost, (x, y) = heapq.heappop(queue)
        if cost > best[y, x]:
            continue
        for dx, dy, length in _STEPS:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < size and 0 <= ny < size) or not free[ny, nx]:
                continue
            if dx and dy and not (free[y, nx] and free[ny, x]):
                continue                             # no squeezing diagonally between two bits of land
            wrong_side = side[ny, nx] * prefer < 0
            step = length * cell * (1.12 if wrong_side else 1.0)
            if cost + step < best[ny, nx]:
                best[ny, nx] = cost + step
                parent[(nx, ny)] = (x, y)
                heapq.heappush(queue, (cost + step, (nx, ny)))

    reached = np.isfinite(best)
    rim = reached & (dist >= reach - 1.5 * cell)
    target_cell = None
    if inside:
        tcx, tcy = int(goal[0] // cell), int(goal[1] // cell)
        if 0 <= tcx < size and 0 <= tcy < size and reached[tcy, tcx]:
            target_cell = (tcx, tcy)
    if target_cell is not None:
        end = target_cell
    else:
        pool = rim if rim.any() else reached
        # detour = what the path costs beyond open water; the grid's own diagonal rounding must not pick the goal
        gx, gy = np.abs(xs - centre[0]), np.abs(ys - centre[1])
        detour = best - cell * (np.maximum(gx, gy) + 0.414 * np.minimum(gx, gy))
        score = np.where(pool, detour + dist + away, np.inf)
        end = divmod(int(np.argmin(score)), size)[::-1]
    path, node = [], end
    while node != centre:
        path.append((node[0] * cell + cell / 2, node[1] * cell + cell / 2))
        node = parent[node]
    path.append((cx, cy))
    path.reverse()
    blocked = not rim.any() and np.hypot(path[-1][0] - cx, path[-1][1] - cy) < 15

    def clear(a, b):
        steps = int(np.hypot(b[0] - a[0], b[1] - a[1]) / 2) + 1
        for i in range(steps + 1):
            x = a[0] + (b[0] - a[0]) * i / steps
            y = a[1] + (b[1] - a[1]) * i / steps
            if not free[int(y // cell), int(x // cell)]:
                return False
        return True

    # string-pulling: aim at the farthest point of the path that is in a clear straight line from the boat
    waypoint = path[1] if len(path) > 1 else path[0]
    for point in path[1:]:
        if clear((cx, cy), point):
            waypoint = point
    return Route(_angle(waypoint[0] - cx, waypoint[1] - cy), blocked, path)


def heading_error(heading: float, bearing: float) -> float:
    """Degrees to turn: positive means the target is anticlockwise of the heading (turn left)."""
    return (bearing - heading + 180) % 360 - 180


def progress_pairs(texts: Iterable[str]) -> list:
    """Every '(n/m)' objective counter in the texts, as (n, m) pairs."""
    return [(int(n), int(m)) for text in texts for n, m in _PROGRESS.findall(text)]


def parse_progress(texts: Iterable[str]) -> Tuple[int, int]:
    pairs = progress_pairs(texts)
    return sum(n for n, _ in pairs), sum(m for _, m in pairs)
