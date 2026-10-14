import random
import time

import win32api

from ok import Logger

from src.fishing import bait_ui as ui, cargo_grid as cg, detect, human_input as hi
from src.fishing.bait_logic import (RoundGuard, dialog_open, entry_selected, parse_count, prompt_state,
                                    sandworm_launched)
from src.fishing.cargo_plan import Catch, grab_and_drop, plan_cargo, shape_matches
from src.fishing.real_input import RealInput
from src.task.FishingTask import HUB_ANCHOR, FishingTask
from src.task.WWOneTimeTask import WWOneTimeTask

logger = Logger.get_logger(__name__)


class BaitFishingTask(FishingTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "🎣 Bait Fishing (Sandworm)"
        self.description = ("Riccioli Islands: launch Sandworm bait near the dock, catch the fish, load the cargo, "
                            "sell all and repeat until the bait runs out. Start in the open world or on the boat near the dock. "
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
        self.wait_ocr(match=HUB_ANCHOR, time_out=20, raise_if_not_found=True, settle_time=0.8)
        self.sell_all()
        self.set_sail()

    SET_SAIL_AT = (0.83, 0.93)    # the Set Sail button of the sail screen (the options keep their last choice)

    def set_sail(self):
        # Later rounds: the Night and durability options are already set from the first sail, only confirm.
        if not self.wait_until(lambda: self.has_text(r'Set\s*Sail'), time_out=10):
            self.fail('Set Sail did not show in the Dock hub')
        if not self.click_ocr_text('Set Sail'):
            self.fail('could not click Set Sail in the Dock hub')
        self.sleep(1.5)
        self.click_at(*self.SET_SAIL_AT)
        self.sleep(random.uniform(4.0, 6.0))

    # ---- utilities -----------------------------------------------------

    def wheel_open(self):
        # the utility counts printed on the wheel only exist while it is open
        return parse_count(self.texts(*ui.WHEEL_BOX)) is not None

    def point_cursor(self, fx, fy):
        # the wheel picks the slot under the real cursor when the key is released (see CombatCheck's tab wheel)
        x, y = hi.offset_point(fx, fy)
        px, py = int(x * self.width), int(y * self.height)
        self.move(px, py)
        abs_x, abs_y = self.executor.interaction.capture.get_abs_cords(px, py)
        win32api.SetCursorPos((int(abs_x), int(abs_y)))

    def equip(self, name):
        # Tab is a hold-to-open wheel: hold it, point at the utility, release to select
        wheel_key = self.key_config.get('Wheel Key')
        self.send_key_down(wheel_key)
        try:
            if not self.wait_until(self.wheel_open, time_out=5):
                self.fail('utility wheel did not open')
            self.sleep(random.uniform(0.3, 0.6))
            self.point_cursor(*ui.UTILITY_SLOTS[name])
            self.sleep(random.uniform(0.4, 0.8))
        finally:
            self.send_key_up(wheel_key)
        self.sleep(random.uniform(0.4, 0.7))
        if not self.wait_until(lambda: not self.wheel_open(), time_out=4):
            self.fail('utility wheel did not close after picking ' + name)

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
        # The prompt list starts on its first entry; scroll until the wanted entry carries the F key badge. A
        # missing entry is first taken for an OCR miss, so look again before giving up.
        tries = 5
        selected = None
        for attempt in range(tries):
            boxes = [(box.name, (box.y + box.height / 2) / self.height)
                     for box in (self.ocr(*ui.PROMPT_BOX) or [])]
            selected = entry_selected(boxes, pattern)
            if selected:
                return
            if selected is None:
                self.sleep(random.uniform(0.4, 0.8))
            elif attempt < tries - 1:
                self.scroll_relative(*ui.PROMPT_SCROLL_AT, ui.SCROLL_DOWN)
                self.sleep(random.uniform(0.3, 0.6))
        if selected is None:
            self.fail(f'{label} entry not found in the prompt list')
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
        if not self.click_ocr_text(r'^\s*Confirm\s*$'):
            self.fail('Confirm button not found in the Use Bait dialog')
        self.sleep(random.uniform(0.8, 1.2))
        if not self.wait_until(lambda: sandworm_launched(self.texts()), time_out=20):
            self.fail('Sandworm launched message did not show')
        self.sleep(random.uniform(0.6, 1.2))

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

    LOAD_PASSES = 4
    PLACE_WAIT = 4    # seconds for the Cargo counter to rise after a drop

    def load_cargo(self):
        self.info_set('current task', 'load cargo')
        if not self.wait_until(self.cargo_screen_open, time_out=15):
            self.fail('Cargo screen not open')
        self.sleep(random.uniform(0.6, 1.0))
        self.screenshot('cargo_screen')   # kept for measuring the card and grid geometry
        for _ in range(self.LOAD_PASSES):
            occupied = cg.occupied_cells(self.rgb_frame())
            catches = self.survey_catches()
            plan = plan_cargo(cg.free_cells(occupied), catches)
            self.log_info(f'cargo: {len(plan)} of {len(catches)} catches placed')
            for catch, placement in plan:
                if not self.place_catch(catch, placement):
                    # Finish with fish still unplaced loses them: stop with the Cargo screen open instead
                    self.fail(f'cargo: slot {catch.slot} could not be placed; Cargo screen left open, Finish not pressed')
            # a full list may hide more fish behind the visible cards: look again once the placed ones have left
            if not plan or len(catches) < cg.MAX_CARDS:
                break
        self.click_at(*ui.FINISH_AT, after_sleep=random.uniform(1.0, 1.6))

    def cargo_used(self):
        return cg.parse_cargo_used(self.texts(*cg.CARGO_COUNT_BOX))

    def survey_catches(self):
        # Click every card slot: the click shows the fish as a ghost on the grid, the value is read off the card.
        # A slot without a card keeps the previous ghost (or none) and has no value.
        catches = []
        previous = frozenset()
        for slot in range(cg.MAX_CARDS):
            self.click_at(*cg.card_center(slot), after_sleep=random.uniform(0.6, 0.9))
            cells = cg.read_ghost(self.rgb_frame())
            if slot == 0:
                self.screenshot('cargo_first_card')
            value = cg.parse_value(self.texts(*cg.card_box(slot)))
            if value is None and (not cells or cells == previous):
                break
            if not cells:
                self.fail(f'cargo: slot {slot} shows a value of {value} but no ghost on the grid; nothing was lost')
            if value is None:
                self.log_info(f'slot {slot}: card value unreadable, using its {len(cells)} cells as the value')
                value = len(cells)
            catches.append(Catch(slot, cells, value))
            previous = cells
        return catches

    def place_catch(self, catch, placement):
        """Place one catch by dragging its ghost and confirming with Space; True when the Cargo counter rose, False when it did not (caller stops)."""
        self.click_at(*cg.card_center(catch.slot), after_sleep=random.uniform(0.6, 0.9))
        cells = cg.read_ghost(self.rgb_frame())
        # rotate by re-reading the ghost, never by counting presses: the rotation direction is the game's
        for _ in range(4):
            if shape_matches(cells, placement):
                break
            self.send_key('r', after_sleep=random.uniform(0.4, 0.7))
            cells = cg.read_ghost(self.rgb_frame())
        else:
            self.log_info(f'slot {catch.slot}: could not rotate to the planned shape, leaving it')
            return False
        used_before = self.cargo_used()
        if used_before is None:
            self.log_info(f'slot {catch.slot}: Cargo counter unreadable, leaving it')
            return False
        grab, drop = grab_and_drop(cells, placement)
        src, dst = cg.cell_center(*grab), cg.cell_center(*drop)
        if grab == drop:
            # the game needs a real movement: end a quarter cell to the right, still inside the cell
            dst = (dst[0] + cg.CELL_PX / 4 / 1920.0, dst[1])
        self.real.drag(src[0], src[1], dst[0], dst[1], random.uniform(0.8, 1.1))
        want = used_before + len(placement.cells)
        if not self.wait_until(lambda: self.cargo_used() == want, time_out=self.PLACE_WAIT):
            self.log_info(f'slot {catch.slot}: the Cargo counter did not reach {want}, leaving it')
            return False
        # the dropped fish is only a draft until Space confirms it (never 't': that trashes it)
        self.send_key('space', after_sleep=random.uniform(0.6, 1.0))
        return True

    def release_selected_fish(self):
        # `FishingTask.sell_all` calls this when Sell All refuses because a fish is still selected. After
        # `Finish` nothing should be selected, so treat it as a fault until a live run shows otherwise.
        self.fail('a fish is still selected at the Dock Shop')

    def return_to_dock(self):
        self.info_set('current task', 'return to dock')
        self.nudge_until('s', lambda: prompt_state(self.prompt_texts()).return_dock,
                         tries=12, label='the Return to the dock prompt')
        if prompt_state(self.prompt_texts()).fish:
            self.select_entry(r'return\s+to\s+the\s+dock', 'Return to the dock')
        # a lone entry is always the selected one: its F badge is not reliably read by OCR
