import random as _random


def jitter_hold(seconds, rng=_random):
    return seconds * rng.uniform(0.93, 1.08)


def short_pause(rng=_random):
    return rng.uniform(0.05, 0.2)


def camera_steps(dx, rng=_random):
    steps, left = [], int(dx)
    sign = 1 if dx > 0 else -1
    while abs(left) > 3:
        size = min(abs(left), rng.randint(25, 70))
        steps.append((sign * size, rng.randint(-1, 1), rng.uniform(0.04, 0.11)))
        left -= sign * size
    return steps


def turn_hold_seconds(error_deg, rng=_random):
    return jitter_hold(min(abs(error_deg) / 83.0, 0.9), rng)


def offset_point(x, y, rng=_random, rx=0.004, ry=0.006):
    clamp = lambda v: min(1.0, max(0.0, v))
    return clamp(x + rng.uniform(-rx, rx)), clamp(y + rng.uniform(-ry, ry))


def sweep_plan(rng=_random):
    plan, total = [], 0
    target = rng.randint(1500, 2200)
    while total < target - 120:
        step = rng.randint(65, 115)
        plan.append(step)
        total += step
    plan.append(target - total)
    return plan


def sail_press(rng=_random):
    return rng.uniform(1.8, 2.8)
