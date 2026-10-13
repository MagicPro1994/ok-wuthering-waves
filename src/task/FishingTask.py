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
