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


def next_action(error_deg, marker_found):
    if not marker_found:
        return 'sweep'
    return 'turn' if abs(error_deg) > 4 else 'forward'


def premium_listed(texts):
    premium = [t.lower() for t in texts if 'premium' in t.lower()]
    return bool(premium) and not all('refresh' in t for t in premium)


def catch_list_empty(texts):
    return any('no catch' in t.lower() for t in texts)


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

    def click_ocr_text(self, pattern, x=0, y=0, to_x=1, to_y=1):
        regex = re.compile(pattern, re.IGNORECASE)
        for box in self.ocr(x, y, to_x, to_y) or []:
            if regex.search(box.name):
                self.click(box, after_sleep=random.uniform(0.4, 0.7))
                return True
        return False

    # ---- dock, premium request, preparation ----------------------------

    EVENTS_KEY = 'f1'
    PERMANENT_TAB = (0.04, 0.48)
    OLD_MAN_LIST = (0.08, 0.1, 0.24, 1.0)   # OCR region of the event list
    EVENT_GO = (0.872, 0.915)
    FAST_TRAVEL = (0.832, 0.931)

    def go_to_dock(self):
        self.info_set('current task', 'go to dock')
        self.send_key(self.EVENTS_KEY, after_sleep=2.0)
        self.click_at(*self.PERMANENT_TAB, after_sleep=1.5)
        for _ in range(8):
            if self.click_ocr_text('Old Man', *self.OLD_MAN_LIST):
                break
            # the list only scrolls with a real cursor drag
            self.real.drag(0.14, 0.85, 0.14, random.uniform(0.5, 0.6), random.uniform(0.7, 0.9))
            self.sleep(1.0)
        else:
            self.fail('Old Man event not found in the Events list')
        self.sleep(1.0)
        self.click_at(*self.EVENT_GO, after_sleep=3.0)            # opens the map on the dock
        self.click_at(*self.FAST_TRAVEL, after_sleep=2.0)
        self.wait_ocr(match=re.compile('Check the dock', re.I), time_out=90, raise_if_not_found=True,
                      settle_time=1.0)
        self.send_key('f', after_sleep=2.0)                       # opens the Dock hub

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

    # ---- sailing -------------------------------------------------------

    F_PROMPT = r'\[?F\]?\s*Fish'

    def fish_prompt(self):
        return self.has_text(self.F_PROMPT, 0.45, 0.45, 0.95, 0.8)

    def objectives_done(self):
        done, total = detect.parse_progress(self.texts(0.0, 0.22, 0.26, 0.36))
        self.info_set('progress', f'{done}/{total}')
        return total > 0 and done >= total

    def sail_to_fish(self):
        self.info_set('current task', 'sail to fish')
        full_px = max(detect.heart_px(self.rgb_frame()), 1)
        last_px = full_px
        reset_done = False
        lost_in_row = 0
        stuck = 0
        last_x = None
        while True:
            if self.fish_prompt():
                return
            rgb = self.rgb_frame()
            px = detect.heart_px(rgb)
            if detect.hearts_from_px(px, full_px) <= 2:
                self.fail('hearts too low, aborting')
            if px < last_px * 0.9:
                self.avoid_damage()
                last_px = max(px, 1)
                continue
            last_px = max(px, 1)
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

    # ---- deliver and sell ----------------------------------------------

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

    # ---- states (filled in by later tasks) -----------------------------

    def fish(self): raise NotImplementedError
    def handle_catches(self): raise NotImplementedError
    def release_selected_fish(self): raise NotImplementedError  # needs cargo_grid (Task 9)
