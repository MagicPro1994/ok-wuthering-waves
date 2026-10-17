# BaitFishingTask Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A one-time task that repeats launch Sandworm bait, catch the fish, load the cargo, return to the dock, sell all, set sail, until the bait count reaches 0.

**Architecture:** `BaitFishingTask(FishingTask)` reuses the existing dock, set-sail, sell, input and heart helpers. Everything testable without the game lives in three small pure modules: `bait_logic.py` (OCR parsing, prompt state, no-progress guard), `cargo_grid.py` (cargo grid geometry, preview and occupancy reading) and `cargo_plan.py` (value-optimised placement and drag targets). The game-facing states are verified live by the user watching.

**Tech Stack:** Python, `ok` framework (OCR, `send_key`, `click_relative`, `scroll_relative`), OpenCV, NumPy, `unittest`/pytest. Run Python with `.\.venv\Scripts\python.exe`.

**Spec:** `docs/superpowers/specs/2026-10-14-bait-fishing-design.md` (the Premium task design is `2026-10-14-fishing-task-design.md`; its helpers are reused).

## Global Constraints

- Human-like input: random key holds and pauses, offset clicks, no fixed-interval polling.
- Tool Key must be `t` (`check_tool_key`); the game and the project run elevated; drags use `RealInput`.
- Every state has a timeout; on a timeout, an unexpected dialog, low hearts or a round with no progress: `self.fail(...)` (screenshot, notify, raise).
- Never press Esc blindly (system menu); the dock's top-right X is Disembark.
- Cargo grid: 8 columns by 7 rows, corner cells `(0,0) (0,7) (6,0) (6,7)` blocked, 52 usable cells. Measured on `tests/images/fishing/cargo_empty.png` (1920x1080): origin `(896.5, 154.5)`, pitch `111.0`, empty cell colour RGB `(52, 52, 52)`.
- No Claude/Anthropic attribution in commit messages.
- Use `pnpm` only for Node work (none expected here).

## Review Focus

- Bait count unreadable (OCR returns nothing or `0/3` only): the task fails with a message, it does not launch blindly. (Task 2, Task 8)
- Bait count does not drop after a round (launch did nothing): stop after two such rounds. (Task 2, Task 8)
- More fish than the cargo holds: the packer keeps the highest-value set, the rest stay in the Catch List and Sell All sells them. (Task 4)
- Preview rotation direction differs from `rotate_cw`: rotation is verified by re-reading the preview, not counted. (Task 4, Task 7)
- A card slot past the last fish shows no preview: the survey stops there instead of looping. (Task 7)
- Dock prompt never disappears or never returns: bounded nudges then `fail`. (Task 6, Task 8)
- Sweet Puff owned but count 0: take the manual path, not a failure. (Task 5)

---

## File Structure

| File | Responsibility |
|---|---|
| `src/fishing/bait_ui.py` | UI constants: utility wheel slots, count box, prompt box, confirm and finish positions (measured in Task 1) |
| `src/fishing/bait_logic.py` | pure: `parse_count`, `dialog_open`, `sandworm_launched`, `prompt_state`, `entry_selected`, `RoundGuard` |
| `src/fishing/cargo_grid.py` | pure: grid geometry, `cell_center`, `free_cells`, `read_preview`, `occupied_cells`, `parse_value`, card slot geometry |
| `src/fishing/cargo_plan.py` | pure: `Catch`, `plan_cargo`, `shape_matches`, `grab_and_drop` |
| `src/fishing/human_input.py` | add `nudge_press` |
| `src/task/BaitFishingTask.py` | the task (subclass of `FishingTask`) |
| `config.py` | register the task |
| `tests/TestBaitLogic.py`, `tests/TestCargoGrid.py`, `tests/TestCargoPlan.py`, `tests/TestBaitFishingTask.py` | tests |
| `tests/images/fishing/` | fixtures captured in Task 1 |

---

### Task 1: Probe the live game and capture fixtures (manual, user present)

**Files:**
- Create: `tests/images/fishing/bait_*.png`, `cargo_cards.png`, `cargo_preview_green.png`, `cargo_preview_red.png` (names below)
- Create: `src/fishing/bait_ui.py`
- Create: `.tmp/bait_probe_notes.md` (local scratch, not committed)

**Interfaces:**
- Produces `src/fishing/bait_ui.py` constants used by every later task:
  - `UTILITY_SLOTS: dict[str, tuple[float, float]]` keys `'baiting'`, `'sweet_puff'` (fractions of the client, where Tab shows each utility image)
  - `WHEEL_CLOSES_ON_PICK: bool`
  - `COUNT_BOX: tuple[float, float, float, float]` (x, y, to_x, to_y) OCR box around the bait count on the bottom-right utility icon
  - `PROMPT_BOX = (0.45, 0.45, 0.95, 0.8)` OCR box of the `[F]` prompt list; `PROMPT_SCROLL_AT: tuple[float, float]`; `SCROLL_DOWN: int` (the `count` argument that scrolls the list to the next entry)
  - `CONFIRM_AT: tuple[float, float]` Confirm on "Use Sandworm as bait?"
  - `FISHING_COMPLETE_CLOSE_AT = (0.5, 0.78)`
  - `FINISH_AT: tuple[float, float]` Finish on the Catches screen

- [ ] **Step 1: Start the game at sea next to the dock with bait in stock, elevated project running.** Use the existing `tests/images/fishing/` naming; take full-resolution frames with a one-off script in the scratchpad or with the task's `self.screenshot(name)`.

- [ ] **Step 2: Capture and note the utility wheel.** Press Tab. Save `bait_wheel.png`. Note the pixel centre of the Baiting image and the Sweet Puff image (divide by 1920x1080 for fractions). Click one: note whether the wheel closes by itself (`WHEEL_CLOSES_ON_PICK`) or needs Tab again. Save `bait_icon_baiting.png` (icon with bait count) and, with Sweet Puff equipped, `bait_icon_puff.png`. Note the pixel box around the count digits (not the `0/3`).

- [ ] **Step 3: Capture the dock and fish prompts.** Save `bait_dock_prompt.png` (only `[F] Return to the dock`), then after launching bait and moving 2-3 W, `bait_fish_prompt.png` (the `[F] Fish` entry below `Return to the dock`). Note which entry is selected by default, how the selected entry looks (the `F` key badge next to it), and which wheel direction selects `Fish` (record the integer `SCROLL_DOWN` for `scroll_relative`: try `-1` and `1`).

- [ ] **Step 4: Capture the Use Bait dialog and result screens.** `bait_dialog.png` (Confirm position), the "Sandworm launched" message `bait_launched.png`, `fishing_complete.png`, and the screen after the normal mini-game.

