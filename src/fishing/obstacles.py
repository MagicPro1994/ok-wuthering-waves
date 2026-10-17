from typing import Iterable, List, NamedTuple, Optional, Tuple

CLASSES = {0: 'land', 1: 'rock', 2: 'structure', 3: 'shallows'}

CORRIDOR = (0.36, 0.64)      # share of the frame width the bow sweeps through
SOLID_NEAR_Y = 0.50          # a land/rock/structure box whose foot is lower than this is close, not a far shore
SHALLOWS_AHEAD_Y = 0.42      # a shallows box whose top is higher than this reaches well in front of the bow, not just under it
BLOCKED_SIDE = 0.85          # share of a side covered by obstacles: nothing to turn into
TURN_DEGREES = 45.0


class Obstacle(NamedTuple):
    name: str
    x1: float
    y1: float
    x2: float
    y2: float


class Verdict(NamedTuple):
    action: str              # 'clear', 'turn' or 'blocked'
    error_deg: float         # positive: turn left (A), as detect.heading_error
    left: float              # share of the left half that is covered
    right: float


def to_obstacles(boxes: Iterable, width: float, height: float) -> List[Obstacle]:
    """Detector boxes (pixels, with .x .y .width .height .name) as fractions of the frame."""
    out = []
    for box in boxes:
        out.append(Obstacle(box.name, box.x / width, box.y / height,
                            (box.x + box.width) / width, (box.y + box.height) / height))
    return out


def is_near(obstacle: Obstacle) -> bool:
    if obstacle.name == 'shallows':
        return obstacle.y1 < SHALLOWS_AHEAD_Y
    return obstacle.y2 > SOLID_NEAR_Y


def _covered(obstacles: Iterable[Obstacle], lo: float, hi: float) -> float:
    """Share of the horizontal span [lo, hi] that near obstacles cover."""
    spans = sorted((max(o.x1, lo), min(o.x2, hi)) for o in obstacles if is_near(o) and o.x2 > lo and o.x1 < hi)
    covered, end = 0.0, lo
    for start, stop in spans:
        start = max(start, end)
        if stop > start:
            covered += stop - start
            end = stop
    return covered / (hi - lo)


def verdict(obstacles: Iterable[Obstacle]) -> Verdict:
    obstacles = list(obstacles)
    left = _covered(obstacles, 0.0, 0.5)
    right = _covered(obstacles, 0.5, 1.0)
    ahead = _covered(obstacles, *CORRIDOR)
    if ahead < 0.05:
        return Verdict('clear', 0.0, left, right)
    if left >= BLOCKED_SIDE and right >= BLOCKED_SIDE:
        return Verdict('blocked', 0.0, left, right)
    # turn towards the emptier half; a tie keeps the side the minimap route is already rounding
    if left < right:
        return Verdict('turn', TURN_DEGREES, left, right)
    if right < left:
        return Verdict('turn', -TURN_DEGREES, left, right)
    return Verdict('turn', TURN_DEGREES, left, right)


class ObstacleDetector:
    """The trained sailing model run on the live frame. Without the model file it reports nothing (no avoidance)."""

    def __init__(self, weights: str, threshold: float = 0.3):
        self.threshold = threshold
        self.model = None
        try:
            from src.OpenVinoYolo8Detect import OpenVinoYolo8Detect
            self.model = OpenVinoYolo8Detect(weights=weights)
            self.model.dic_labels = dict(CLASSES)
        except Exception:
            self.model = None

    @property
    def ready(self) -> bool:
        return self.model is not None

    def look(self, bgr) -> Optional[List[Obstacle]]:
        """Obstacles in the frame, or None when there is no model."""
        if self.model is None:
            return None
        height, width = bgr.shape[:2]
        boxes = self.model.detect(bgr, threshold=self.threshold)
        return [o for o in to_obstacles(boxes, width, height) if o.name in CLASSES.values()]
