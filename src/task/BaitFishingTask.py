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
        self.open_dock_hub()
        self.sell_all()
        self.set_sail()



    # ---- utilities -----------------------------------------------------

    def utility_count(self):
        for _ in range(5):
            count = parse_count(self.texts(*ui.COUNT_BOX))
            if count is not None:
                return count
            self.sleep(random.uniform(0.4, 0.8))
        return None

    def bait_count(self):
        for _ in range(2):
            self.equip('baiting')
            count = self.utility_count()
            if count is not None:
                return count
            self.screenshot('utility_missed')   # no count on the bottom-right icon: Baiting was probably not picked
        return None

    # ---- game-facing states (Tasks 6 to 8) -----------------------------


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
        count = self.utility_count()
        if count == 0:
            return False                  # read as empty: take the manual path
        # An unreadable count is not an empty stock (the small digits are easy to miss): try it and see.
        self.send_key(self.key_config.get('Tool Key'), after_sleep=random.uniform(0.8, 1.3))
        if not self.wait_until(lambda: self.has_text('Fishing Complete'), time_out=20):
            if count is None:
                self.log_info('Sweet Puff count unreadable and nothing happened, fishing normally')
                return False
            self.fail('Fishing Complete did not show after using Sweet Puff')
        self.sleep(random.uniform(0.8, 1.4))
        self.click_at(*ui.FISHING_COMPLETE_CLOSE_AT, after_sleep=random.uniform(1.0, 1.6))
        return True

    def fish_normally(self):
        if not self.fish():
            self.fail('the Fish prompt: not reached')