- [ ] **Step 5: Capture the Catches screen.** `cargo_cards.png` (cards list, before any click), then click the first card: `cargo_preview_green.png` or `cargo_preview_red.png` (whichever the default shows; produce the other by dragging the preview onto a taken cell). Note: where the cards are (first card centre, pitch in x and y, how many columns), whether a card shows its value text, whether previews of earlier cards vanish when another card is clicked, whether a placed card leaves the list, the Finish button position, the R key rotates clockwise or counter-clockwise.

- [ ] **Step 6: Write `src/fishing/bait_ui.py`** with the measured values (replace every value below with what you measured; the numbers shown are the best current estimates):

```python
# Fractions of the 1920x1080 client unless noted. Measured live (see tests/images/fishing/bait_*.png).
UTILITY_SLOTS = {'baiting': (0.50, 0.50), 'sweet_puff': (0.60, 0.50)}
WHEEL_CLOSES_ON_PICK = True
COUNT_BOX = (0.88, 0.74, 0.97, 0.86)
PROMPT_BOX = (0.45, 0.45, 0.95, 0.8)
PROMPT_SCROLL_AT = (0.7, 0.6)
SCROLL_DOWN = -1
CONFIRM_AT = (0.79, 0.855)
FISHING_COMPLETE_CLOSE_AT = (0.5, 0.78)
FINISH_AT = (0.293, 0.91)
```

- [ ] **Step 7: Commit the fixtures and constants.**

```bash
git add src/fishing/bait_ui.py tests/images/fishing
git commit -m "feat(fishing): capture bait UI fixtures and constants"
```

---

### Task 2: Bait logic (pure)

**Files:**
- Create: `src/fishing/bait_logic.py`
- Modify: `src/fishing/human_input.py` (add `nudge_press`)
- Test: `tests/TestBaitLogic.py`

**Interfaces:**
- Produces:
  - `parse_count(texts: Iterable[str]) -> Optional[int]`: first text that is only digits (1-5), ignores `0/3` and `T`.
  - `dialog_open(texts) -> bool`: both `use` and `bait` appear (case-insensitive) in the joined text.
  - `sandworm_launched(texts) -> bool`: `launched` appears in any text.
  - `prompt_state(texts) -> PromptState` (`NamedTuple` with `return_dock: bool`, `fish: bool`).
  - `entry_selected(boxes, pattern) -> Optional[bool]`: `boxes` are `(text, y)` pairs in fractions; `None` when no box matches `pattern`; `True` when an `F` key box lies within 0.025 of the matching box's y.
  - `RoundGuard(max_stalls=2)` with `record(before: int, after: int) -> bool` (False when the loop must stop).
  - `human_input.nudge_press(rng=random) -> float` uniform 0.35 to 0.8.

- [ ] **Step 1: Write the failing tests** in `tests/TestBaitLogic.py`:

```python
import random
import unittest

from src.fishing import human_input as hi
from src.fishing.bait_logic import (RoundGuard, dialog_open, entry_selected, parse_count, prompt_state,
                                    sandworm_launched)


class TestParseCount(unittest.TestCase):
    def test_reads_the_count_and_skips_ratio_and_key(self):
        self.assertEqual(189, parse_count(["189", "0/3", "T"]))

    def test_count_zero_is_zero_not_none(self):
        self.assertEqual(0, parse_count(["0", "0/3"]))

    def test_unreadable_is_none(self):
        self.assertIsNone(parse_count(["0/3", "T"]))
        self.assertIsNone(parse_count([]))

    def test_ignores_digits_inside_words(self):
        self.assertIsNone(parse_count(["x2 speed"]))


class TestMessages(unittest.TestCase):
    def test_dialog(self):
        self.assertTrue(dialog_open(["Use Bait", "Use Sandworm as bait?", "Cancel", "Confirm"]))
        self.assertFalse(dialog_open(["Fishing Complete"]))

    def test_launched(self):
        self.assertTrue(sandworm_launched(["Sandworm launched"]))
        self.assertFalse(sandworm_launched(["Sandworm", "1"]))


class TestPromptState(unittest.TestCase):
    def test_return_only(self):
        s = prompt_state(["[F] Return to the dock"])
        self.assertTrue(s.return_dock)
        self.assertFalse(s.fish)

    def test_both(self):
        s = prompt_state(["Return to the dock", "Fish"])
        self.assertTrue(s.return_dock and s.fish)

    def test_fishing_complete_is_not_a_fish_prompt(self):
        self.assertFalse(prompt_state(["Fishing Complete"]).fish)

    def test_nothing(self):
        s = prompt_state([])
        self.assertFalse(s.return_dock or s.fish)


class TestEntrySelected(unittest.TestCase):
    def test_selected_when_key_badge_on_same_row(self):
        boxes = [("F", 0.60), ("Fish", 0.605), ("Return to the dock", 0.54)]
        self.assertTrue(entry_selected(boxes, r"^Fish$"))
        self.assertFalse(entry_selected(boxes, r"Return to the dock"))

    def test_missing_entry_is_none(self):
        self.assertIsNone(entry_selected([("F", 0.5)], r"^Fish$"))


class TestRoundGuard(unittest.TestCase):
    def test_a_drop_resets_the_stalls(self):
        g = RoundGuard(2)
        self.assertTrue(g.record(10, 10))
        self.assertTrue(g.record(10, 9))
        self.assertTrue(g.record(9, 9))

    def test_two_stalls_in_a_row_stop(self):
        g = RoundGuard(2)
        self.assertTrue(g.record(10, 10))
        self.assertFalse(g.record(10, 11))


class TestNudge(unittest.TestCase):
    def test_nudge_press_is_short_and_uneven(self):
        values = {hi.nudge_press(random.Random(i)) for i in range(20)}
        self.assertTrue(all(0.35 <= v <= 0.8 for v in values))
        self.assertGreater(len(values), 10)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestBaitLogic.py -v`
Expected: FAIL (ImportError: `src.fishing.bait_logic`).

- [ ] **Step 3: Implement** `src/fishing/bait_logic.py`:

