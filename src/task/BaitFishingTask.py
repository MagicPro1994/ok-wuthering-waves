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
    def load_cargo(self): raise NotImplementedError
    def return_to_dock(self):
        self.info_set('current task', 'return to dock')
        self.nudge_until('s', lambda: prompt_state(self.prompt_texts()).return_dock,
                         tries=12, label='the Return to the dock prompt')
        self.select_entry(r'return\s+to\s+the\s+dock', 'Return to the dock')
