import random
import time

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
        self.click_at(*ui.CONFIRM_AT, after_sleep=random.uniform(0.8, 1.2))
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
        placed = set()
        for catch, placement in plan:
            if not self.place_catch(catch, placement, base, placed):
                self.log_info(f'cargo: slot {catch.slot} was not placed, leaving the rest as they are')
                break
            placed |= placement.cells
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
            value = cg.parse_value(self.texts(*cg.card_box(slot)))
            if value is None:
                self.log_info(f'slot {slot}: card value unreadable, counting it as 0')
                value = 0
            catches.append(Catch(slot, cells, value))
        return catches

    def place_catch(self, catch, placement, survey_base=None, placed=frozenset()):
        """Place one catch; True when it was placed, False when it was left (the caller stops placing)."""
        if survey_base is not None:
            stray = cg.read_preview(survey_base, self.rgb_frame()) - frozenset(placed)
            if stray:
                self.log_info(f'slot {catch.slot}: a preview from an earlier card is still showing: {sorted(stray)}')
        # a fresh base for every card: earlier placements are part of the cargo now and must not read as preview
        base = self.rgb_frame()
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
            return False
        if cells != placement.cells:
            grab, drop = grab_and_drop(cells, placement)
            src, dst = cg.cell_center(*grab), cg.cell_center(*drop)
            self.real.drag(src[0], src[1], dst[0], dst[1], random.uniform(0.8, 1.1))
            self.sleep(random.uniform(0.5, 0.8))
            if cg.read_preview(base, self.rgb_frame()) != placement.cells:
                self.log_info(f'slot {catch.slot}: preview did not land on the planned cells, leaving it')
                return False
        self.send_key('space', after_sleep=random.uniform(0.5, 0.9))
        return True

    def release_selected_fish(self):
        # `FishingTask.sell_all` calls this when Sell All refuses because a fish is still selected. After
        # `Finish` nothing should be selected, so treat it as a fault until a live run shows otherwise.
        self.fail('a fish is still selected at the Dock Shop')

    def return_to_dock(self):
        self.info_set('current task', 'return to dock')
        self.nudge_until('s', lambda: prompt_state(self.prompt_texts()).return_dock,
                         tries=12, label='the Return to the dock prompt')
        self.select_entry(r'return\s+to\s+the\s+dock', 'Return to the dock')
