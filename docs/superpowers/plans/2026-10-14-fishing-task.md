# FishingTask Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-time task `FishingTask` that completes the Premium Request of the permanent fishing event "Old Man and the…" once, then sells all fish at the Dock Shop.

**Architecture:** One `FishingTask(WWOneTimeTask, BaseWWTask)` state machine in `src/task/FishingTask.py`. All logic that can be tested without the game lives in four small pure modules under `src/fishing/` (cargo packer, human-like input timing, frame detectors, real-cursor input with an injectable Win32 API). The task wires them to OCR-driven screen handling; the game-facing states are verified live.

**Tech Stack:** Python (project `.venv`), `ok` script framework (`self.ocr`, `self.send_key`, `self.click_relative`, `self.frame`), OpenCV/numpy, pywin32 + ctypes (`user32.mouse_event`, `SetCursorPos`), `unittest`/`pytest`.

**Spec:** `docs/superpowers/specs/2026-10-14-fishing-task-design.md`

## Global Constraints

- Run Python with `.\.venv\Scripts\python.exe` (AGENTS.md). Run tests with `.\.venv\Scripts\python.exe -m pytest tests/<file> -v`.
- Only the **Premium Request** is in scope. Not Common Requests, Chanty Bounty, or paid refresh.
- Before Set Sail always select **Night** and tick **Automatically restore durability**.
- If the target marker does not show, set the in-game time to night (Esc, clock icon, drag the dial to 18:00 or later, Confirm).
- **Human-like input is a hard requirement.** Randomised key holds and pauses; camera turns split into small uneven mouse steps; clicks at small random offsets; no fixed-interval polling loops.
- **No middle-click camera recentre.** Aim the camera with relative mouse movement only.
- `Tool Key` must be `t` (`configs/Game Hotkey.json` currently has `mouse_x2`, which the installed `ok` cannot send).
- The game runs elevated, so the project runs elevated. Real-cursor drags need the game in the foreground. Do not restore or resize the game window.
- Steering signal is the 3D purple round marker, never the radar arrow.
- Heart loss is counted from red heart pixels in the bottom row (about x680–1200, y1000–1030 at 1920x1080; full = 5633 px at 8 hearts). Abort at 2 hearts or fewer.
- Sell uses **Sell All** once, never per-fish clicks. A selected fish blocks it ("Please handle the selected item first").
- The X at the top right of the dock hub is **Disembark**. Never click it. Do not press Esc blindly.
- Git commits: **no Claude co-author trailer** and no Claude/Anthropic attribution in commit messages (user's CLAUDE.md overrides any default).
- Temporary files go under `.tmp/` (gitignored), not the OS temp directory.

## Review Focus

- Premium Request not listed (refreshing, "Premium Refresh in 1h") → task exits cleanly without sailing. Test: `parse_progress`/entry check on OCR text lacking "Premium".
- Packer given pieces that cannot all fit → returns `None`, task keeps the piece unplaced and still reaches Sell All. Test in `TestCargoPacker`.
- Marker never visible after a full camera sweep and one time reset → task stops with a message instead of looping. Test: `sweep` helper returns a bounded list of steps.
- Hearts drop while sailing → task reverses and turns away, then aborts at 2 hearts. Test: `hearts_from_px` and `heart_loss` thresholds.
- Game window not foreground / helper input fails → `RealInput.focus` raises a clear error instead of dragging blind. Test with fake API.

## File Structure

| File | Responsibility |
|---|---|
| `src/fishing/__init__.py` | package marker (empty) |
| `src/fishing/cargo_packer.py` | pure: rotations and backtracking placement of pieces on free cells |
| `src/fishing/human_input.py` | pure: jittered hold times, uneven camera chunks, offset points, camera sweep plan |
| `src/fishing/detect.py` | pure: marker finder, heart counter, progress-text parser |
| `src/fishing/real_input.py` | real-cursor foreground, relative mouse move, human-like drag (Win32 API injectable) |
| `src/task/FishingTask.py` | the task and its states |
| `tests/TestCargoPacker.py`, `tests/TestHumanInput.py`, `tests/TestFishingDetect.py`, `tests/TestRealInput.py`, `tests/TestFishingTask.py` | tests |
| `config.py` | register task in `onetime_tasks` |
| `configs/Game Hotkey.json` | `Tool Key` → `t` |

Frames are `numpy` RGB arrays at 1920x1080 in the pure modules. The task converts the `ok` frame (BGR, any supported size) with `cv2.resize(..., (1920, 1080))` then `cv2.cvtColor(..., cv2.COLOR_BGR2RGB)`.

---

### Task 1: Hotkey config and package skeleton

**Files:**
- Modify: `configs/Game Hotkey.json` (`"Tool Key": "mouse_x2"` → `"t"`)
- Create: `src/fishing/__init__.py` (empty)
- Test: `tests/TestFishingTask.py`

**Interfaces:**
- Produces: `tests/TestFishingTask.py` with class `TestFishingConfig`.

- [ ] **Step 1: Write the failing test**

```python
import json
import unittest
from pathlib import Path


class TestFishingConfig(unittest.TestCase):
    def test_tool_key_is_sendable(self):
        data = json.loads(Path("configs/Game Hotkey.json").read_text(encoding="utf-8"))
        self.assertEqual("t", data["Tool Key"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestFishingTask.py -v`
Expected: FAIL (`'mouse_x2' != 't'`).

- [ ] **Step 3: Make the change**

Edit `configs/Game Hotkey.json`: set `"Tool Key": "t"`. Create the empty `src/fishing/__init__.py`.

- [ ] **Step 4: Run to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestFishingTask.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add configs/"Game Hotkey.json" src/fishing/__init__.py tests/TestFishingTask.py
git commit -m "feat(fishing): set Tool Key to t and add fishing package"
```

---

### Task 2: Cargo packer

**Files:**
- Create: `src/fishing/cargo_packer.py`
- Test: `tests/TestCargoPacker.py`

**Interfaces:**
- Produces:
  - `Cell = tuple[int, int]` (row, col)
  - `normalize(cells: Iterable[Cell]) -> frozenset[Cell]` shifts so min row and min col are 0
  - `rotate_cw(cells: Iterable[Cell]) -> frozenset[Cell]` one 90° clockwise turn, normalised
  - `orientations(cells) -> list[tuple[int, frozenset[Cell]]]` unique `(rotation_count, normalised_cells)`, rotation_count 0–3
  - `Placement` dataclass: `rotations: int`, `cells: frozenset[Cell]` (absolute), `origin: Cell` (min row, min col of `cells`)
  - `pack(free: Iterable[Cell], pieces: dict[str, Iterable[Cell]]) -> dict[str, Placement] | None`
  - `pack_best(free, pieces, values: dict[str, int], required: Iterable[str] = (), node_limit: int = 200_000) -> dict[str, Placement] | None` places every `required` piece (else `None`) and the subset of the other pieces with the highest total value. Branch-and-bound: after `node_limit` nodes it returns the best plan found so far.

- [ ] **Step 1: Write the failing tests**

```python
import unittest

from src.fishing.cargo_packer import normalize, rotate_cw, orientations, pack, pack_best

L = {(0, 0), (1, 0), (2, 0), (2, 1)}
SQUARE = {(0, 0), (0, 1), (1, 0), (1, 1)}
BAR = {(0, 0), (0, 1), (0, 2), (0, 3)}


def grid(rows, cols, blocked=()):
    return {(r, c) for r in range(rows) for c in range(cols)} - set(blocked)


class TestCargoPacker(unittest.TestCase):
    def test_rotate_four_times_is_identity(self):
        cells = normalize(L)
        r = cells
        for _ in range(4):
            r = rotate_cw(r)
        self.assertEqual(cells, r)

    def test_square_has_one_orientation(self):
        self.assertEqual(1, len(orientations(SQUARE)))

    def test_single_piece_fits_exactly(self):
        out = pack(grid(2, 2), {"sq": SQUARE})
        self.assertEqual(grid(2, 2), out["sq"].cells)
        self.assertEqual((0, 0), out["sq"].origin)

    def test_needs_rotation(self):
        out = pack(grid(2, 3), {"l": L})
        self.assertIsNotNone(out)
        p = out["l"]
        self.assertNotEqual(0, p.rotations)
        expected = dict(orientations(L))[p.rotations]
        self.assertEqual(expected, normalize(p.cells))

    def test_two_pieces_do_not_overlap(self):
        free = grid(2, 6)
        out = pack(free, {"a": SQUARE, "b": BAR})
        self.assertIsNotNone(out)
        self.assertEqual(set(), set(out["a"].cells) & set(out["b"].cells))
        self.assertTrue((set(out["a"].cells) | set(out["b"].cells)) <= free)

    def test_blocked_corners_respected(self):
        free = grid(2, 2, blocked=[(0, 0)])
        self.assertIsNone(pack(free, {"sq": SQUARE}))

    def test_returns_none_when_not_all_fit(self):
        self.assertIsNone(pack(grid(2, 2), {"a": SQUARE, "b": SQUARE}))

    def test_empty_pieces(self):
        self.assertEqual({}, pack(grid(2, 2), {}))

    def test_backtracks_to_find_tight_fit(self):
        # 2x4 free: bar horizontal on one row, then another bar on the other row.
        out = pack(grid(2, 4), {"a": BAR, "b": BAR})
        self.assertIsNotNone(out)
        self.assertEqual(grid(2, 4), out["a"].cells | out["b"].cells)

    def test_best_prefers_higher_value(self):
        out = pack_best(grid(2, 2), {"a": SQUARE, "b": SQUARE}, {"a": 5, "b": 8})
        self.assertEqual({"b"}, set(out))

    def test_best_keeps_required_over_value(self):
        out = pack_best(grid(2, 2), {"a": SQUARE, "b": SQUARE}, {"a": 1, "b": 10}, required=["a"])
        self.assertEqual({"a"}, set(out))

    def test_best_none_when_required_does_not_fit(self):
        self.assertIsNone(pack_best(grid(2, 2), {"a": SQUARE, "b": SQUARE}, {"a": 1, "b": 1}, required=["a", "b"]))

    def test_best_picks_best_subset(self):
        pieces = {"bar": BAR, "s1": SQUARE, "s2": SQUARE}
        out = pack_best(grid(2, 4), pieces, {"bar": 3, "s1": 5, "s2": 5})
        self.assertEqual({"s1", "s2"}, set(out))

    def test_best_no_overlap_and_inside_free(self):
        free = grid(3, 4, blocked=[(0, 0)])
        out = pack_best(free, {"l": L, "sq": SQUARE, "bar": BAR}, {"l": 4, "sq": 6, "bar": 5})
        used = [c for p in out.values() for c in p.cells]
        self.assertEqual(len(used), len(set(used)))
        self.assertTrue(set(used) <= free)

    def test_best_node_limit_still_returns_plan(self):
        out = pack_best(grid(2, 2), {"a": SQUARE}, {"a": 1}, node_limit=1)
        self.assertEqual({"a"}, set(out))

    def test_best_empty(self):
        self.assertEqual({}, pack_best(grid(2, 2), {}, {}))
```

- [ ] **Step 2: Run to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestCargoPacker.py -v` → FAIL (ImportError).

- [ ] **Step 3: Implement**

```python
from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, List, Optional, Tuple

Cell = Tuple[int, int]


def normalize(cells: Iterable[Cell]) -> FrozenSet[Cell]:
    cells = list(cells)
    if not cells:
        return frozenset()
    min_r = min(r for r, _ in cells)
    min_c = min(c for _, c in cells)
    return frozenset((r - min_r, c - min_c) for r, c in cells)


def rotate_cw(cells: Iterable[Cell]) -> FrozenSet[Cell]:
    return normalize((c, -r) for r, c in cells)


def orientations(cells: Iterable[Cell]) -> List[Tuple[int, FrozenSet[Cell]]]:
    result, seen = [], set()
    current = normalize(cells)
    for rotation in range(4):
        if current not in seen:
            seen.add(current)
            result.append((rotation, current))
        current = rotate_cw(current)
    return result


@dataclass(frozen=True)
class Placement:
    rotations: int
    cells: FrozenSet[Cell]
    origin: Cell


def pack(free: Iterable[Cell], pieces: Dict[str, Iterable[Cell]]) -> Optional[Dict[str, Placement]]:
    free_set = set(free)
    order = sorted(pieces, key=lambda name: -len(list(pieces[name])))
    shapes = {name: orientations(pieces[name]) for name in order}
    result: Dict[str, Placement] = {}

    def place(index: int, available: set) -> bool:
        if index == len(order):
            return True
        name = order[index]
        for rotation, shape in shapes[name]:
            for r0, c0 in sorted(available):
                cells = frozenset((r + r0, c + c0) for r, c in shape)
                if cells <= available:
                    result[name] = Placement(rotation, cells, (r0, c0))
                    if place(index + 1, available - cells):
                        return True
                    del result[name]
        return False

    return result if place(0, free_set) else None


def pack_best(free, pieces, values, required=(), node_limit=200_000):
    free_set = set(free)
    required = set(required)
    order = sorted(pieces, key=lambda n: (n not in required, -values.get(n, 0), -len(list(pieces[n]))))
    shapes = {name: orientations(pieces[name]) for name in order}
    suffix = [sum(values.get(n, 0) for n in order[i:]) for i in range(len(order) + 1)]
    best = {'value': -1, 'plan': None}
    current: Dict[str, Placement] = {}
    nodes = [0]

    def search(i: int, available: set, value: int):
        nodes[0] += 1
        if nodes[0] > node_limit and best['plan'] is not None:
            return
        if value + suffix[i] <= best['value']:
            return
        if i == len(order):
            best['value'], best['plan'] = value, dict(current)
            return
        name = order[i]
        for rotation, shape in shapes[name]:
            for r0, c0 in sorted(available):
                cells = frozenset((r + r0, c + c0) for r, c in shape)
                if cells <= available:
                    current[name] = Placement(rotation, cells, (r0, c0))
                    search(i + 1, available - cells, value + values.get(name, 0))
                    del current[name]
        if name not in required:
            search(i + 1, available, value)

    search(0, free_set, 0)
    return best['plan']
```

Note on `origin`: `(r0, c0)` is the anchor offset added to the normalised shape, so it equals the min row/min col of `cells`.

- [ ] **Step 4: Run to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestCargoPacker.py -v` → PASS (16 tests).

- [ ] **Step 5: Commit**

```bash
git add src/fishing/cargo_packer.py tests/TestCargoPacker.py
git commit -m "feat(fishing): add cargo packer with value-optimising mode"
```

---

### Task 3: Human-like input timing helpers

**Files:**
- Create: `src/fishing/human_input.py`
- Test: `tests/TestHumanInput.py`

**Interfaces:**
- Produces (all take an optional `rng: random.Random`, default module `random`):
  - `jitter_hold(seconds: float, rng=random) -> float` returns `seconds * U(0.93, 1.08)`
  - `short_pause(rng=random) -> float` returns `U(0.05, 0.2)`
  - `camera_steps(dx: int, rng=random) -> list[tuple[int, int, float]]` list of `(step_dx, step_dy, delay_after)`; `|step_dx|` in 25–70 except possibly the last; `step_dy` in -1..1; delay in 0.04–0.11; steps sum to `dx` within ±3; empty for `abs(dx) <= 3`
  - `turn_hold_seconds(error_deg: float, rng=random) -> float` A/D hold: `min(abs(error_deg) / 83.0, 0.9)` jittered
  - `offset_point(x: float, y: float, rng=random, rx=0.004, ry=0.006) -> tuple[float, float]` fractions, clamped to [0, 1]
  - `sweep_plan(rng=random) -> list[int]` camera dx steps covering about one full turn (about 20 steps of 90 ± 25 units, sum 1500–2200 units), used when the marker is lost
  - `sail_press(rng=random) -> float` W hold `U(1.8, 2.8)`

- [ ] **Step 1: Write the failing tests**

```python
import random
import unittest

from src.fishing import human_input as hi


class TestHumanInput(unittest.TestCase):
    def setUp(self):
        self.rng = random.Random(7)

    def test_jitter_hold_range(self):
        for _ in range(200):
            v = hi.jitter_hold(1.0, self.rng)
            self.assertTrue(0.93 <= v <= 1.08)

    def test_camera_steps_sum_and_bounds(self):
        for dx in (300, -300, 41, -90, 1000):
            steps = hi.camera_steps(dx, self.rng)
            self.assertLessEqual(abs(sum(s[0] for s in steps) - dx), 3)
            for sx, sy, delay in steps[:-1]:
                self.assertTrue(25 <= abs(sx) <= 70)
            for sx, sy, delay in steps:
                self.assertTrue(-1 <= sy <= 1)
                self.assertTrue(0.04 <= delay <= 0.11)
                self.assertEqual(dx > 0, sx > 0)

    def test_camera_steps_are_not_uniform(self):
        sizes = {abs(s[0]) for s in hi.camera_steps(2000, self.rng)[:-1]}
        self.assertGreater(len(sizes), 5)

    def test_tiny_turn_is_noop(self):
        self.assertEqual([], hi.camera_steps(3, self.rng))
        self.assertEqual([], hi.camera_steps(-2, self.rng))

    def test_turn_hold_capped(self):
        self.assertLessEqual(hi.turn_hold_seconds(500, self.rng), 0.9 * 1.08)
        self.assertAlmostEqual(83 / 83.0, hi.turn_hold_seconds(83, random.Random(1)), delta=0.09)

    def test_offset_point_clamped_and_close(self):
        for _ in range(200):
            x, y = hi.offset_point(0.001, 0.999, self.rng)
            self.assertTrue(0.0 <= x <= 1.0 and 0.0 <= y <= 1.0)
        x, y = hi.offset_point(0.5, 0.5, self.rng)
        self.assertLess(abs(x - 0.5), 0.0041)
        self.assertLess(abs(y - 0.5), 0.0061)

    def test_sweep_plan_covers_a_turn(self):
        plan = hi.sweep_plan(self.rng)
        self.assertTrue(1500 <= sum(plan) <= 2200)
        self.assertGreater(len(set(plan)), 5)

    def test_sail_press_range(self):
        for _ in range(100):
            self.assertTrue(1.8 <= hi.sail_press(self.rng) <= 2.8)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestHumanInput.py -v` → FAIL (ImportError).

- [ ] **Step 3: Implement**

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestHumanInput.py -v` → PASS. If `sweep_plan` sum falls outside 1500–2200 for the seed, adjust the loop, not the test.

- [ ] **Step 5: Commit**

```bash
git add src/fishing/human_input.py tests/TestHumanInput.py
git commit -m "feat(fishing): add human-like input timing helpers"
```

---

### Task 4: Frame detectors and progress parser

**Files:**
- Create: `src/fishing/detect.py`
- Test: `tests/TestFishingDetect.py`

**Interfaces:**
- Produces:
  - `find_marker(rgb: np.ndarray) -> tuple[float, float, int] | None` `(x, y, area)` on a 1080x1920x3 RGB frame
  - `heart_px(rgb) -> int` red pixel count in the hearts row
  - `hearts_from_px(px: int, full_px: int = 5633, max_hearts: int = 8) -> int`
  - `marker_error_deg(marker_x: float, centre_x: float = 960.0, px_per_deg: float = 21.0) -> float` positive = marker right of centre
  - `parse_progress(texts: Iterable[str]) -> tuple[int, int]` returns `(done, total)` summed over every `(n/m)` found; `(0, 0)` if none
  - `FULL_HEARTS_PX = 5633`

- [ ] **Step 1: Write the failing tests**

```python
import unittest

import cv2
import numpy as np

from src.fishing import detect


def blank():
    return np.full((1080, 1920, 3), (20, 40, 80), np.uint8)


class TestMarker(unittest.TestCase):
    def test_finds_round_marker(self):
        img = blank()
        cv2.circle(img, (800, 500), 14, (150, 60, 200), -1)
        x, y, area = detect.find_marker(img)
        self.assertAlmostEqual(800, x, delta=2)
        self.assertAlmostEqual(500, y, delta=2)
        self.assertTrue(250 < area < 1500)

    def test_ignores_sail_shape(self):
        img = blank()
        cv2.fillPoly(img, [np.array([[960, 600], [1000, 780], [920, 780]])], (150, 60, 200))
        self.assertIsNone(detect.find_marker(img))

    def test_ignores_hud_regions(self):
        img = blank()
        cv2.circle(img, (100, 100), 14, (150, 60, 200), -1)   # top-left HUD
        cv2.circle(img, (1700, 800), 14, (150, 60, 200), -1)  # bottom-right HUD
        self.assertIsNone(detect.find_marker(img))

    def test_none_on_empty(self):
        self.assertIsNone(detect.find_marker(blank()))

    def test_error_deg(self):
        self.assertAlmostEqual(0.0, detect.marker_error_deg(960))
        self.assertAlmostEqual(10.0, detect.marker_error_deg(960 + 210))
        self.assertAlmostEqual(-5.0, detect.marker_error_deg(960 - 105))


class TestHearts(unittest.TestCase):
    def _hearts(self, n):
        img = blank()
        for i in range(n):
            cv2.rectangle(img, (690 + i * 60, 1005), (690 + i * 60 + 28, 1025), (230, 40, 40), -1)
        return img

    def test_px_scales_with_hearts(self):
        self.assertGreater(detect.heart_px(self._hearts(8)), detect.heart_px(self._hearts(4)))
        self.assertEqual(0, detect.heart_px(blank()))

    def test_hearts_from_px(self):
        self.assertEqual(8, detect.hearts_from_px(5633))
        self.assertEqual(4, detect.hearts_from_px(2817))
        self.assertEqual(2, detect.hearts_from_px(1400))
        self.assertEqual(0, detect.hearts_from_px(0))
        self.assertEqual(8, detect.hearts_from_px(9000))


class TestProgress(unittest.TestCase):
    def test_sums_fractions(self):
        self.assertEqual((1, 2), detect.parse_progress(["Catch Giant Gulper Mutant (1/1)", "Catch Sob Blob Mutant (0/1)"]))

    def test_done(self):
        self.assertEqual((2, 2), detect.parse_progress(["x (1/1)", "y (1/1)"]))

    def test_none_found(self):
        self.assertEqual((0, 0), detect.parse_progress(["Special: One Last Tear"]))

    def test_ocr_spacing(self):
        self.assertEqual((0, 1), detect.parse_progress(["Catch Sob Blob ( 0 / 1 )"]))
```

- [ ] **Step 2: Run to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestFishingDetect.py -v` → FAIL (ImportError).

- [ ] **Step 3: Implement**

```python
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


def marker_error_deg(marker_x: float, centre_x: float = 960.0, px_per_deg: float = 21.0) -> float:
    return (marker_x - centre_x) / px_per_deg


def parse_progress(texts: Iterable[str]) -> Tuple[int, int]:
    done = total = 0
    for text in texts:
        for n, m in _PROGRESS.findall(text):
            done += int(n)
            total += int(m)
    return done, total
```

- [ ] **Step 4: Run to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestFishingDetect.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/fishing/detect.py tests/TestFishingDetect.py
git commit -m "feat(fishing): add marker, heart and progress detectors"
```

---

### Task 5: Real-cursor input

**Files:**
- Create: `src/fishing/real_input.py`
- Test: `tests/TestRealInput.py`

**Interfaces:**
- Consumes: `short_pause` is not needed; uses its own `random`.
- Produces:
  - `to_screen(origin: tuple[int, int], size: tuple[int, int], fx: float, fy: float) -> tuple[int, int]`
  - `class Win32Api` with `set_cursor(x, y)`, `mouse_event(flags, dx, dy)`, `foreground() -> int`, `set_foreground(hwnd)`, `keybd_alt()`, `client_origin(hwnd) -> (int, int)`, `client_size(hwnd) -> (int, int)`; real implementation uses `ctypes.windll.user32` and `win32gui`
  - `class RealInput(hwnd: int, api=None, sleep=time.sleep, rng=random)` with:
    - `focus()` brings the game forward (Alt tap + `SetForegroundWindow`); raises `RuntimeError("game window not in foreground")` if still not foreground after 5 tries
    - `rel_move(dx: int, dy: int)` one relative `mouse_event`
    - `drag(x1, y1, x2, y2, duration=0.9)` fractions of the client; calls `focus()` first; moves with an eased, slightly wobbly path in steps of about 15 ms; LEFTDOWN at the start point, LEFTUP at the end
  - Constants `MOVE = 0x0001`, `LEFTDOWN = 0x0002`, `LEFTUP = 0x0004`

- [ ] **Step 1: Write the failing tests**

```python
import random
import unittest

from src.fishing.real_input import RealInput, to_screen, LEFTDOWN, LEFTUP, MOVE


class FakeApi:
    def __init__(self, foreground_after=1):
        self.calls = []
        self.fg = 0
        self.attempts = 0
        self.foreground_after = foreground_after

    def set_cursor(self, x, y): self.calls.append(("cursor", x, y))
    def mouse_event(self, flags, dx=0, dy=0): self.calls.append(("event", flags, dx, dy))
    def foreground(self): return self.fg
    def keybd_alt(self): self.calls.append(("alt",))

    def set_foreground(self, hwnd):
        self.attempts += 1
        if self.attempts >= self.foreground_after:
            self.fg = hwnd

    def client_origin(self, hwnd): return (100, 50)
    def client_size(self, hwnd): return (1920, 1080)


class TestRealInput(unittest.TestCase):
    def test_to_screen(self):
        self.assertEqual((100 + 960, 50 + 540), to_screen((100, 50), (1920, 1080), 0.5, 0.5))

    def test_drag_order(self):
        api = FakeApi()
        RealInput(7, api=api, sleep=lambda s: None, rng=random.Random(3)).drag(0.2, 0.3, 0.6, 0.5, 0.4)
        events = [c for c in api.calls if c[0] == "event"]
        self.assertEqual(LEFTDOWN, events[0][1])
        self.assertEqual(LEFTUP, events[-1][1])
        cursors = [c for c in api.calls if c[0] == "cursor"]
        self.assertAlmostEqual(100 + 0.2 * 1920, cursors[0][1], delta=3)
        self.assertAlmostEqual(100 + 0.6 * 1920, cursors[-1][1], delta=3)
        self.assertGreater(len(cursors), 10)
        down_index = api.calls.index(events[0])
        up_index = api.calls.index(events[-1])
        self.assertTrue(any(c[0] == "cursor" for c in api.calls[down_index:up_index]))

    def test_drag_path_is_not_a_straight_line(self):
        api = FakeApi()
        RealInput(7, api=api, sleep=lambda s: None, rng=random.Random(3)).drag(0.2, 0.5, 0.8, 0.5, 0.5)
        ys = {c[2] for c in api.calls if c[0] == "cursor"}
        self.assertGreater(len(ys), 1)

    def test_focus_retries_then_succeeds(self):
        api = FakeApi(foreground_after=3)
        RealInput(7, api=api, sleep=lambda s: None).focus()
        self.assertEqual(7, api.fg)

    def test_focus_failure_raises(self):
        api = FakeApi(foreground_after=99)
        with self.assertRaises(RuntimeError):
            RealInput(7, api=api, sleep=lambda s: None).focus()

    def test_rel_move(self):
        api = FakeApi()
        RealInput(7, api=api, sleep=lambda s: None).rel_move(40, -1)
        self.assertEqual([("event", MOVE, 40, -1)], api.calls)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestRealInput.py -v` → FAIL (ImportError).

- [ ] **Step 3: Implement**

```python
import ctypes
import math
import random as _random
import time

MOVE = 0x0001
LEFTDOWN = 0x0002
LEFTUP = 0x0004
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002


def to_screen(origin, size, fx, fy):
    return int(origin[0] + fx * size[0]), int(origin[1] + fy * size[1])


class Win32Api:
    def __init__(self):
        self.user32 = ctypes.windll.user32
        self.user32.SetProcessDPIAware()

    def set_cursor(self, x, y):
        self.user32.SetCursorPos(int(x), int(y))

    def mouse_event(self, flags, dx=0, dy=0):
        self.user32.mouse_event(flags, int(dx), int(dy), 0, 0)

    def foreground(self):
        return self.user32.GetForegroundWindow()

    def set_foreground(self, hwnd):
        self.user32.SetForegroundWindow(hwnd)

    def keybd_alt(self):
        self.user32.keybd_event(VK_MENU, 0, 0, 0)
        self.user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)

    def client_origin(self, hwnd):
        import win32gui
        return win32gui.ClientToScreen(hwnd, (0, 0))

    def client_size(self, hwnd):
        import win32gui
        return win32gui.GetClientRect(hwnd)[2:]


class RealInput:
    """Real-cursor input for what PostMessage cannot do (cargo pieces, time dial, camera)."""

    def __init__(self, hwnd, api=None, sleep=time.sleep, rng=_random):
        self.hwnd = hwnd
        self.api = api or Win32Api()
        self.sleep = sleep
        self.rng = rng

    def focus(self):
        for _ in range(5):
            if self.api.foreground() == self.hwnd:
                return
            self.api.keybd_alt()
            self.api.set_foreground(self.hwnd)
            self.sleep(self.rng.uniform(0.15, 0.35))
        if self.api.foreground() != self.hwnd:
            raise RuntimeError("game window not in foreground")

    def rel_move(self, dx, dy):
        self.api.mouse_event(MOVE, dx, dy)

    def drag(self, x1, y1, x2, y2, duration=0.9):
        self.focus()
        origin = self.api.client_origin(self.hwnd)
        size = self.api.client_size(self.hwnd)
        start = to_screen(origin, size, x1, y1)
        end = to_screen(origin, size, x2, y2)
        self.api.set_cursor(*start)
        self.sleep(self.rng.uniform(0.15, 0.3))
        self.api.mouse_event(LEFTDOWN)
        self.sleep(self.rng.uniform(0.2, 0.3))
        steps = max(12, int(duration / 0.015))
        wobble = self.rng.uniform(2.0, 6.0)
        phase = self.rng.uniform(0, math.pi)
        for i in range(1, steps + 1):
            t = i / steps
            eased = t * t * (3 - 2 * t)
            x = start[0] + (end[0] - start[0]) * eased
            y = start[1] + (end[1] - start[1]) * eased + wobble * math.sin(math.pi * t + phase) * (1 - t)
            self.api.set_cursor(x, y)
            self.sleep(self.rng.uniform(0.010, 0.020))
        self.api.set_cursor(*end)
        self.sleep(self.rng.uniform(0.2, 0.3))
        self.api.mouse_event(LEFTUP)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestRealInput.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/fishing/real_input.py tests/TestRealInput.py
git commit -m "feat(fishing): add real-cursor input with injectable Win32 API"
```

---

### Task 6: Task skeleton, registration, hotkey check, premium entry

**Files:**
- Create: `src/task/FishingTask.py`
- Modify: `config.py:262-274` (add `["src.task.FishingTask", "FishingTask"],` after the GardenTask line)
- Test: `tests/TestFishingTask.py`

**Interfaces:**
- Consumes: Task 1–5 modules.
- Produces `FishingTask` with methods used by later tasks (all on `self`):
  - `run()`
  - `check_tool_key()` raises `Exception("Set Tool Key to t in Game Hotkey ...")` if `self.key_config.get('Tool Key') != 't'`
  - `rgb_frame() -> np.ndarray` 1080x1920 RGB
  - `hold_key(key: str, seconds: float)` jittered `send_key` plus pause
  - `click_at(fx, fy, after_sleep=0.4)` clicks at `offset_point(fx, fy)` with a random hold
  - `texts(x, y, to_x, to_y) -> list[str]` OCR strings in a region
  - `has_text(pattern: str, x=0, y=0, to_x=1, to_y=1) -> bool`
  - `fail(message)` saves a screenshot, logs, calls `ensure_main`, raises
  - `go_to_dock()`, `pick_premium() -> bool`, `prepare_and_sail()`, `set_time_to_night()`, `sail_to_fish()`, `fish()`, `handle_catches()`, `deliver()`, `sell_all()` (bodies added in Tasks 7–11)

- [ ] **Step 1: Write the failing tests** (append to `tests/TestFishingTask.py`)

```python
from src.task.FishingTask import FishingTask


class FakeKeys:
    def __init__(self, value):
        self.value = value

    def get(self, key):
        return self.value


class TestFishingTaskBasics(unittest.TestCase):
    def test_check_tool_key_rejects_other_keys(self):
        task = FishingTask.__new__(FishingTask)
        task.key_config = FakeKeys("mouse_x2")
        with self.assertRaises(Exception) as ctx:
            task.check_tool_key()
        self.assertIn("Tool Key", str(ctx.exception))

    def test_check_tool_key_accepts_t(self):
        task = FishingTask.__new__(FishingTask)
        task.key_config = FakeKeys("t")
        task.check_tool_key()

    def test_registered_in_config(self):
        from config import config
        self.assertIn(["src.task.FishingTask", "FishingTask"], config["onetime_tasks"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestFishingTask.py -v` → FAIL (ImportError).

- [ ] **Step 3: Implement the skeleton**

```python
import random
import re
import time

import cv2
import numpy as np
from ok import Logger

from src.fishing import detect, human_input as hi
from src.fishing.cargo_packer import pack
from src.fishing.real_input import RealInput
from src.task.BaseWWTask import BaseWWTask
from src.task.WWOneTimeTask import WWOneTimeTask

logger = Logger.get_logger(__name__)


class FishingTask(WWOneTimeTask, BaseWWTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "🎣 Daily Fishing (Premium Request)"
        self.description = ("Riccioli Islands 'Old Man and the…': complete the Premium Request, "
                            "deliver it, then sell all fish. Start in the open world. Needs an elevated run.")
        self.default_config.update({'Max Sail Minutes': 25})
        self.real = None

    def run(self):
        WWOneTimeTask.run(self)
        self.check_tool_key()
        self.ensure_main()
        self.real = RealInput(self.hwnd.hwnd)
        self.go_to_dock()
        if not self.pick_premium():
            self.log_info('No Premium Request listed (refreshing); nothing to do', notify=True)
            self.ensure_main()
            return
        self.prepare_and_sail()
        deadline = time.time() + self.config.get('Max Sail Minutes', 25) * 60
        while not self.objectives_done():
            if time.time() > deadline:
                self.fail('sail timeout')
            self.sail_to_fish()
            self.fish()
            self.handle_catches()
        self.deliver()
        self.sell_all()
        self.log_info('Fishing daily done', notify=True)

    # ---- helpers -------------------------------------------------------

    def check_tool_key(self):
        if self.key_config.get('Tool Key') != 't':
            raise Exception('Set Tool Key to t in Game Hotkey (and in game): the ship utility teleports to the dock')

    def rgb_frame(self):
        frame = cv2.resize(self.frame, (1920, 1080))
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    def hold_key(self, key, seconds):
        self.send_key(key, down_time=hi.jitter_hold(seconds))
        self.sleep(seconds * 0.1 + hi.short_pause())

    def click_at(self, fx, fy, after_sleep=0.4):
        x, y = hi.offset_point(fx, fy)
        self.click_relative(x, y, after_sleep=after_sleep * random.uniform(0.8, 1.3))

    def texts(self, x=0, y=0, to_x=1, to_y=1):
        return [box.name for box in (self.ocr(x, y, to_x, to_y) or [])]

    def has_text(self, pattern, x=0, y=0, to_x=1, to_y=1):
        regex = re.compile(pattern, re.IGNORECASE)
        return any(regex.search(t) for t in self.texts(x, y, to_x, to_y))

    def fail(self, message):
        logger.error(f'fishing failed: {message}')
        self.screenshot(f'fishing_fail_{int(time.time())}')
        self.log_error(message, notify=True)
        raise Exception(message)

    # ---- states (filled in by later tasks) -----------------------------

    def go_to_dock(self): raise NotImplementedError
    def pick_premium(self): raise NotImplementedError
    def prepare_and_sail(self): raise NotImplementedError
    def set_time_to_night(self): raise NotImplementedError
    def objectives_done(self): raise NotImplementedError
    def sail_to_fish(self): raise NotImplementedError
    def fish(self): raise NotImplementedError
    def handle_catches(self): raise NotImplementedError
    def deliver(self): raise NotImplementedError
    def sell_all(self): raise NotImplementedError
```

Edit `config.py` `onetime_tasks`: add `["src.task.FishingTask", "FishingTask"],` after the `GardenTask` entry.

- [ ] **Step 4: Run to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestFishingTask.py tests/TestConfig.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/task/FishingTask.py config.py tests/TestFishingTask.py
git commit -m "feat(fishing): add FishingTask skeleton and register it"
```

---

### Task 7: Dock, Premium request, preparation, set time (live-verified)

Needs the game running at the open world, project elevated. Coordinates are fractions of 1920x1080 from the probe session.

**Files:**
- Modify: `src/task/FishingTask.py` (`go_to_dock`, `pick_premium`, `prepare_and_sail`, `set_time_to_night`)
- Test: `tests/TestFishingTask.py`

**Interfaces:**
- Produces: `go_to_dock()`, `pick_premium() -> bool` (True when Premium is listed and now tracked), `prepare_and_sail()`, `set_time_to_night()`.
- Pure helper `premium_listed(texts: list[str]) -> bool` (module level in `FishingTask.py`): True when some text mentions "premium" and not every such text is a "refresh" countdown.

- [ ] **Step 1: Write the failing test**

```python
from src.task.FishingTask import premium_listed


class TestPremiumListed(unittest.TestCase):
    def test_listed(self):
        self.assertTrue(premium_listed(["Premium Request", "Special: One Last Tear"]))

    def test_refreshing_only(self):
        self.assertFalse(premium_listed(["Premium Refresh in 1h"]))

    def test_missing(self):
        self.assertFalse(premium_listed(["Common Request", "Night Challenge"]))
```

- [ ] **Step 2: Run to verify it fails** → ImportError for `premium_listed`.

- [ ] **Step 3: Implement**

Add at module level in `FishingTask.py`:

```python
def premium_listed(texts):
    premium = [t.lower() for t in texts if 'premium' in t.lower()]
    return bool(premium) and not all('refresh' in t for t in premium)
```

`go_to_dock` is written in Step 4 from live measurements. Because the Events-tab layout was not recorded in the probe session, this step is done live:

- [ ] **Step 4: Capture and record the Events entry (live)**

With the game at the open world, run a scratch script under `.tmp/fishing/` (not committed) that opens the Events window and dumps OCR boxes with positions for the screen:

```python
# .tmp/fishing/dump_ocr.py -- run inside the ok task runner via a one-off DiagnosisTask-style task
for b in self.ocr(0, 0, 1, 1): print(b.name, round(b.x/self.width, 3), round(b.y/self.height, 3))
```

Record the fraction of the Events icon, the "Old Man and the…" entry and its Go/Teleport button. Write them as class constants `EVENTS_ICON`, `OLD_MAN_ENTRY`, `OLD_MAN_GO` and implement `go_to_dock` as: `click_at(*EVENTS_ICON)`, `wait_ocr(match=re.compile('Old Man'))`, `click` it, click go, `wait_until(lambda: self.has_text('Planck|Dock', ...) , time_out=90)`, then `walk_until_f` / send `f` when the F prompt appears (`self.wait_until(self.is_pick_f, time_out=20)` then `self.send_key('f', after_sleep=1.5)`).

- [ ] **Step 5: Implement `pick_premium`, `prepare_and_sail`, `set_time_to_night`**

```python
    def pick_premium(self):
        # Planck dialog -> "Fishing Request"; the Premium tab/entry is at the top of the request list.
        self.wait_ocr(match=re.compile('Fishing Request', re.I), time_out=15, raise_if_not_found=True,
                      settle_time=0.5)
        self.click_ocr_text('Fishing Request')
        self.sleep(1.2)
        if not premium_listed(self.texts(0.0, 0.15, 0.4, 0.5)):
            return False
        self.click_ocr_text('Premium')
        self.sleep(0.8)
        self.click_at(0.88, 0.93)  # Track (about (0.88, 0.93) in the probe session)
        self.sleep(1.0)
        return True

    def click_ocr_text(self, pattern, x=0, y=0, to_x=1, to_y=1):
        regex = re.compile(pattern, re.IGNORECASE)
        for box in self.ocr(x, y, to_x, to_y) or []:
            if regex.search(box.name):
                self.click(box, after_sleep=random.uniform(0.4, 0.7))
                return True
        return False

    def prepare_and_sail(self):
        self.click_ocr_text('Set Sail')
        self.sleep(1.5)
        self.click_at(0.928, 0.256)   # Night
        self.click_at(0.703, 0.796)   # Automatically restore durability
        self.sleep(0.4)
        self.click_at(0.83, 0.93)     # Set Sail
        self.sleep(random.uniform(4.0, 6.0))

    def set_time_to_night(self):
        self.send_key('esc', after_sleep=1.2)
        self.click_at(0.713, 0.958, after_sleep=2.0)  # clock icon
        self.real.drag(0.85, 0.5, 0.15, 0.5, random.uniform(0.8, 1.0))
        self.sleep(0.5)
        self.real.drag(0.91, 0.5, 0.07, 0.5, random.uniform(0.9, 1.1))
        self.sleep(0.5)
        self.click_at(0.5, 0.92, after_sleep=3.0)     # Confirm
        self.send_key('esc', after_sleep=1.0)
```

Verify live (user watching): with the game at the dock, run the task from the GUI up to the end of `prepare_and_sail`. After the run, confirm the boat is at sea with Night selected and 8 hearts. If `Set Sail`'s OCR text differs, use the dump from step 4 to adjust the pattern. Replace the temporary `go_to_dock` body once the constants are recorded.

- [ ] **Step 6: Run unit tests and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestFishingTask.py -v` → PASS.

```bash
git add src/task/FishingTask.py tests/TestFishingTask.py
git commit -m "feat(fishing): dock, premium request, preparation and time reset"
```

---

### Task 8: Sailing controller

**Files:**
- Modify: `src/task/FishingTask.py` (`sail_to_fish`, `objectives_done`, hazard handling)
- Test: `tests/TestFishingTask.py`

**Interfaces:**
- Consumes: `detect.find_marker`, `detect.marker_error_deg`, `detect.heart_px`, `detect.hearts_from_px`, `hi.camera_steps`, `hi.turn_hold_seconds`, `hi.sail_press`, `hi.sweep_plan`, `self.real.rel_move`, `self.set_time_to_night`.
- Produces: `sail_to_fish()` returns when the "[F] Fish" prompt is on screen; raises through `self.fail` on abort. `objectives_done() -> bool`.
- Pure helper (module level, tested): `next_action(error_deg: float, marker_found: bool) -> str` returns `'sweep'` when no marker, `'turn'` when `abs(error_deg) > 4`, else `'forward'`.

- [ ] **Step 1: Write the failing tests**

```python
from src.task.FishingTask import next_action


class TestNextAction(unittest.TestCase):
    def test_no_marker_sweeps(self):
        self.assertEqual('sweep', next_action(0.0, False))

    def test_big_error_turns(self):
        self.assertEqual('turn', next_action(7.5, True))
        self.assertEqual('turn', next_action(-12.0, True))

    def test_small_error_goes_forward(self):
        self.assertEqual('forward', next_action(3.9, True))
        self.assertEqual('forward', next_action(-4.0, True))
```

- [ ] **Step 2: Run to verify it fails** → ImportError.

- [ ] **Step 3: Implement**

Module level:

```python
def next_action(error_deg, marker_found):
    if not marker_found:
        return 'sweep'
    return 'turn' if abs(error_deg) > 4 else 'forward'
```

Methods:

```python
    F_PROMPT = r'\[?F\]?\s*Fish'

    def fish_prompt(self):
        return self.has_text(self.F_PROMPT, 0.45, 0.45, 0.95, 0.8)

    def objectives_done(self):
        done, total = detect.parse_progress(self.texts(0.0, 0.22, 0.26, 0.36))
        self.info_set('progress', f'{done}/{total}')
        return total > 0 and done >= total

    def sail_to_fish(self):
        self.info_set('current task', 'sail to fish')
        base_px = max(detect.heart_px(self.rgb_frame()), 1)
        reset_done = False
        lost_in_row = 0
        stuck = 0
        last_x = None
        while True:
            if self.fish_prompt():
                return
            rgb = self.rgb_frame()
            px = detect.heart_px(rgb)
            if detect.hearts_from_px(px, base_px) <= 2:
                self.fail('hearts too low, aborting')
            if px < base_px * 0.9:
                self.avoid_damage()
                base_px = max(px, 1)
                continue
            marker = detect.find_marker(rgb)
            err = detect.marker_error_deg(marker[0]) if marker else 0.0
            action = next_action(err, marker is not None)
            if action == 'sweep':
                lost_in_row += 1
                if lost_in_row >= 3:
                    if reset_done:
                        self.fail('fish marker not found after a time reset')
                    self.sweep_camera()
                    if detect.find_marker(self.rgb_frame()) is None:
                        self.set_time_to_night()
                        reset_done = True
                    lost_in_row = 0
                continue
            lost_in_row = 0
            if action == 'turn':
                self.turn_camera(err)
            else:
                if last_x is not None and abs(marker[0] - last_x) < 2 and marker[2] > 0:
                    stuck += 1
                else:
                    stuck = 0
                last_x = marker[0]
                if stuck >= 4:
                    self.reverse_and_turn()
                    stuck = 0
                    continue
                self.hold_key('w', hi.sail_press())
            self.sleep(random.uniform(0.3, 0.8))

    def turn_camera(self, error_deg):
        # ~2.3 px of marker shift per mouse unit, ~21 px per degree
        units = int(error_deg * 21.0 / 2.3)
        self.real.focus()
        for dx, dy, delay in hi.camera_steps(units):
            self.real.rel_move(dx, dy)
            self.sleep(delay)

    def sweep_camera(self):
        self.real.focus()
        for dx in hi.sweep_plan():
            for sx, sy, delay in hi.camera_steps(dx):
                self.real.rel_move(sx, sy)
                self.sleep(delay)
            if detect.find_marker(self.rgb_frame()) is not None:
                return

    def reverse_and_turn(self):
        self.hold_key('s', random.uniform(1.0, 2.0))
        self.turn_camera(random.choice([-1, 1]) * random.uniform(40, 50))

    def avoid_damage(self):
        # Land, ghost or tornado: back off, turn about 90 degrees away, continue.
        self.hold_key('s', random.uniform(1.0, 2.0))
        self.turn_camera(random.choice([-1, 1]) * random.uniform(80, 100))
        self.hold_key('w', random.uniform(1.5, 2.5))
```

Note `hearts_from_px(px, full_px=base_px)` uses the observed starting pixel count as the "full" reference, so `<= 2` means a quarter of the starting hearts or less.

- [ ] **Step 4: Run to verify tests pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestFishingTask.py -v` → PASS.

- [ ] **Step 5: Live check (user watching)**

Calibrate the F-prompt and tracker regions with an OCR dump while at sea (prompt visible within ~7 m of a fish): record the true regions and fix `fish_prompt` and `objectives_done` boxes if they differ. Run the task from the sea with a target on screen; expect it to arrive and stop at the prompt. Watch for: no straight-line identical key holds in `logs/ok-ww.log`, hearts not dropping, no middle-click anywhere (`grep -n "middle" src/task/FishingTask.py` returns nothing).

- [ ] **Step 6: Commit**

```bash
git add src/task/FishingTask.py tests/TestFishingTask.py
git commit -m "feat(fishing): marker-steered sailing with damage avoidance"
```

---

### Task 9: Fish mini-game and Catches screen / cargo

**Files:**
- Modify: `src/task/FishingTask.py` (`fish`, `handle_catches`, shape reading)
- Create: `src/fishing/cargo_grid.py` (grid geometry and preview reading)
- Test: `tests/TestCargoGrid.py`

**Interfaces:**
- Produces in `cargo_grid.py`:
  - `GRID_ORIGIN`, `CELL_PX`, `GRID_ROWS`, `GRID_COLS`, `BLOCKED: frozenset[Cell]` measured in step 1
  - `cell_center(row: int, col: int) -> tuple[float, float]` fractions of 1920x1080
  - `read_preview(before: np.ndarray, after: np.ndarray, threshold: float = 18.0) -> frozenset[Cell]` cells whose mean absolute RGB difference exceeds `threshold`
  - `free_cells(occupied: Iterable[Cell]) -> set[Cell]` all grid cells minus `BLOCKED` minus `occupied`
- Produces in the task: `fish()`, `handle_catches()`, and `self.occupied: set[Cell]` reset in `run` before the loop.

- [ ] **Step 1: Measure the grid (live)**

Open the Catches screen (the probe run showed it opens after the "Fishing Complete" blank click). Save a full-resolution frame (`self.screenshot('cargo_empty')`) to `tests/images/fishing/cargo_empty.png`, and one after clicking a fish card to `tests/images/fishing/cargo_preview.png`. From `cargo_empty.png` read the pixel position of the top-left grid cell, the cell pitch (about 110 px), the row/column counts, and which corner cells are blocked. Write them into `cargo_grid.py` as constants. Commit the two images (they are small).

- [ ] **Step 2: Write the failing tests**

```python
import unittest

import cv2
import numpy as np

from src.fishing import cargo_grid as cg


class TestCargoGrid(unittest.TestCase):
    def test_cell_center_inside_screen(self):
        x, y = cg.cell_center(0, 0)
        self.assertTrue(0 < x < 1 and 0 < y < 1)
        x2, y2 = cg.cell_center(1, 1)
        self.assertGreater(x2, x)
        self.assertGreater(y2, y)

    def test_free_cells_excludes_blocked_and_occupied(self):
        free = cg.free_cells({(3, 3)})
        self.assertNotIn((3, 3), free)
        self.assertTrue(cg.BLOCKED.isdisjoint(free))
        self.assertEqual(cg.GRID_ROWS * cg.GRID_COLS - len(cg.BLOCKED) - 1, len(free))

    def test_read_preview_on_synthetic_cells(self):
        before = np.full((1080, 1920, 3), 30, np.uint8)
        after = before.copy()
        for r, c in [(2, 2), (3, 2), (4, 2), (4, 3)]:
            x, y = cg.cell_center(r, c)
            cv2.rectangle(after, (int(x * 1920) - 30, int(y * 1080) - 30),
                          (int(x * 1920) + 30, int(y * 1080) + 30), (90, 160, 230), -1)
        self.assertEqual(frozenset({(2, 2), (3, 2), (4, 2), (4, 3)}), cg.read_preview(before, after))

    def test_read_preview_ignores_identical_frames(self):
        img = np.full((1080, 1920, 3), 30, np.uint8)
        self.assertEqual(frozenset(), cg.read_preview(img, img))

    def test_real_fixture_preview_is_a_piece(self):
        before = cv2.cvtColor(cv2.imread("tests/images/fishing/cargo_empty.png"), cv2.COLOR_BGR2RGB)
        after = cv2.cvtColor(cv2.imread("tests/images/fishing/cargo_preview.png"), cv2.COLOR_BGR2RGB)
        cells = cg.read_preview(before, after)
        self.assertIn(len(cells), (4, 5))
```

- [ ] **Step 3: Run to verify it fails** → ImportError.

- [ ] **Step 4: Implement `cargo_grid.py`**

```python
from typing import FrozenSet, Iterable, Set, Tuple

import numpy as np

Cell = Tuple[int, int]

# Measured from tests/images/fishing/cargo_empty.png in Step 1 (1920x1080 pixels).
GRID_ORIGIN = (0, 0)   # x, y of the top-left corner of cell (0, 0)  -- set in Step 1
CELL_PX = 110          # cell pitch                                  -- confirm in Step 1
GRID_ROWS = 7          # confirm in Step 1
GRID_COLS = 8          # confirm in Step 1
BLOCKED: FrozenSet[Cell] = frozenset()  # corner cells shown as unusable -- set in Step 1


def cell_center(row: int, col: int) -> Tuple[float, float]:
    x = GRID_ORIGIN[0] + (col + 0.5) * CELL_PX
    y = GRID_ORIGIN[1] + (row + 0.5) * CELL_PX
    return x / 1920.0, y / 1080.0


def free_cells(occupied: Iterable[Cell]) -> Set[Cell]:
    all_cells = {(r, c) for r in range(GRID_ROWS) for c in range(GRID_COLS)}
    return all_cells - set(BLOCKED) - set(occupied)


def read_preview(before: np.ndarray, after: np.ndarray, threshold: float = 18.0) -> FrozenSet[Cell]:
    found = set()
    margin = CELL_PX // 4
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            x0 = int(GRID_ORIGIN[0] + c * CELL_PX) + margin
            y0 = int(GRID_ORIGIN[1] + r * CELL_PX) + margin
            x1 = int(GRID_ORIGIN[0] + (c + 1) * CELL_PX) - margin
            y1 = int(GRID_ORIGIN[1] + (r + 1) * CELL_PX) - margin
            diff = np.abs(before[y0:y1, x0:x1].astype(int) - after[y0:y1, x0:x1].astype(int)).mean()
            if diff > threshold:
                found.add((r, c))
    return frozenset(found)
```

Before the tests can pass, replace the five "set in Step 1" constants with the measured values. The synthetic tests assume the whole grid lies inside the 1920x1080 frame. `BLOCKED` must hold the real blocked cells so that `GRID_ROWS * GRID_COLS - len(BLOCKED) == 52`: add `self.assertEqual(52, cg.GRID_ROWS * cg.GRID_COLS - len(cg.BLOCKED))` to the tests and make it pass.

- [ ] **Step 5: Implement `fish` and `handle_catches`**

```python
    def fish(self):
        self.info_set('current task', 'fishing')
        self.send_key('f', after_sleep=random.uniform(0.6, 1.2))
        if not self.wait_until(lambda: self.has_text('Fishing Complete'), time_out=60, raise_if_not_found=False):
            self.fail('mini-game did not complete')
        self.sleep(random.uniform(0.6, 1.2))
        self.click_at(0.5, 0.78)   # blank area closes the result
        self.sleep(random.uniform(1.0, 1.6))

    def handle_catches(self):
        if not self.wait_until(lambda: self.has_text('Cargo|Catch List', 0, 0, 1, 0.15), time_out=8,
                               raise_if_not_found=False):
            return
        needed = self.needed_fish_cards()
        for card_x, card_y in needed:
            self.place_fish(card_x, card_y)
        self.click_at(0.293, 0.91)  # Finish
        self.sleep(random.uniform(1.0, 1.6))

    def needed_fish_cards(self):
        # Cards of the request fish: the left list. Cards the request needs carry the "needed" tag;
        # read from the Request Overview text under the list.
        return [(0.094, 0.24), (0.212, 0.25)]

    def place_fish(self, card_x, card_y):
        before = self.rgb_frame()
        self.click_at(card_x, card_y, after_sleep=0.8)
        after = self.rgb_frame()
        cells = cg.read_preview(before, after)
        if not cells:
            return
        free = cg.free_cells(self.occupied)
        plan = pack(free, {'fish': cells})
        if plan is None:
            self.log_info('no room in cargo for this fish; leaving it for Sell All')
            return
        placement = plan['fish']
        for _ in range(placement.rotations):
            self.send_key('r', after_sleep=random.uniform(0.3, 0.6))
        if placement.rotations:
            cells = cg.read_preview(before, self.rgb_frame())
        cur_r = min(r for r, _ in cells)
        cur_c = min(c for _, c in cells)
        if not self.preview_is_green():
            src = cg.cell_center(*sorted(cells)[0])
            offset = sorted(cells)[0]
            dst_cell = (placement.origin[0] + offset[0] - cur_r, placement.origin[1] + offset[1] - cur_c)
            dst = cg.cell_center(*dst_cell)
            self.real.drag(src[0], src[1], dst[0], dst[1], random.uniform(0.8, 1.1))
            self.sleep(0.6)
        self.send_key('space', after_sleep=random.uniform(0.5, 0.9))
        self.occupied |= set(placement.cells)
```

`preview_is_green` uses `cg.grid_slice()` and the green/red thresholds below; Step 1 confirms them against fixtures of a green and a red preview (save both as `tests/images/fishing/cargo_green.png` and `cargo_red.png` and add a test asserting `True`/`False`):

```python
    def preview_is_green(self):
        rgb = self.rgb_frame()
        region = rgb[cg.grid_slice()]
        green = ((region[..., 1] > 150) & (region[..., 0] < 120) & (region[..., 2] < 140)).sum()
        red = ((region[..., 0] > 190) & (region[..., 1] < 90) & (region[..., 2] < 90)).sum()
        return green > red and green > 400
```

In Step 1, measure green and red preview colours from a green and a red preview frame and replace those thresholds; write them as constants in `cargo_grid.py` (`GRID_SLICE`, `GREEN_RGB_RANGE`, `RED_RGB_RANGE`) with a test using the fixtures. Add `grid_slice() -> tuple[slice, slice]` to `cargo_grid.py`, built from `GRID_ORIGIN`, `CELL_PX`, `GRID_ROWS`, `GRID_COLS`.

Add `from src.fishing import cargo_grid as cg` to `FishingTask.py` and `self.occupied = set()` before the loop in `run`.

- [ ] **Step 6: Run tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestCargoGrid.py tests/TestCargoPacker.py -v` → PASS.

- [ ] **Step 7: Live check (user watching)**

Catch one fish on the water, let `handle_catches` run, and confirm the piece sits in the grid, Finish closes the screen, and the unplaced fish remain in the Catch List. Check the log shows no overlapping drags and that the drag is not a fixed path.

- [ ] **Step 8: Commit**

```bash
git add src/fishing/cargo_grid.py src/task/FishingTask.py tests/TestCargoGrid.py tests/images/fishing
git commit -m "feat(fishing): fish mini-game and cargo placement"
```

---

### Task 9b: Value-optimised cargo (gated by a live check)

**Gate (live, before any code):** after delivering a request with one extra fish placed in the cargo, open the Dock Shop and Sell All. Record whether (a) the extra placed fish is still in the cargo, (b) it was sold, or (c) it was lost. If (a) or (c), stop: the optimiser must not place non-request fish, and this task is dropped (the simple packer from Task 9 stays). If (b), continue.

**Files:**
- Modify: `src/task/FishingTask.py` (`handle_catches` survey pass)
- Modify: `src/fishing/cargo_grid.py` (`read_value`, `selected_name` regions)
- Test: `tests/TestCargoGrid.py`

**Interfaces:**
- Consumes: `pack_best`, `cg.read_preview`, `cg.free_cells`.
- Produces: `parse_value(texts: list[str]) -> int | None` in `cargo_grid.py`: first integer found in the price text, ignoring thousands separators; `None` if none.

- [ ] **Step 1: Write the failing test**

```python
def test_parse_value(self):
    self.assertEqual(1240, cg.parse_value(["Price", "1,240"]))
    self.assertEqual(95, cg.parse_value(["Price 95"]))
    self.assertIsNone(cg.parse_value(["Size", "Micro"]))
```

- [ ] **Step 2: Run to verify it fails** → AttributeError.

- [ ] **Step 3: Implement**

```python
import re

def parse_value(texts):
    for text in texts:
        m = re.search(r'\d[\d,]*', text)
        if m:
            return int(m.group(0).replace(',', ''))
    return None
```

- [ ] **Step 4: Survey pass (live-verified)**

In `handle_catches`, before placing anything: for each card, click it, OCR the detail panel (name and price; region measured live and stored as `cg.DETAIL_REGION`), read the preview shape, then deselect (measured live: clicking the same card again, or Esc; record which works in `cg.DESELECT` and verify the card is unhighlighted). Cache shapes by fish name so a repeated species is not re-surveyed. Then:

```python
plan = pack_best(cg.free_cells(self.occupied), shapes, values, required=request_fish)
```

`request_fish` are the names the tracker asks for (parsed from the objective lines). Place each planned fish in order (`place_fish` from Task 9, using its `Placement`); fish not in the plan stay in the Catch List for Sell All. If `plan` is `None` (a request fish does not fit), `fail('request fish does not fit the cargo')`.

- [ ] **Step 5: Live check (user watching)**

With four or more fish caught, confirm: request fish are placed first, extra fish are placed only where they fit and only if the gate said they are sold, and no fish is left selected before Finish.

- [ ] **Step 6: Commit**

```bash
git add src/fishing/cargo_grid.py src/task/FishingTask.py tests/TestCargoGrid.py
git commit -m "feat(fishing): value-optimised cargo placement"
```

---

### Task 10: Deliver and Sell All

**Files:**
- Modify: `src/task/FishingTask.py` (`deliver`, `sell_all`)

**Interfaces:**
- Produces: `deliver()` ends at the dock hub; `sell_all()` ends at the dock hub with the Catch List showing "No Catch".

- [ ] **Step 1: Write the failing test**

```python
class TestSellText(unittest.TestCase):
    def test_no_catch_detected(self):
        from src.task.FishingTask import catch_list_empty
        self.assertTrue(catch_list_empty(["Catch List", "No Catch"]))
        self.assertFalse(catch_list_empty(["Catch List", "Giant Gulper"]))
```

- [ ] **Step 2: Run to verify it fails** → ImportError.

- [ ] **Step 3: Implement**

Module level:

```python
def catch_list_empty(texts):
    return any('no catch' in t.lower() for t in texts)
```

Methods:

```python
    def deliver(self):
        self.info_set('current task', 'deliver')
        self.send_key(self.key_config.get('Tool Key'), after_sleep=1.5)
        self.click_at(0.657, 0.628, after_sleep=2.0)       # Confirm fast travel to the dock
        self.wait_until(lambda: self.has_text('Return to the dock'), time_out=60)
        self.send_key('f', after_sleep=2.5)
        self.click_at(0.2375, 0.296, after_sleep=1.0)      # request "..."
        self.click_at(0.875, 0.902, after_sleep=2.0)       # Deliver
        self.click_at(0.5, 0.85, after_sleep=1.5)          # close rewards

    def sell_all(self):
        self.info_set('current task', 'sell all')
        self.click_at(0.835, 0.93, after_sleep=2.0)        # Dock Shop
        self.send_key('c', after_sleep=1.2)                # Catch List
        if catch_list_empty(self.texts(0, 0, 0.5, 1)):
            self.send_key('esc', after_sleep=1.0)
            return
        if self.has_text('handle the selected item'):
            self.release_selected_fish()
        self.click_at(0.72, 0.91, after_sleep=1.2)         # Sell All
        if self.has_text('Request items for sale'):
            self.click_at(0.657, 0.628, after_sleep=1.5)   # Confirm
        self.click_at(0.5, 0.85, after_sleep=1.5)          # close "Items Obtained"
        if not catch_list_empty(self.texts(0, 0, 0.5, 1)):
            self.fail('Catch List not empty after Sell All')
        self.send_key('esc', after_sleep=1.0)

    def release_selected_fish(self):
        # A selected fish blocks Sell All: drop it on the first free cell.
        cells = sorted(cg.free_cells(self.occupied))
        if not cells:
            return
        dst = cg.cell_center(*cells[0])
        self.real.drag(0.2, 0.25, dst[0], dst[1], random.uniform(0.8, 1.1))
        self.sleep(0.8)
```

`release_selected_fish` takes its drag source from the selected piece's current position; the shop-screen coordinates are recorded in the live check below and the `(0.2, 0.25)` start replaced by the measured cell.

- [ ] **Step 4: Run test** → PASS.

- [ ] **Step 5: Live check (user watching)**

From the point where objectives are complete, run `deliver` and `sell_all`. Confirm the rewards were collected, gold increased, and the Catch List reads "No Catch". Never click the top-right X at the dock hub.

- [ ] **Step 6: Commit**

```bash
git add src/task/FishingTask.py tests/TestFishingTask.py
git commit -m "feat(fishing): deliver the request and sell all fish"
```

---

### Task 11: Full live run and cleanup

**Files:**
- Modify: `docs/superpowers/specs/2026-10-14-fishing-task-design.md` (steps 5–6: Catches screen opens after each fish and cargo runs there; objectives checked from the tracker)

- [ ] **Step 1: Run the full suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestCargoPacker.py tests/TestHumanInput.py tests/TestFishingDetect.py tests/TestRealInput.py tests/TestCargoGrid.py tests/TestFishingTask.py tests/TestConfig.py -v`
Expected: PASS.

- [ ] **Step 2: Full live run from the open world (user watching)**

Start the project elevated (`run_main_admin.bat`), pick FishingTask in the GUI. Expect: dock → Premium → Night + restore durability → sail → fish ×2 → cargo → deliver → Sell All → "No Catch". Record any hearts lost and where. If the Premium request is refreshing, the task must stop with the "nothing to do" message.

- [ ] **Step 3: Update the spec flow note and commit**

Edit spec steps 5–6 to say the Catches screen opens after each "Fishing Complete" click and cargo is handled there, and objectives are read from the tracker `(n/m)` text.

```bash
git add docs/superpowers/specs/2026-10-14-fishing-task-design.md
git commit -m "docs: align fishing spec with observed Catches flow"
```

- [ ] **Step 4: Clean up**

Remove nothing under `.tmp/` automatically. Tell the user the throwaway probes in `.tmp/fish_probe/` and the elevated helper are not part of the product and can be deleted.
