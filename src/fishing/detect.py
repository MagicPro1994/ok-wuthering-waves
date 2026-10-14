import re
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


def _target_icon(rgb: np.ndarray) -> Optional[Tuple[float, float]]:
    cx, cy = MINIMAP_CENTRE
    r, g, b = [rgb[:260, :260, i].astype(int) for i in range(3)]
    yy, xx = np.mgrid[0:260, 0:260]
    mask = (r > 120) & (r < 200) & (b > 150) & (g < 110) & (b - g > 60) & (np.hypot(xx - cx, yy - cy) < 100)
    ys, xs = np.nonzero(mask)
    if len(xs) < 20:
        return None
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


def minimap_danger(rgb: np.ndarray) -> np.ndarray:
    """Pixels of the minimap that are not open water (land, shallows, structures), as a 260x260 mask.

    The minimap is translucent, so the water colour is taken from the frame itself: the median of the ring around
    the boat. The view cone is that colour blended 17.5% towards white; anything matching neither is not water.
    """
    a = rgb[:260, :260].astype(int)
    rad, _ = _minimap_grid()
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    yellow = (r > 180) & (g > 130) & (b < 140)
    purple = (r > 100) & (b > 130) & (g < 120) & (b - g > 40)
    white = (r > 190) & (g > 190) & (b > 190)
    over = cv2.dilate((yellow | purple | white).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    ring = (rad > 30) & (rad < 70) & ~over
    ref = np.median(a[ring], axis=0) if ring.any() else a.reshape(-1, 3).mean(0)
    cone = ref * 0.825 + 255 * 0.175
    water = (np.abs(a - ref).max(2) <= 14) | (np.abs(a - cone).max(2) <= 16)
    bad = ~water & ~over & (rad < 74)
    return cv2.morphologyEx(bad.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8)) > 0


def sector_danger(mask: np.ndarray, bearing: float, half_width: float = 15.0) -> float:
    """Share of the wedge around a bearing (minimap angle, east 0 anticlockwise) that is not open water."""
    rad, ang = _minimap_grid()
    wedge = (rad > 20) & (rad < 74) & (np.abs((ang - bearing + 180) % 360 - 180) <= half_width)
    return float(mask[wedge].mean()) if wedge.any() else 0.0


def steer_bearing(mask: np.ndarray, target_bearing: float, prefer: int = 1, limit: float = 0.3,
                  switch_cost: float = 30.0):
    """Cheapest clear bearing near the target's, as (bearing, offset), or None when every direction is blocked.

    The cost is the turn away from the target, plus `switch_cost` for the side the boat is not already going
    round (`prefer`, +1 / -1). That commitment makes it follow an island's coast instead of dithering at it.
    """
    options = []
    for offset in range(0, 181, 20):
        for sign in ((1,) if offset == 0 else (prefer, -prefer)):
            cost = offset + (switch_cost if offset and sign != prefer else 0)
            options.append((cost, sign * offset))
    for _, signed in sorted(options, key=lambda option: option[0]):
        candidate = (target_bearing + signed) % 360
        if sector_danger(mask, candidate) < limit:
            return candidate, signed
    return None


def heading_error(heading: float, bearing: float) -> float:
    """Degrees to turn: positive means the target is anticlockwise of the heading (turn left)."""
    return (bearing - heading + 180) % 360 - 180


def parse_progress(texts: Iterable[str]) -> Tuple[int, int]:
    done = total = 0
    for text in texts:
        for n, m in _PROGRESS.findall(text):
            done += int(n)
            total += int(m)
    return done, total
