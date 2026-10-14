import math
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


HUB_ANCHOR = re.compile(r'Fame|Set\s*Sail|Dock\s*Shop', re.IGNORECASE)   # OCR reads "Dock Shop" as "DockShop"


def dial_hour(boxes):
    """Hour on the Set Time dial's centred slot, from OCR (text, x, y) in relative coordinates, or None.

    The centred slot sits at x about 0.5 and y about 0.65; the 'Current Time' value at the top is ignored.
    """
    best = None
    for text, x, y in boxes:
        match = re.fullmatch(r'\s*(\d{1,2}):(\d{2})\s*', text)
        if match and y > 0.5 and abs(x - 0.5) < 0.06:
            if best is None or abs(x - 0.5) < best[0]:
                best = (abs(x - 0.5), int(match.group(1)))
    return None if best is None else best[1]


def is_night_hour(hour):
    return hour >= 19 or hour < 5


def parse_coords(texts):
    """Player position from the bottom-left readout, e.g. '6962,3089,0 2026-10-14...'."""
    for text in texts:
        match = re.search(r'(-?\d{3,6}),(-?\d{3,6}),-?\d+', text)
        if match:
            return int(match.group(1)), int(match.group(2))
    return None


def moved(before, after, min_units=8):
    # live: a 2 s W press moves about 27 units; an unreadable position never counts as stuck
    if before is None or after is None:
        return True
    return math.hypot(after[0] - before[0], after[1] - before[1]) >= min_units


def next_action(error_deg, target_found):
    if not target_found:
        return 'lost'
    return 'turn' if abs(error_deg) > 12 else 'forward'


def premium_entry(boxes):
    """Vertical centre of the open entry under the 'Premium Request' header, or None.

    `boxes` are OCR (text, y centre) pairs of the Fishing Request list. The entry must lie between the Premium
    and Common headers: with no premium entry the first common request moves up into its place. An open entry
    shows progress such as 0/2 next to its refresh timer; a finished one shows 2/2.
    """
    heads = [y for text, y in boxes if 'premium' in text.lower()]
    if not heads:
        return None
    top = min(heads)
    commons = [y for text, y in boxes if 'common' in text.lower() and y > top]
    bottom = min(commons) if commons else float('inf')
    for text, y in sorted(boxes, key=lambda box: box[1]):
        match = re.search(r'(\d+)\s*/\s*(\d+)', text)
        if match and top < y < bottom and int(match.group(1)) < int(match.group(2)):
            return y
    return None