```python
import re
from typing import Iterable, NamedTuple, Optional, Sequence, Tuple

_COUNT = re.compile(r'\d{1,5}')
_FISH = re.compile(r'(?<![A-Za-z])Fish(?![A-Za-z])')


def parse_count(texts: Iterable[str]) -> Optional[int]:
    for text in texts:
        value = text.strip()
        if _COUNT.fullmatch(value):
            return int(value)
    return None


def dialog_open(texts: Iterable[str]) -> bool:
    joined = ' '.join(texts).lower()
    return 'use' in joined and 'bait' in joined


def sandworm_launched(texts: Iterable[str]) -> bool:
    return any('launched' in text.lower() for text in texts)


class PromptState(NamedTuple):
    return_dock: bool
    fish: bool


def prompt_state(texts: Iterable[str]) -> PromptState:
    texts = list(texts)
    return PromptState(
        return_dock=any(re.search(r'return\s+to\s+the\s+dock', t, re.IGNORECASE) for t in texts),
        fish=any(_FISH.search(t) for t in texts),
    )


def entry_selected(boxes: Sequence[Tuple[str, float]], pattern: str) -> Optional[bool]:
    """Whether the prompt entry matching `pattern` carries the F key badge (is the selected one).

    `boxes` are OCR (text, y centre) pairs of the prompt list in fractions of the frame height.
    """
    regex = re.compile(pattern, re.IGNORECASE)
    rows = [y for text, y in boxes if regex.search(text.strip())]
    if not rows:
        return None
    keys = [y for text, y in boxes if text.strip().strip('[]').upper() == 'F']
    return any(abs(key - rows[0]) < 0.025 for key in keys)


class RoundGuard:
    """Stops the loop when the bait count has not dropped for `max_stalls` rounds in a row."""

    def __init__(self, max_stalls: int = 2):
        self.max_stalls = max_stalls
        self.stalls = 0

    def record(self, before: int, after: int) -> bool:
        self.stalls = self.stalls + 1 if after >= before else 0
        return self.stalls < self.max_stalls
```

Add to `src/fishing/human_input.py` (after `approach_press`):

```python
def nudge_press(rng=_random):
    return rng.uniform(0.35, 0.8)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestBaitLogic.py tests/TestHumanInput.py -v`
Expected: PASS.

- [ ] **Step 5: Check against the live fixtures from Task 1.** Add a test that OCR-free fixtures are consistent is not possible without OCR; instead, in the live task (Task 5) verify `parse_count` against the real OCR output of `bait_icon_baiting.png` and fix the regex there if the count is read with extra characters. Commit.

```bash
git add src/fishing/bait_logic.py src/fishing/human_input.py tests/TestBaitLogic.py
git commit -m "feat(fishing): bait logic helpers and round guard"
```

---

### Task 3: Cargo grid geometry and screen reading (pure)

**Files:**
- Create: `src/fishing/cargo_grid.py`
- Test: `tests/TestCargoGrid.py`

**Interfaces:**
- Produces:
  - `Cell = Tuple[int, int]`; `GRID_ORIGIN = (896.5, 154.5)`, `CELL_PX = 111.0`, `GRID_ROWS = 7`, `GRID_COLS = 8`, `BLOCKED`, `EMPTY_RGB = (52, 52, 52)`
  - `cell_center(row, col) -> Tuple[float, float]` fractions of 1920x1080
  - `free_cells(occupied: Iterable[Cell]) -> Set[Cell]`
  - `read_preview(before, after, threshold=18.0) -> FrozenSet[Cell]` cells whose interior changed between two RGB frames
  - `occupied_cells(rgb, threshold=18.0) -> FrozenSet[Cell]` non-blocked cells whose interior differs from `EMPTY_RGB`
  - `parse_value(texts) -> Optional[int]` first integer in the texts, commas ignored
  - Card geometry measured from `cargo_cards.png`: `CARD_ORIGIN`, `CARD_PITCH`, `CARD_COLS`, `MAX_CARDS`; `card_center(slot) -> Tuple[float, float]` and `card_box(slot) -> Tuple[float, float, float, float]` (fractions)

- [ ] **Step 1: Write the failing tests** in `tests/TestCargoGrid.py`:

```python
import unittest

import cv2
import numpy as np

from src.fishing import cargo_grid as cg


def fixture(name):
    return cv2.cvtColor(cv2.imread(f"tests/images/fishing/{name}"), cv2.COLOR_BGR2RGB)


def paint(img, cells, colour=(90, 160, 230)):
    out = img.copy()
    for r, c in cells:
        x, y = cg.cell_center(r, c)
        cx, cy = int(x * 1920), int(y * 1080)
        cv2.rectangle(out, (cx - 30, cy - 30), (cx + 30, cy + 30), colour, -1)
    return out


class TestGeometry(unittest.TestCase):
    def test_usable_cells_are_52(self):
        self.assertEqual(52, len(cg.free_cells(set())))

    def test_blocked_corners(self):
        self.assertEqual({(0, 0), (0, 7), (6, 0), (6, 7)}, set(cg.BLOCKED))

    def test_free_cells_exclude_occupied(self):
        self.assertNotIn((3, 3), cg.free_cells({(3, 3)}))
        self.assertEqual(51, len(cg.free_cells({(3, 3)})))

    def test_cell_center_is_inside_the_cell(self):
        x, y = cg.cell_center(1, 1)
        self.assertAlmostEqual(1062.5 / 1920, x, places=3)
        self.assertAlmostEqual(320.5 / 1080, y, places=3)

    def test_real_fixture_free_cell_centres_are_empty_grey(self):
        img = fixture("cargo_empty.png")
        for r, c in cg.free_cells(set()):
            x, y = cg.cell_center(r, c)
            pixel = img[int(y * 1080), int(x * 1920)].astype(int)
            self.assertTrue(all(abs(v - 52) < 8 for v in pixel), (r, c, pixel))


class TestPreview(unittest.TestCase):
    def test_reads_painted_cells(self):
        before = fixture("cargo_empty.png")
        cells = [(2, 2), (3, 2), (4, 2), (4, 3)]
        self.assertEqual(frozenset(cells), cg.read_preview(before, paint(before, cells)))

    def test_identical_frames_have_no_preview(self):
        img = fixture("cargo_empty.png")
        self.assertEqual(frozenset(), cg.read_preview(img, img))


class TestOccupied(unittest.TestCase):
    def test_empty_cargo_has_no_occupied_cells(self):
        self.assertEqual(frozenset(), cg.occupied_cells(fixture("cargo_empty.png")))

    def test_painted_cells_are_occupied(self):
        img = paint(fixture("cargo_empty.png"), [(1, 1), (5, 6)])
        self.assertEqual(frozenset({(1, 1), (5, 6)}), cg.occupied_cells(img))


class TestParseValue(unittest.TestCase):
    def test_values(self):
        self.assertEqual(1240, cg.parse_value(["Price", "1,240"]))
        self.assertEqual(95, cg.parse_value(["Price 95"]))
        self.assertIsNone(cg.parse_value(["Size", "Micro"]))


class TestCards(unittest.TestCase):
    def test_card_slots_are_inside_the_left_panel_and_distinct(self):
        centres = [cg.card_center(i) for i in range(cg.MAX_CARDS)]
        self.assertEqual(len(centres), len(set(centres)))
        for x, y in centres:
            self.assertTrue(0 < x < 0.5 and 0 < y < 1)

    def test_card_box_contains_its_centre(self):
        x, y = cg.card_center(0)
        x0, y0, x1, y1 = cg.card_box(0)
        self.assertTrue(x0 < x < x1 and y0 < y < y1)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestCargoGrid.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Measure the card geometry** from `tests/images/fishing/cargo_cards.png` (Task 1): first card centre in pixels, pitch in x and y, number of columns, how many slots to scan (`MAX_CARDS`, 12 unless the screen shows fewer). Record them as the constants below.

- [ ] **Step 4: Implement** `src/fishing/cargo_grid.py`:

```python
import re
from typing import FrozenSet, Iterable, Optional, Set, Tuple

