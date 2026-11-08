"""Small random variations that make bot input look less mechanical.

A script repeats the exact same pixel, the exact same hold time and the exact
same pause every time. A person never does. Each helper takes the planned
value and returns a slightly different one each call.
"""
import math
import random as _random


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def hold_time(base, rng=_random):
    """How long a key or mouse button stays down.

    Taps below 30 ms are not humanly possible, so they become a fast tap.
    Longer holds keep their length within a few percent.
    """
    if base <= 0.03:
        return rng.uniform(0.035, 0.07)
    return base * rng.uniform(0.95, 1.12)


def sleep_time(seconds, rng=_random):
    """A pause that is never shorter than planned, usually a little longer."""
    if seconds <= 0:
        return seconds
    return seconds * (1 + min(abs(rng.gauss(0, 0.06)), 0.2))


def reaction_delay(rng=_random):
    """Time between a button appearing and a person clicking it."""
    return rng.uniform(0.05, 0.18)


def _scatter(x, y, sigma_x, sigma_y, limit_x, limit_y, rng):
    dx = _clamp(rng.gauss(0, sigma_x), -limit_x, limit_x)
    dy = _clamp(rng.gauss(0, sigma_y), -limit_y, limit_y)
    return int(round(x + dx)), int(round(y + dy))


def point_in_box(bx, by, bw, bh, rel_x=0.5, rel_y=0.5, rng=_random):
    """Aim at a point in a box, landing near it the way a hand would.

    Bigger buttons get a wider spread. The spread stays within 30% of the box
    size around the aim point, so it works when the aim point is outside the box.
    """
    cx, cy = bx + bw * rel_x, by + bh * rel_y
    return _scatter(cx, cy, bw / 8, bh / 8, bw * 0.3, bh * 0.3, rng)


def point_near(x, y, screen_height, rng=_random):
    """A few pixels of spread around an exact coordinate (about 5 px max at 1080p)."""
    sigma = max(1.0, screen_height * 0.0015)
    return _scatter(x, y, sigma, sigma, sigma * 3, sigma * 3, rng)


def glide_path(start, end, rng=_random):
    """Cursor positions from start to end: eased, slightly bowed, ~0.1-0.25 s in total.

    Returns a list of (x, y, delay_after) ending exactly at end.
    """
    sx, sy = start
    ex, ey = end
    dist = math.hypot(ex - sx, ey - sy)
    if dist < 2:
        return [(int(ex), int(ey), 0.0)]
    steps = int(_clamp(dist / 25, 6, 30))
    duration = rng.uniform(0.1, 0.25)
    # bow sideways a little, like a wrist arc
    bow = rng.uniform(-0.08, 0.08) * dist
    nx, ny = -(ey - sy) / dist, (ex - sx) / dist
    path = []
    for i in range(1, steps + 1):
        t = i / steps
        eased = t * t * (3 - 2 * t)
        arc = bow * math.sin(math.pi * t)
        x = sx + (ex - sx) * eased + nx * arc
        y = sy + (ey - sy) * eased + ny * arc
        path.append((int(round(x)), int(round(y)), duration / steps * rng.uniform(0.7, 1.3)))
    path[-1] = (int(ex), int(ey), path[-1][2])
    return path