def track_action(texts):
    joined = ' '.join(texts).lower()
    if 'cancel' in joined:
        return 'tracking'
    if any(re.fullmatch(r'\s*track\s*', t, re.IGNORECASE) for t in texts):
        return 'track'
    return None


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
        self.avoid_side = random.choice([-1, 1])

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
        self.reach_planck()
        self.send_key('f', after_sleep=2.0)                       # opens the Dock hub

    def reach_planck(self):
        # Fast travel can land a few steps from Planck. Wait out the loading screen, then walk forward in short
        # uneven steps until the "[F] Check the dock" prompt shows.
        self.wait_until(lambda: self.in_team_and_world() or self.has_text('Check the dock'), time_out=90)
        for _ in range(12):
            if self.has_text('Check the dock'):
                self.sleep(random.uniform(0.3, 0.8))
                return
            self.hold_key('w', random.uniform(0.5, 1.2))
            self.sleep(random.uniform(0.3, 0.7))
        self.fail('Planck not found after fast travel: no "Check the dock" prompt')

    REQUEST_MORE = (0.2375, 0.296)               # "..." on the tracked request in the dock hub
    REQUEST_LIST = (0.0, 0.08, 0.4, 0.8)        # OCR region of the request list on the left
    PREMIUM_ENTRY_X = 0.19
    TRACK_BUTTON = (0.78, 0.86, 0.98, 0.95)      # OCR region of Track / Cancel Tracking
    TRACK_AT = (0.877, 0.903)

    def pick_premium(self):
        # Dock hub -> "Fishing Request"; select the premium entry and track it unless it already is.
        self.wait_ocr(match=HUB_ANCHOR, time_out=20, raise_if_not_found=True, settle_time=0.8)
        # Nothing tracked: the hub shows a "Fishing Request" row. A tracked request replaces it with its own
        # panel, whose "..." opens the same Fishing Request screen.
        if not self.click_ocr_text('Fishing Request', 0.0, 0.1, 0.5, 0.4):
            self.click_at(*self.REQUEST_MORE)
        self.sleep(1.2)
        boxes = [(box.name, (box.y + box.height / 2) * 1080 / self.height)
                 for box in (self.ocr(*self.REQUEST_LIST) or [])]
        entry_y = premium_entry(boxes)
        if entry_y is None:
            return False
        self.click_at(self.PREMIUM_ENTRY_X, (entry_y - 12) / 1080, after_sleep=0.8)
        action = track_action(self.texts(*self.TRACK_BUTTON))
        if action is None:
            self.fail('Track button not found on the premium request')
        if action == 'track':
            self.click_at(*self.TRACK_AT, after_sleep=1.0)
            if track_action(self.texts(*self.TRACK_BUTTON)) != 'tracking':
                self.fail('premium request did not become tracked')
        self.send_key('esc', after_sleep=1.2)     # back to the dock hub
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
        # one drag moves the dial about 5 hours (live: 10:00 -> 15:00); read it after every drag
        for _ in range(6):
            hour = dial_hour(self.dial_boxes())
            if hour is not None and is_night_hour(hour):
                break
            self.real.drag(random.uniform(0.84, 0.88), 0.5, random.uniform(0.12, 0.17), 0.5,
                           random.uniform(0.8, 1.0))
            self.sleep(random.uniform(0.6, 1.0))
        else:
            self.fail('could not set the time to night on the Set Time dial')
        self.click_at(0.5, 0.92, after_sleep=3.0)     # Confirm
        self.send_key('esc', after_sleep=1.0)

    def dial_boxes(self):
        return [(box.name, (box.x + box.width / 2) / self.width, (box.y + box.height / 2) / self.height)
                for box in (self.ocr(0.2, 0.5, 0.8, 0.8) or [])]

    # ---- sailing -------------------------------------------------------

    F_PROMPT = r'\[?F\]?\s*Fish'

    def fish_prompt(self):
        return self.has_text(self.F_PROMPT, 0.45, 0.45, 0.95, 0.8)

    def objectives_done(self):
        done, total = detect.parse_progress(self.texts(0.0, 0.22, 0.26, 0.36))
        self.info_set('progress', f'{done}/{total}')
        return total > 0 and done >= total

    CRUISE_RADIUS = 40      # minimap px from the request icon: closer than this the boat takes short presses
    PROMPT_RADIUS = 60      # the [F] Fish prompt is only looked for once the icon is well inside the minimap

    def sail_to_fish(self):
        # The boat sails along the yellow minimap arrow and A/D turn it (about 80 degrees per second, the camera
        # follows). So steer by the arrow against the purple request icon on the minimap, not by the camera.
        # Far away W stays held and A/D taps steer, so the boat never stops to think; near the icon it takes
        # short presses so it cannot overshoot the fish spot.
        self.info_set('current task', 'sail to fish')
        first_px = detect.heart_px(self.rgb_frame())
        full_px = first_px if first_px >= detect.FULL_HEARTS_PX * 0.5 else detect.FULL_HEARTS_PX
        last_px = full_px
        reset_done = False
        lost_in_row = 0
        hidden_in_row = 0
        stuck = 0
        detours = 0
        clear_moves = 0
        pos = self.read_coords()
        w_down = False
        now = time.time()
        next_check = now + random.uniform(3.0, 4.5)
        next_ease = now + hi.cruise_gap()
        try:
            while True:
                rgb = self.rgb_frame()
                px = detect.heart_px(rgb)
                state = detect.hearts_state(px, full_px)
                if state == 'hidden':
                    # a menu or dialog covers the HUD: wait for it rather than reading zero hearts
                    hidden_in_row += 1
                    if hidden_in_row >= 12:
                        self.fail('HUD not visible while sailing (a menu is open?)')
                    w_down = self.release_w(w_down)
                    self.sleep(random.uniform(0.5, 1.0))
                    continue
                hidden_in_row = 0
                if state == 'low':
                    self.fail('hearts too low, aborting')
                if px < last_px * 0.9:
                    w_down = self.release_w(w_down)
                    self.avoid_damage()
                    last_px = max(px, 1)
                    continue
                last_px = max(px, 1)
                heading = detect.arrow_heading(rgb)
                bearing = detect.minimap_target_bearing(rgb)
                radius = detect.minimap_target_radius(rgb)
                found = heading is not None and bearing is not None
                if found and radius < self.PROMPT_RADIUS and self.fish_prompt():
                    return
                aim = bearing
                if found:
                    aim = self.clear_bearing(rgb, bearing, radius)
                    if aim is None:
                        # land on every side: back off and go round instead of pushing in
                        if detours >= 6:
                            self.fail('boxed in by land and detours did not free the boat')
                        w_down = self.release_w(w_down)
                        self.detour(detours)
                        detours += 1
                        continue
                err = detect.heading_error(heading, aim) if found else 0.0
                action = next_action(err, found)
                if action == 'lost':
                    lost_in_row += 1
                    if lost_in_row >= 4:
                        if reset_done:
                            self.fail('request icon not found on the minimap after a time reset')
                        w_down = self.release_w(w_down)
                        self.set_time_to_night()
                        reset_done = True
                        lost_in_row = 0
                    self.sleep(random.uniform(0.4, 0.9))
                    continue
                lost_in_row = 0
                if radius < self.CRUISE_RADIUS:
                    w_down = self.release_w(w_down)
                    if action == 'turn':
                        self.turn_boat(err)
                    else:
                        self.hold_key('w', hi.approach_press())
                    self.sleep(random.uniform(0.3, 0.7))
                    continue
                # cruise: W stays held, A/D taps steer
                if not w_down:
                    self.send_key_down('w')
                    w_down = True
                if action == 'turn':
                    self.turn_boat(err)
                now = time.time()
                if now >= next_ease:
                    self.send_key_up('w')
                    self.sleep(random.uniform(0.15, 0.5))
                    self.send_key_down('w')
                    next_ease = now + hi.cruise_gap()
                if now >= next_check:
                    here = self.read_coords()
                    if moved(pos, here, 12):
                        stuck = 0
                        clear_moves += 1
                        if clear_moves >= 3:      # only a long clean run forgives earlier detours
                            detours = max(0, detours - 1)
                            clear_moves = 0
                    else:
                        stuck += 1
                        clear_moves = 0
                    pos = here if here is not None else pos
                    if stuck >= 2:
                        if detours >= 6:
                            self.fail('boat is stuck and detours did not free it')
                        w_down = self.release_w(w_down)
                        self.detour(detours)
                        detours += 1
                        stuck = 0
                        pos = self.read_coords() or pos
                    next_check = time.time() + random.uniform(3.0, 4.5)
                self.sleep(random.uniform(0.25, 0.5))
        finally:
            self.release_w(w_down)

    def release_w(self, w_down):
        if w_down:
            self.send_key_up('w')
        return False

    def clear_bearing(self, rgb, bearing, radius):
        # Aim at the cheapest direction near the target whose minimap wedge is open water, sticking to the
        # side already being rounded. Near the target (icon well inside the rim) the final approach ignores
        # land: the fish spot itself may be by a shore.
        if radius is not None and radius < 45:
            return bearing
        steered = detect.steer_bearing(detect.minimap_danger(rgb), bearing, self.avoid_side)
        if steered is None:
            return None
        aim, offset = steered
        if offset:
            self.avoid_side = 1 if offset > 0 else -1
        return aim

    def read_coords(self):
        return parse_coords(self.texts(0.0, 0.95, 0.3, 1.0))

    def detour(self, attempt):
        # Pinned against land or rock without taking damage: back off, then sail well clear sideways.
        # The side alternates and the leg grows with each failed attempt, so a wall is eventually rounded.
        side = 1 if attempt % 2 == 0 else -1
        self.info_set('current task', f'detour {attempt + 1}')
        self.hold_key('s', random.uniform(1.5, 2.5))
        self.turn_boat(side * random.uniform(80, 120))
        self.hold_key('w', random.uniform(3.0, 4.0) + 1.5 * attempt)

    def turn_boat(self, error_deg):
        # positive error: the target is anticlockwise of the heading, so turn left (W, if held, stays held)
        self.send_key('a' if error_deg > 0 else 'd', down_time=hi.turn_hold_seconds(error_deg))
        self.sleep(hi.short_pause() + 0.2)

    def avoid_damage(self):
        # Land, ghost or tornado: back off, turn about 90 degrees away, continue.
        self.hold_key('s', random.uniform(1.0, 2.0))
        self.turn_boat(random.choice([-1, 1]) * random.uniform(80, 100))
        self.hold_key('w', random.uniform(1.5, 2.5))
    # ---- deliver and sell ----------------------------------------------

    def deliver(self):
        self.info_set('current task', 'deliver')
        self.send_key(self.key_config.get('Tool Key'), after_sleep=1.5)
        self.click_at(0.657, 0.628, after_sleep=2.0)       # Confirm fast travel to the dock
        self.wait_until(lambda: self.has_text('Return to the dock'), time_out=60)
        self.send_key('f', after_sleep=2.5)
        self.click_at(*self.REQUEST_MORE, after_sleep=1.0)  # request "..."
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