import numpy as np

Cell = Tuple[int, int]

GRID_ORIGIN = (896.5, 154.5)    # top-left corner of cell (0, 0), 1920x1080 pixels
CELL_PX = 111.0
GRID_ROWS = 7
GRID_COLS = 8
BLOCKED: FrozenSet[Cell] = frozenset({(0, 0), (0, 7), (6, 0), (6, 7)})
EMPTY_RGB = (52, 52, 52)

# Fish cards on the Catches screen, 1920x1080 pixels: measured from tests/images/fishing/cargo_cards.png in Task 1.
CARD_ORIGIN = (180.0, 259.0)    # centre of slot 0
CARD_PITCH = (227.0, 190.0)     # (x, y) distance between slot centres
CARD_COLS = 2
CARD_SIZE = (200.0, 170.0)
MAX_CARDS = 12


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
```

Replace the four card constants with the Step 3 measurements before the tests can pass.

- [ ] **Step 5: Run to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestCargoGrid.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/fishing/cargo_grid.py tests/TestCargoGrid.py
git commit -m "feat(fishing): cargo grid geometry, preview and occupancy reading"
```

---

### Task 4: Cargo planning (pure)

**Files:**
- Create: `src/fishing/cargo_plan.py`
- Test: `tests/TestCargoPlan.py`

**Interfaces:**
- Consumes: `cargo_packer.pack_best`, `normalize`, `Placement`; `cargo_grid.Cell`.
- Produces:
  - `Catch` (frozen dataclass): `slot: int`, `cells: FrozenSet[Cell]` (shape read from the preview), `value: int`
  - `plan_cargo(free: Iterable[Cell], catches: Sequence[Catch]) -> List[Tuple[Catch, Placement]]`: value-optimised subset that fits; catches that do not fit are omitted; sorted by `slot` descending.
  - `shape_matches(preview: Iterable[Cell], placement: Placement) -> bool`: preview, normalised, equals the normalised placement cells.
  - `grab_and_drop(preview: Iterable[Cell], placement: Placement) -> Tuple[Cell, Cell]`: the preview cell to grab and the grid cell to drop it on so the preview lands exactly on `placement.cells`.

- [ ] **Step 1: Write the failing tests** in `tests/TestCargoPlan.py`:

```python
import unittest

from src.fishing.cargo_packer import orientations
from src.fishing.cargo_plan import Catch, grab_and_drop, plan_cargo, shape_matches

SQUARE = frozenset({(0, 0), (0, 1), (1, 0), (1, 1)})
BAR = frozenset({(0, 0), (0, 1), (0, 2), (0, 3)})
L = frozenset({(0, 0), (1, 0), (2, 0), (2, 1)})


def grid(rows, cols):
    return {(r, c) for r in range(rows) for c in range(cols)}


class TestPlanCargo(unittest.TestCase):
    def test_everything_fits(self):
        catches = [Catch(0, SQUARE, 5), Catch(1, BAR, 3)]
        plan = plan_cargo(grid(4, 4), catches)
        self.assertEqual({0, 1}, {c.slot for c, _ in plan})

    def test_high_value_fish_wins_when_only_one_fits(self):
        catches = [Catch(0, SQUARE, 5), Catch(1, SQUARE, 9)]
        plan = plan_cargo(grid(2, 2), catches)
        self.assertEqual([1], [c.slot for c, _ in plan])

    def test_nothing_fits(self):
        self.assertEqual([], plan_cargo(grid(1, 1), [Catch(0, SQUARE, 5)]))

    def test_no_catches(self):
        self.assertEqual([], plan_cargo(grid(3, 3), []))

    def test_placements_do_not_overlap_and_stay_in_free_cells(self):
        free = grid(3, 4)
        plan = plan_cargo(free, [Catch(0, L, 4), Catch(1, SQUARE, 6), Catch(2, BAR, 5)])
        seen = set()
        for _, placement in plan:
            self.assertTrue(placement.cells <= free)
            self.assertTrue(seen.isdisjoint(placement.cells))
            seen |= placement.cells

    def test_sorted_by_slot_descending(self):
        plan = plan_cargo(grid(4, 4), [Catch(0, SQUARE, 5), Catch(1, SQUARE, 5), Catch(2, SQUARE, 5)])
        slots = [c.slot for c, _ in plan]
        self.assertEqual(sorted(slots, reverse=True), slots)


class TestDragTargets(unittest.TestCase):
    def test_shape_matches_after_rotation(self):
        plan = plan_cargo(grid(2, 3), [Catch(0, L, 4)])
        _, placement = plan[0]
        rotated = dict(orientations(L))[placement.rotations]
        self.assertTrue(shape_matches({(r + 5, c + 4) for r, c in rotated}, placement))
        if placement.rotations:
            self.assertFalse(shape_matches(L, placement))

    def test_grab_and_drop_moves_the_preview_onto_the_placement(self):
        preview = {(2, 2), (3, 2), (4, 2), (4, 3)}            # an L at rows 2-4, cols 2-3
        plan = plan_cargo(grid(7, 8), [Catch(0, frozenset({(0, 0), (1, 0), (2, 0), (2, 1)}), 4)])
        placement = plan[0][1]
        grab, drop = grab_and_drop(preview, placement)
        self.assertIn(grab, preview)
        dr, dc = drop[0] - grab[0], drop[1] - grab[1]
        # only valid when the shape already has the target orientation
        if shape_matches(preview, placement):
            self.assertEqual(placement.cells, frozenset((r + dr, c + dc) for r, c in preview))
```

- [ ] **Step 2: Run to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestCargoPlan.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement** `src/fishing/cargo_plan.py`:

