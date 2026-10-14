import random
import time

import numpy as np
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
            if not self.has_text(HUB_ANCHOR.pattern):    # already on the Dock hub: no need to travel there
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

    LOAD_PASSES = 6
    MAX_QUICK_SALES = 3
    PLACE_WAIT = 4    # seconds for the Cargo counter to rise after a confirm

    def load_cargo(self, finish=True):
        self.info_set('current task', 'load cargo')
        if not self.wait_until(self.cargo_screen_open, time_out=15):
            self.fail('Cargo screen not open')
        self.sleep(random.uniform(0.6, 1.0))
        self.screenshot('cargo_screen')   # kept for measuring the card and grid geometry
        sales = 0
        passes = 0
        while passes < self.LOAD_PASSES:
            passes += 1
            self.clear_draft()      # a draft left on screen would end up in the base frames
            occupied = cg.occupied_cells(self.rgb_frame())
            catches = self.survey_catches()
            for catch in catches:
                self.log_info(f'cargo survey: slot {catch.slot} value {catch.value} cells {sorted(catch.cells)}')
            plan = plan_cargo(cg.free_cells(occupied), catches)
            self.log_info(f'cargo: {len(plan)} of {len(catches)} catches placed')
            self.log_info('cargo plan: ' + ', '.join(f'slot {c.slot} value {c.value} -> {sorted(p.cells)}' for c, p in plan))
            for catch, placement in plan:
                if not self.place_catch(catch, placement):
                    # Finish with fish still unplaced loses them: stop with the Cargo screen open instead
                    self.fail(f'cargo: slot {catch.slot} could not be placed; Cargo screen left open, Finish not pressed')
            leftovers = len(catches) - len(plan)
            if leftovers > 0:
                if sales >= self.MAX_QUICK_SALES:
                    self.log_info(f'cargo: {leftovers} fish left over, Quick Sale already used {sales} times')
                    break
                self.log_info(f'cargo: {leftovers} fish left over, trying Quick Sale')
                self.clear_draft()
                if not self.quick_sale():
                    break
                sales += 1
            elif len(catches) < cg.MAX_CARDS:
                break
            # else: a full list may hide more fish behind the visible cards, look again once the placed ones have left
        self.clear_draft()      # the survey leaves the last probed card's draft up
        if finish:
            self.click_at(*ui.FINISH_AT, after_sleep=random.uniform(1.0, 1.6))

    QUICK_SALE_PANEL = (0.02, 0.5, 0.45, 0.95)
    QUICK_SALE_PRICE = (0.1, 0.74, 0.35, 0.83)
    QUICK_SALE_CLOSE_AT = (0.366, 0.535)
    REWARD_CLOSE_AT = (0.5, 0.85)

    def quick_sale_open(self):
        return self.has_text(r'Quick\s*Sale', *self.QUICK_SALE_PANEL)

    def quick_sale(self):
        """Sell everything in the dashed zone (`c` opens the panel, `e` sells). True when cargo was freed."""
        self.info_set('current task', 'quick sale')
        self.send_key('c', after_sleep=random.uniform(0.8, 1.2))
        if not self.wait_until(self.quick_sale_open, time_out=4):
            self.log_info('quick sale: the panel did not open')
            return False
        price = cg.parse_value(self.texts(*self.QUICK_SALE_PRICE))
        if not price:
            self.log_info('quick sale: nothing in the zone to sell, closing the panel')
            self.click_at(*self.QUICK_SALE_CLOSE_AT, after_sleep=random.uniform(0.6, 0.9))
            if not self.wait_until(lambda: not self.quick_sale_open(), time_out=4):
                self.log_info('quick sale: the panel did not close')
            return False
        used_before = self.cargo_used()
        self.send_key('e', after_sleep=random.uniform(0.8, 1.2))
        if not self.wait_until(lambda: self.has_text(r'Items\s*Obtained'), time_out=8):
            self.fail('Quick Sale did not show Items Obtained, Cargo screen left open')
        self.click_at(*self.REWARD_CLOSE_AT, after_sleep=random.uniform(1.0, 1.5))
        if not self.wait_until(self.cargo_screen_open, time_out=8):
            self.fail('Cargo screen did not come back after Quick Sale')

        def freed():
            used = self.cargo_used()
            return used is not None and used_before is not None and used < used_before
        if not self.wait_until(freed, time_out=5):
            self.fail('Quick Sale did not free any cargo, Cargo screen left open')
        self.log_info(f'quick sale freed {used_before - self.cargo_used()} cells, price {price}')
        return True

    def clear_draft(self):
        # Q returns the drafted fish to the list (never 't': that trashes it)
        for _ in range(3):
            if not cg.draft_active(self.rgb_frame()):
                return
            self.send_key('q', after_sleep=0.6)
        if cg.draft_active(self.rgb_frame()):
            self.fail('could not clear the draft, Cargo screen left open')

    def cargo_used(self):
        return cg.parse_cargo_used(self.texts(*cg.CARGO_COUNT_BOX))

    clean_base = None    # the last survey's frame without a draft, good until the next confirm

    def survey_catches(self):
        # Clicking a card shows its fish as a draft at the top-left of the grid: diff it against the frame without one
        # (none is showing when the Cargo screen opens). The value is read off the card. A slot without a card leaves
        # the previous draft in place and has no value.
        base = self.rgb_frame()
        self.clean_base = base
        occupied = cg.occupied_cells(base)
        catches = []
        previous = frozenset()
        for slot in range(cg.MAX_CARDS):
            self.click_at(*cg.card_center(slot), after_sleep=random.uniform(0.6, 0.9))
            cells = cg.read_draft(base, self.rgb_frame(), occupied)
            if slot == 0:
                self.screenshot('cargo_first_card')
            value = cg.parse_value(self.texts(*cg.card_box(slot)))
            if not cells:
                if value is not None:
                    self.fail(f'cargo: slot {slot} shows a value of {value} but no draft on the grid; nothing was lost')
                break
            if value is None and cells == previous:
                break
            if value is None:
                self.log_info(f'slot {slot}: card value unreadable, using its {len(cells)} cells as the value')
                value = len(cells)
            catches.append(Catch(slot, cells, value))
            previous = cells
        return catches

    def settled_frame(self):
        # right after a confirm the board still animates: wait for two matching frames before using one as a base
        frame = self.rgb_frame()
        for _ in range(6):
            self.sleep(0.3)
            following = self.rgb_frame()
            if np.abs(frame.astype(int) - following.astype(int)).mean() < 1.0:
                return following
            frame = following
        return frame

    def place_catch(self, catch, placement):
        """Place one catch: draft it, drag it onto the plan, confirm with Space. True once the Cargo counter rose.

        False means it was left (the caller stops). Never press `t`: that trashes the fish.
        """
        # placed fish are part of the base and no draft may show in it: a confirm clears the draft, but right after
        # a survey the last probed card's draft is still up, so that first placement uses the survey's own base
        if self.clean_base is None:
            self.clear_draft()
            base = self.settled_frame()
        else:
            base = self.clean_base
        self.clean_base = None
        occupied = cg.occupied_cells(base)
        self.click_at(*cg.card_center(catch.slot), after_sleep=random.uniform(0.6, 0.9))
        cells = cg.read_draft(base, self.rgb_frame(), occupied)
        if not cells:
            self.log_info(f'slot {catch.slot}: no draft showed after clicking its card, leaving it')
            return False
        # rotate by re-reading the draft, never by counting presses: the rotation direction is the game's
        for _ in range(4):
            if shape_matches(cells, placement):
                break
            self.send_key('r', after_sleep=random.uniform(0.4, 0.7))
            cells = cg.read_draft(base, self.rgb_frame(), occupied)
        else:
            self.log_info(f'slot {catch.slot}: could not rotate to the planned shape, leaving it')
            return False
        used_before = self.cargo_used()
        if used_before is None:
            self.log_info(f'slot {catch.slot}: Cargo counter unreadable, leaving it')
            return False
        if cells != placement.cells:
            grab, drop = grab_and_drop(cells, placement)
            src, dst = cg.cell_center(*grab), cg.cell_center(*drop)
            self.real.drag(src[0], src[1], dst[0], dst[1], random.uniform(0.8, 1.1))
            self.sleep(random.uniform(0.5, 0.8))
            landed = cg.read_draft(base, self.rgb_frame(), occupied)
            if landed != placement.cells:
                self.screenshot('cargo_after_drag')
                self.log_info(f'slot {catch.slot}: the draft did not land on the planned cells, leaving it: '
                              f'planned {sorted(placement.cells)}, read {sorted(landed)}, '
                              f'dragged {sorted(cells)} from {grab} to {drop}')
                return False
        self.send_key('space', after_sleep=random.uniform(0.6, 1.0))
        want = used_before + len(placement.cells)
        if not self.wait_until(lambda: self.cargo_used() == want, time_out=self.PLACE_WAIT):
            self.log_info(f'slot {catch.slot}: the Cargo counter did not reach {want}, leaving it')
            return False
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
