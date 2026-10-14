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