```python
from dataclasses import dataclass
from typing import FrozenSet, Iterable, List, Sequence, Tuple

from src.fishing.cargo_packer import Placement, normalize, pack_best

Cell = Tuple[int, int]


@dataclass(frozen=True)
class Catch:
    slot: int
    cells: FrozenSet[Cell]
    value: int


def plan_cargo(free: Iterable[Cell], catches: Sequence[Catch]) -> List[Tuple[Catch, Placement]]:
    """Value-optimised set of catches that fits the free cells, highest slot first.

    Highest slot first: placing a card removes it from the list, so the slots below it do not shift.
    """
    by_slot = {c.slot: c for c in catches}
    pieces = {str(c.slot): c.cells for c in catches}
    values = {str(c.slot): c.value for c in catches}
    plan = pack_best(free, pieces, values)
    if not plan:
        return []
    placed = [(by_slot[int(name)], placement) for name, placement in plan.items()]
    return sorted(placed, key=lambda item: -item[0].slot)


def shape_matches(preview: Iterable[Cell], placement: Placement) -> bool:
    return normalize(preview) == normalize(placement.cells)


def grab_and_drop(preview: Iterable[Cell], placement: Placement) -> Tuple[Cell, Cell]:
    cells = list(preview)
    top = min(r for r, _ in cells)
    left = min(c for _, c in cells)
    grab = min(cells)
    target_top = min(r for r, _ in placement.cells)
    target_left = min(c for _, c in placement.cells)
    return grab, (target_top + grab[0] - top, target_left + grab[1] - left)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestCargoPlan.py tests/TestCargoPacker.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/fishing/cargo_plan.py tests/TestCargoPlan.py
git commit -m "feat(fishing): value-optimised cargo planning and drag targets"
```

---

### Task 5: Task skeleton, registration and the loop (tested with stubs)

**Files:**
- Create: `src/task/BaitFishingTask.py`
- Modify: `config.py:274` (add after the `FishingTask` line)
- Test: `tests/TestBaitFishingTask.py`

**Interfaces:**
- Consumes: `FishingTask` helpers (`hold_key`, `click_at`, `texts`, `has_text`, `fail`, `go_to_dock`, `prepare_and_sail`, `sell_all`, `rgb_frame`, `check_tool_key`), `bait_logic.*`, `bait_ui.*`.
- Produces `BaitFishingTask`:
  - `run()` setup; `loop()` the rounds (the unit under test); `play_round()` one round.
  - `bait_count() -> Optional[int]` equips Baiting, reads the count (up to 3 reads).
  - game-facing methods, stubbed here and implemented in Tasks 6 to 8: `clear_dock_prompt()`, `launch_bait()`, `catch_fish()`, `load_cargo()`, `return_to_dock()`.

- [ ] **Step 1: Write the failing tests** in `tests/TestBaitFishingTask.py`:

```python
import unittest

from src.task.BaitFishingTask import BaitFishingTask


class Fake(BaitFishingTask):
    """BaitFishingTask with every game-facing method replaced, to test the loop."""

    def __init__(self, counts, max_rounds=0):
        self.counts = list(counts)
        self.config = {'Max Rounds': max_rounds}
        self.rounds = 0
        self.notes = []

    def bait_count(self):
        return self.counts.pop(0)

    def play_round(self):
        self.rounds += 1

    def log_info(self, message, notify=False, **kwargs):
        self.notes.append(message)

    def fail(self, message):
        raise Exception(message)


class TestLoop(unittest.TestCase):
    def test_runs_until_the_bait_is_gone(self):
        task = Fake([3, 2, 1, 0])
        task.loop()
        self.assertEqual(3, task.rounds)
        self.assertTrue(any('no bait' in n.lower() for n in task.notes))

    def test_stops_after_max_rounds(self):
        task = Fake([5, 4, 3, 2], max_rounds=2)
        task.loop()
        self.assertEqual(2, task.rounds)

    def test_fails_when_the_count_does_not_drop_twice(self):
        task = Fake([3, 3, 3])
        with self.assertRaises(Exception) as ctx:
            task.loop()
        self.assertIn('did not drop', str(ctx.exception))

    def test_fails_when_the_count_is_unreadable(self):
        task = Fake([None])
        with self.assertRaises(Exception) as ctx:
            task.loop()
        self.assertIn('unreadable', str(ctx.exception))

    def test_starts_at_zero_without_playing(self):
        task = Fake([0])
        task.loop()
        self.assertEqual(0, task.rounds)


class TestRegistration(unittest.TestCase):
    def test_registered_in_config(self):
        from config import config
        self.assertIn(["src.task.BaitFishingTask", "BaitFishingTask"], config["onetime_tasks"])

    def test_tool_key_check_is_inherited(self):
        task = BaitFishingTask.__new__(BaitFishingTask)

        class Keys:
            def get(self, key):
                return "mouse_x2"

        task.key_config = Keys()
        with self.assertRaises(Exception):
            task.check_tool_key()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestBaitFishingTask.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement** `src/task/BaitFishingTask.py`:

```python
import random
import time

from ok import Logger

from src.fishing import bait_ui as ui, detect, human_input as hi
from src.fishing.bait_logic import (RoundGuard, dialog_open, entry_selected, parse_count, prompt_state,
                                    sandworm_launched)
from src.fishing.real_input import RealInput
from src.task.FishingTask import FishingTask
from src.task.WWOneTimeTask import WWOneTimeTask

logger = Logger.get_logger(__name__)


class BaitFishingTask(FishingTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "🎣 Bait Fishing (Sandworm)"
        self.description = ("Riccioli Islands: launch Sandworm bait near the dock, catch the fish, load the cargo, "
                            "sell all and repeat until the bait runs out. Start in the open world or on the boat. "
                            "Needs an elevated run.")
        self.default_config.pop('Max Sail Minutes', None)
        self.default_config.update({'Max Rounds': 0})   # 0 = until the bait runs out

    def run(self):
        WWOneTimeTask.run(self)
        self.check_tool_key()
        self.real = RealInput(self.hwnd.hwnd)
        if not self.is_sailing():
            self.ensure_main()
            self.go_to_dock()
            self.prepare_and_sail()
        self.loop()
        self.log_info('Bait fishing done', notify=True)

    def is_sailing(self):
        return detect.heart_px(self.rgb_frame()) >= detect.FULL_HEARTS_PX * 0.3

    def loop(self):
        guard = RoundGuard()
        max_rounds = int(self.config.get('Max Rounds', 0))
        previous = None
        rounds = 0
        while True:
            count = self.bait_count()
            if count is None:
                self.fail('bait count unreadable')
            if previous is not None and not guard.record(previous, count):
                self.fail('bait count did not drop after two rounds')
            self.info_set('bait', count)
            if count == 0:
                self.log_info('No bait left', notify=True)
                return
            if max_rounds and rounds >= max_rounds:
                return
            previous = count
            self.play_round()
            rounds += 1

    def play_round(self):
        self.clear_dock_prompt()
        self.launch_bait()
        self.catch_fish()
        self.load_cargo()
        self.return_to_dock()
        self.send_key('f', after_sleep=random.uniform(1.8, 2.6))   # opens the Dock hub
        self.sell_all()
        self.prepare_and_sail()

    # ---- utilities -----------------------------------------------------

    def equip(self, name):
        self.send_key(self.key_config.get('Wheel Key'), after_sleep=random.uniform(0.7, 1.1))
        self.click_at(*ui.UTILITY_SLOTS[name], after_sleep=random.uniform(0.6, 1.0))
        if not ui.WHEEL_CLOSES_ON_PICK:
            self.send_key(self.key_config.get('Wheel Key'), after_sleep=random.uniform(0.6, 1.0))

    def utility_count(self):
        for _ in range(3):
            count = parse_count(self.texts(*ui.COUNT_BOX))
            if count is not None:
                return count
            self.sleep(random.uniform(0.4, 0.8))
        return None

    def bait_count(self):
        self.equip('baiting')
        return self.utility_count()

    # ---- game-facing states (Tasks 6 to 8) -----------------------------

    def clear_dock_prompt(self): raise NotImplementedError
    def launch_bait(self): raise NotImplementedError
    def catch_fish(self): raise NotImplementedError
    def load_cargo(self): raise NotImplementedError
    def return_to_dock(self): raise NotImplementedError
```

In `config.py`, add after `["src.task.FishingTask", "FishingTask"],`:

```python
        ["src.task.BaitFishingTask", "BaitFishingTask"],
```

- [ ] **Step 4: Run to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestBaitFishingTask.py tests/TestFishingTask.py -v`
Expected: PASS.

- [ ] **Step 5: Live check, equip and count (user watching).** With the boat at sea, run a throwaway snippet or temporary task entry that calls `self.equip('baiting')`, then `self.utility_count()`, then `equip('sweet_puff')` and `utility_count()`. Confirm both counts equal what the screen shows and the wheel closes. If the OCR box misses the digits, adjust `COUNT_BOX` in `bait_ui.py` and re-capture `bait_icon_*.png`.

- [ ] **Step 6: Commit**

```bash
git add src/task/BaitFishingTask.py tests/TestBaitFishingTask.py config.py src/fishing/bait_ui.py
git commit -m "feat(fishing): add BaitFishingTask loop, utility switching and registration"
```

---

### Task 6: Dock prompt nudges and bait launch (live)

**Files:**
- Modify: `src/task/BaitFishingTask.py` (`clear_dock_prompt`, `launch_bait`, `return_to_dock`, prompt helpers)
- Test: `tests/TestBaitFishingTask.py` (nudge bound tests)

**Interfaces:**
- Consumes: `prompt_state`, `entry_selected`, `dialog_open`, `sandworm_launched`, `hi.nudge_press`, `ui.*`.
- Produces: `prompt_texts() -> list[str]`, `nudge_until(key, done: Callable[[], bool], tries: int, label: str)`, `select_entry(pattern)`.

- [ ] **Step 1: Write the failing tests** (append to `tests/TestBaitFishingTask.py`):

```python
class Nudger(BaitFishingTask):
    def __init__(self, states):
        self.states = list(states)
        self.presses = []

    def hold_key(self, key, seconds):
        self.presses.append(key)

    def sleep(self, seconds):
        pass

    def fail(self, message):
        raise Exception(message)


class TestNudge(unittest.TestCase):
    def test_nudges_until_the_condition_holds(self):
        task = Nudger([False, False, True])
        task.nudge_until('w', lambda: task.states.pop(0), tries=5, label='x')
        self.assertEqual(['w', 'w'], task.presses)

    def test_fails_after_the_bound(self):
        task = Nudger([False] * 10)
        with self.assertRaises(Exception) as ctx:
            task.nudge_until('s', lambda: task.states.pop(0), tries=3, label='the dock prompt')
        self.assertIn('the dock prompt', str(ctx.exception))
        self.assertEqual(3, len(task.presses))
```

- [ ] **Step 2: Run to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestBaitFishingTask.py -v`
Expected: FAIL (`nudge_until` missing).

- [ ] **Step 3: Implement.** Replace the `clear_dock_prompt`, `launch_bait` and `return_to_dock` stubs and add the helpers:

```python
    def prompt_texts(self):
        return self.texts(*ui.PROMPT_BOX)

    def nudge_until(self, key, done, tries, label):
        for _ in range(tries):
            if done():
                return
            self.hold_key(key, hi.nudge_press())
            self.sleep(random.uniform(0.3, 0.7))
        if done():
            return
        self.fail(f'{label}: not reached after {tries} presses of {key}')

    def select_entry(self, pattern, label):
        # The prompt list starts on its first entry; scroll until the wanted entry carries the F key badge.
        for _ in range(4):
            boxes = [(box.name, (box.y + box.height / 2) / self.height)
                     for box in (self.ocr(*ui.PROMPT_BOX) or [])]
            selected = entry_selected(boxes, pattern)
            if selected:
                return
            if selected is None:
                self.fail(f'{label} entry not found in the prompt list')
            self.scroll_relative(*ui.PROMPT_SCROLL_AT, ui.SCROLL_DOWN)
            self.sleep(random.uniform(0.3, 0.6))
        self.fail(f'could not select the {label} entry')

    def clear_dock_prompt(self):
        # The fish spot appears ahead of the boat: leave the dock's reach before baiting.
        self.info_set('current task', 'leave the dock prompt')
        self.nudge_until('w', lambda: not prompt_state(self.prompt_texts()).return_dock,
                         tries=10, label='leaving the dock prompt')

    def launch_bait(self):
        self.info_set('current task', 'launch bait')
        self.equip('baiting')
        self.send_key(self.key_config.get('Tool Key'), after_sleep=random.uniform(0.8, 1.3))
        if not self.wait_until(lambda: dialog_open(self.texts(0.2, 0.1, 0.8, 0.5)), time_out=10):
            self.fail('Use Bait dialog did not open')
        self.click_at(*ui.CONFIRM_AT, after_sleep=random.uniform(0.8, 1.2))
        if not self.wait_until(lambda: sandworm_launched(self.texts()), time_out=20):
            self.fail('Sandworm launched message did not show')
        self.sleep(random.uniform(0.6, 1.2))

    def return_to_dock(self):
        self.info_set('current task', 'return to dock')
        self.nudge_until('s', lambda: prompt_state(self.prompt_texts()).return_dock,
                         tries=12, label='the Return to the dock prompt')
        self.select_entry(r'return\s+to\s+the\s+dock', 'Return to the dock')
```

- [ ] **Step 4: Run to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestBaitFishingTask.py -v`
Expected: PASS.

- [ ] **Step 5: Live check (user watching).** On the boat at the dock bay, run `clear_dock_prompt` then `launch_bait` through a temporary entry point: the boat leaves the prompt, the dialog opens, Confirm is clicked, the launched message is seen, and the bait count drops by 1. Then run `return_to_dock` and confirm the prompt returns and the F badge sits on that entry. Fix `CONFIRM_AT`, the dialog OCR box, `PROMPT_BOX` or `entry_selected` (using the real OCR output of the prompt list) as needed and note the reason in the commit.

- [ ] **Step 6: Commit**

```bash
git add src/task/BaitFishingTask.py tests/TestBaitFishingTask.py src/fishing/bait_ui.py
git commit -m "feat(fishing): dock prompt nudges and bait launch"
```

---

### Task 7: Catching fish, with and without Sweet Puff (live)

**Files:**
- Modify: `src/task/BaitFishingTask.py` (`catch_fish`, `try_sweet_puff`, `fish_normally`, `cargo_screen_open`)
- Test: `tests/TestBaitFishingTask.py`

**Interfaces:**
- Produces: `catch_fish()`; `try_sweet_puff() -> bool`; `fish_normally()`; `cargo_screen_open() -> bool` (the "Cargo" title text at the top of the screen).

- [ ] **Step 1: Write the failing test** (append):

```python
class Catcher(BaitFishingTask):
    def __init__(self, puff):
        self.puff = puff
        self.calls = []

    def try_sweet_puff(self):
        self.calls.append('puff')
        return self.puff

    def fish_normally(self):
        self.calls.append('normal')


class TestCatchFish(unittest.TestCase):
    def test_uses_sweet_puff_when_available(self):
        task = Catcher(True)
        task.catch_fish()
        self.assertEqual(['puff'], task.calls)

    def test_falls_back_to_normal_fishing(self):
        task = Catcher(False)
        task.catch_fish()
        self.assertEqual(['puff', 'normal'], task.calls)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestBaitFishingTask.py -v`
Expected: FAIL (`catch_fish` raises `NotImplementedError`).

- [ ] **Step 3: Implement** (replace the `catch_fish` stub):

```python
    def catch_fish(self):
        if self.try_sweet_puff():
            return
        self.fish_normally()

    def try_sweet_puff(self):
        self.info_set('current task', 'sweet puff')
        self.equip('sweet_puff')
        if not (self.utility_count() or 0) > 0:
            return False
        self.send_key(self.key_config.get('Tool Key'), after_sleep=random.uniform(0.8, 1.3))
        if not self.wait_until(lambda: self.has_text('Fishing Complete'), time_out=20):
            self.fail('Fishing Complete did not show after using Sweet Puff')
        self.sleep(random.uniform(0.8, 1.4))
        self.click_at(*ui.FISHING_COMPLETE_CLOSE_AT, after_sleep=random.uniform(1.0, 1.6))
        return True

    def fish_normally(self):
        self.info_set('current task', 'fish')
        self.nudge_until('w', lambda: prompt_state(self.prompt_texts()).fish, tries=8, label='the Fish prompt')
        self.select_entry(r'(?<![A-Za-z])Fish(?![A-Za-z])', 'Fish')
        self.send_key('f', after_sleep=random.uniform(0.8, 1.4))
        # the mini-game finishes by itself in 15 to 30 s and opens the Cargo screen
        if not self.wait_until(self.cargo_screen_open, time_out=75):
            self.fail('mini-game did not reach the Cargo screen')
        self.sleep(random.uniform(0.6, 1.0))

    def cargo_screen_open(self):
        return self.has_text(r'Cargo|Catch', 0.0, 0.0, 0.6, 0.15)
```

(`wait_until` returns the condition's truthy result or a falsy value on timeout, as used by `reach_planck`.)

- [ ] **Step 4: Run to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestBaitFishingTask.py -v`
Expected: PASS.

- [ ] **Step 5: Live check, both paths (user watching).** Path A: with Sweet Puff in stock, run `launch_bait` then `catch_fish`; "Fishing Complete" shows and closes and the Cargo screen opens. Path B: with the Sweet Puff count at 0 (or temporarily call `fish_normally` directly), nudge until `[F] Fish`, select it, press F, and the Cargo screen opens when the mini-game ends. Check `cargo_screen_open` against the real OCR text of the Catches screen top-left and fix the regex and box if the title reads differently.

- [ ] **Step 6: Commit**

```bash
git add src/task/BaitFishingTask.py tests/TestBaitFishingTask.py src/fishing/bait_ui.py
git commit -m "feat(fishing): catch fish with Sweet Puff or the normal mini-game"
```

---

### Task 8: Cargo loading (live)

**Files:**
- Modify: `src/task/BaitFishingTask.py` (`load_cargo`, `survey_catches`, `place_catch`, `release_selected_fish`)
- Test: `tests/TestBaitFishingTask.py`

**Interfaces:**
- Consumes: `cargo_grid.*`, `cargo_plan.*`, `RealInput.drag`.
- Produces: `load_cargo()`; `survey_catches(base) -> list[Catch]`; `place_catch(catch, placement, base)`; `release_selected_fish()` (called by `FishingTask.sell_all` when "Please handle the selected item first" shows).

- [ ] **Step 1: Write the failing test for the survey stop** (append). The survey stops at the first slot with no preview:

```python
import numpy as np

from src.fishing import cargo_grid as cg


class Surveyor(BaitFishingTask):
    def __init__(self, shapes):
        self.shapes = shapes          # slot -> list of cells (a missing slot has no preview)
        self.clicked = []
        self.current = None
        self.width, self.height = 1920, 1080

    def click_at(self, fx, fy, after_sleep=0.4):
        self.clicked.append((fx, fy))
        slots = [cg.card_center(s) for s in range(cg.MAX_CARDS)]
        self.current = min(range(cg.MAX_CARDS), key=lambda s: abs(slots[s][0] - fx) + abs(slots[s][1] - fy))

    def rgb_frame(self):
        frame = np.full((1080, 1920, 3), 52, np.uint8)
        for r, c in self.shapes.get(self.current, []):
            x, y = cg.cell_center(r, c)
            frame[int(y * 1080) - 30:int(y * 1080) + 30, int(x * 1920) - 30:int(x * 1920) + 30] = (90, 160, 230)
        return frame

    def texts(self, x=0, y=0, to_x=1, to_y=1):
        return ["1,200"]

    def sleep(self, seconds):
        pass


class TestSurvey(unittest.TestCase):
    def test_reads_shapes_and_stops_at_the_first_empty_slot(self):
        shapes = {0: [(2, 2), (2, 3)], 1: [(3, 3), (4, 3), (4, 4)]}
        task = Surveyor(shapes)
        base = np.full((1080, 1920, 3), 52, np.uint8)
        catches = task.survey_catches(base)
        self.assertEqual([0, 1], [c.slot for c in catches])
        self.assertEqual(frozenset({(2, 2), (2, 3)}), catches[0].cells)
        self.assertEqual(1200, catches[0].value)
        self.assertEqual(3, len(task.clicked))     # slot 2 was probed and found empty
```

- [ ] **Step 2: Run to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestBaitFishingTask.py -v`
Expected: FAIL (`survey_catches` missing).

- [ ] **Step 3: Implement** (replace the `load_cargo` stub; add imports `from src.fishing import cargo_grid as cg` and `from src.fishing.cargo_plan import Catch, grab_and_drop, plan_cargo, shape_matches`):

```python
    def load_cargo(self):
        self.info_set('current task', 'load cargo')
        if not self.wait_until(self.cargo_screen_open, time_out=15):
            self.fail('Cargo screen not open')
        self.sleep(random.uniform(0.6, 1.0))
        base = self.rgb_frame()
        occupied = cg.occupied_cells(base)
        catches = self.survey_catches(base)
        plan = plan_cargo(cg.free_cells(occupied), catches)
        self.log_info(f'cargo: {len(plan)} of {len(catches)} catches placed')
        for catch, placement in plan:
            self.place_catch(catch, placement, base)
        self.click_at(*ui.FINISH_AT, after_sleep=random.uniform(1.0, 1.6))

    def survey_catches(self, base):
        # Click every card slot, read the shape from the preview and the value from the card; stop at the first
        # slot that shows no preview (past the last fish).
        catches = []
        for slot in range(cg.MAX_CARDS):
            self.click_at(*cg.card_center(slot), after_sleep=random.uniform(0.6, 0.9))
            cells = cg.read_preview(base, self.rgb_frame())
            if not cells:
                break
            value = cg.parse_value(self.texts(*cg.card_box(slot))) or 0
            catches.append(Catch(slot, cells, value))
        return catches

    def place_catch(self, catch, placement, base):
        self.click_at(*cg.card_center(catch.slot), after_sleep=random.uniform(0.6, 0.9))
        cells = cg.read_preview(base, self.rgb_frame())
        # rotate by re-reading the preview, never by counting presses: the rotation direction is the game's
        for _ in range(4):
            if shape_matches(cells, placement):
                break
            self.send_key('r', after_sleep=random.uniform(0.4, 0.7))
            cells = cg.read_preview(base, self.rgb_frame())
        else:
            self.log_info(f'slot {catch.slot}: could not rotate to the planned shape, leaving it')
            return
        if cells != placement.cells:
            grab, drop = grab_and_drop(cells, placement)
            src, dst = cg.cell_center(*grab), cg.cell_center(*drop)
            self.real.drag(src[0], src[1], dst[0], dst[1], random.uniform(0.8, 1.1))
            self.sleep(random.uniform(0.5, 0.8))
            if cg.read_preview(base, self.rgb_frame()) != placement.cells:
                self.log_info(f'slot {catch.slot}: preview did not land on the planned cells, leaving it')
                return
        self.send_key('space', after_sleep=random.uniform(0.5, 0.9))

    def release_selected_fish(self):
        # `FishingTask.sell_all` calls this when Sell All refuses because a fish is still selected. After
        # `Finish` nothing should be selected, so treat it as a fault until a live run shows otherwise.
        self.fail('a fish is still selected at the Dock Shop')
```

- [ ] **Step 4: Run to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestBaitFishingTask.py tests/TestCargoGrid.py tests/TestCargoPlan.py -v`
Expected: PASS.

- [ ] **Step 5: Live check (user watching).** After Task 7's live catch, run `load_cargo`. Confirm: every card is surveyed, shapes look right in the log, high-value fish are placed, nothing overlaps, Finish closes the screen and unplaced fish remain in the Catch List. Check the survey's preview diff against the Task 1 notes (whether earlier previews vanish when another card is clicked; if they stay, take `base` from the frame before each click instead). Save any new fixtures (`cargo_preview_*.png`) and add a `TestCargoGrid` case for a real preview if the fixtures allow.

- [ ] **Step 6: Commit**

```bash
git add src/task/BaitFishingTask.py tests/TestBaitFishingTask.py src/fishing/bait_ui.py src/fishing/cargo_grid.py tests/images/fishing
git commit -m "feat(fishing): survey catches and load them into the cargo"
```

---

### Task 9: Full loop, safety and live run

**Files:**
- Modify: `src/task/BaitFishingTask.py` (only fixes found live)
- Modify: `docs/superpowers/specs/2026-10-14-bait-fishing-design.md` (record settled open items)

- [ ] **Step 1: Run the whole test suite for the fishing modules**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestBaitLogic.py tests/TestCargoGrid.py tests/TestCargoPlan.py tests/TestBaitFishingTask.py tests/TestFishingTask.py tests/TestCargoPacker.py tests/TestHumanInput.py tests/TestFishingDetect.py tests/TestRealInput.py -v`
Expected: PASS.

- [ ] **Step 2: One live round (user watching).** Set `Max Rounds` to 1 and run the task from the open world, then from the boat. Confirm the whole round, the bait count drops by 1, the Catch List reads "No Catch" after selling, and the task sets sail again and stops at the round limit.

- [ ] **Step 3: Three live rounds with and without Sweet Puff.** Run with `Max Rounds` 3 including one round with Sweet Puff at 0. Check human-like timing in the log (no fixed-interval loops) and that heart checks hold: if the boat moves during nudges, note whether `detect.hearts_state` should also be sampled in `nudge_until`; add it only if a hit is seen.

- [ ] **Step 4: Update the spec's open items** with the settled answers (utility switch path, count box, prompt scroll direction, card layout, whether previews stack) and note any limits found.

- [ ] **Step 5: Commit**

```bash
git add src/task/BaitFishingTask.py docs/superpowers/specs/2026-10-14-bait-fishing-design.md
git commit -m "feat(fishing): bait fishing loop verified live"
```

---

## Self-Review

- **Spec coverage:** setup and sailing check (Task 5 `run`, `is_sailing`); utility switching via Tab (Task 5 `equip`); bait count and stop (Tasks 2, 5); position clear of the dock prompt (Task 6); launch and Confirm (Task 6); Sweet Puff and normal paths (Task 7); cargo reading, value-optimised placement, drag (Tasks 3, 4, 8); return to the dock by S nudges and Sell All (Tasks 6, 5 `play_round`); set sail again (Task 5); safety (RoundGuard, `fail`, bounded nudges); open items (Task 1 probe, Task 9 spec update). Dock fast-travel fallback is left out, as the spec says.
- **Placeholders:** every coordinate in `bait_ui.py` and the four card constants are explicit estimates replaced from Task 1 and Task 3 Step 3 measurements before their tests are run; this is the same measure-then-fix pattern as the Premium plan and is called out in those steps.
- **Type consistency:** `Catch(slot, cells, value)`, `plan_cargo(free, catches) -> list[(Catch, Placement)]`, `grab_and_drop(preview, placement)`, `shape_matches(preview, placement)`, `read_preview(before, after)`, `occupied_cells(rgb)`, `card_center/card_box(slot)`, `nudge_until(key, done, tries, label)`, `select_entry(pattern, label)`, `prompt_state(...)` fields `return_dock` and `fish` are used identically in later tasks.
- **Known unknowns for execution:** the Dock Shop "selected fish" case stops with a clear message instead of guessing; whether card previews stack, the rotation direction and the Finish position are all measured or verified in Tasks 1 and 8.
