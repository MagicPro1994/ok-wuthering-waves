import math
import random
import re
import time

import cv2
import numpy as np
import win32api
from ok import Logger

from src.fishing import bait_ui as ui, cargo_grid as cg, detect, escape, human_input as hi
from src.fishing.bait_logic import entry_selected, parse_count, prompt_state
from src.fishing.cargo_plan import Catch, grab_and_drop, needed_catches, plan_cargo, shape_key, shape_matches
from src.fishing.cargo_packer import pack
from src.fishing.nav import Navigator
from src.fishing.worldmap import TargetTracker, WorldMap
from src.fishing.real_input import RealInput
from src.task.BaseWWTask import BaseWWTask
from src.task.WWOneTimeTask import WWOneTimeTask

logger = Logger.get_logger(__name__)


class RequestUnreachable(Exception):
    """The tracked request shows no fishing spot on the minimap, by night or by day: skip it."""


class BoatDamaged(Exception):
    """The boat is down to 2 hearts or fewer: it has to be repaired at the dock before it sails on."""


HUB_ANCHOR = re.compile(r'Fame|Set\s*Sail|Dock\s*Shop', re.IGNORECASE)   # OCR reads "Dock Shop" as "DockShop"


def dial_hour(boxes):
    """Hour on the Set Time dial's centred slot, from OCR (text, x, y) in relative coordinates, or None.

    The centred slot sits at x about 0.5 and y about 0.65; the 'Current Time' value at the top is ignored.
    """
    best = None
    for text, x, y in boxes:
        # the OCR may join the hour with the "Today" under it, so search instead of matching the whole text
        match = re.search(r'(\d{1,2})\s*[:.]\s*(\d{2})', text)
        if match and y > 0.5 and abs(x - 0.5) < 0.08:
            if best is None or abs(x - 0.5) < best[0]:
                best = (abs(x - 0.5), int(match.group(1)))
    return None if best is None else best[1]


def current_hour(boxes):
    """Hour of the 'Current Time' value at the top of the Set Time dial, or None."""
    for text, x, y in boxes:
        match = re.search(r'(\d{1,2})\s*[:.]\s*(\d{2})', text)
        if match and y < 0.3 and abs(x - 0.5) < 0.08:
            return int(match.group(1))
    return None


def is_night_hour(hour):
    return hour >= 19 or hour < 5


def is_day_hour(hour):
    return 7 <= hour < 17


def parse_coords(texts):
    """Player position from the bottom-left readout, e.g. '6962,3089,0 2026-10-14...'."""
    for text in texts:
        match = re.search(r'(-?\d{3,6}),(-?\d{3,6}),-?\d+', text)
        if match:
            return int(match.group(1)), int(match.group(2))
    return None


def next_action(error_deg, target_found):
    if not target_found:
        return 'lost'
    return 'turn' if abs(error_deg) > 12 else 'forward'


def premium_entry(boxes):
    """Vertical centre of the open entry under the 'Premium Request' header, or None.

    `boxes` are OCR (text, y centre) pairs of the Fishing Request list. The entry must lie between the Premium
    and Common headers: with no premium entry the first common request moves up into its place. An open entry
    shows progress such as 0/2 next to its refresh timer; a finished one shows 2/2 and offers Deliver until it is
    delivered, after which the whole Premium section is gone.
    """
    heads = [y for text, y in boxes if 'premium' in text.lower()]
    if not heads:
        return None
    top = min(heads)
    commons = [y for text, y in boxes if 'common' in text.lower() and y > top]
    bottom = min(commons) if commons else float('inf')
    for text, y in sorted(boxes, key=lambda box: box[1]):
        match = re.search(r'(\d+)\s*/\s*(\d+)', text)
        if match and top < y < bottom and int(match.group(1)) <= int(match.group(2)):
            return y
    return None


def common_entry(boxes, skip=0, avoid=()):
    """Vertical centre of the first Common Request entry (progress such as 0/5, or 5/5 waiting to be delivered).

    `boxes` are OCR (text, y centre) pairs of the Fishing Request list. Only the entries below the Common header
    count: the Premium entry above it has its own progress. `skip` passes over that many entries first (requests
    given up on earlier); an entry whose title matches one of the `avoid` patterns is never chosen.
    """
    heads = [y for text, y in boxes if 'common' in text.lower()]
    if not heads:
        return None
    top = min(heads)
    for text, y in sorted(boxes, key=lambda box: box[1]):
        match = re.search(r'(\d+)\s*/\s*(\d+)', text)
        if match and y > top and int(match.group(1)) <= int(match.group(2)):
            # the title sits just above its progress counter
            title = ' '.join(t for t, ty in boxes if y - 70 < ty < y)
            if any(re.search(pattern, title, re.IGNORECASE) for pattern in avoid):
                continue
            if skip <= 0:
                return y
            skip -= 1
    return None


def track_action(texts):
    joined = ' '.join(texts).lower()
    if any(re.fullmatch(r'\s*deliver\s*', t, re.IGNORECASE) for t in texts):
        return 'deliver'
    if 'cancel' in joined:
        return 'tracking'
    if any(re.fullmatch(r'\s*track\s*', t, re.IGNORECASE) for t in texts):
        return 'track'
    return None


def tracked_after_click(texts):
    """True once a click on Track took: the game shows a toast and drops back to the dock hub, or the
    request screen now offers Cancel Tracking."""
    joined = ' '.join(texts).lower()
    return 'cancel tracking' in joined or 'tracking the target' in joined


def catch_list_empty(texts):
    return any('no catch' in t.lower() for t in texts)


def objective_needs(boxes):
    """Remaining fish per objective from the OCR boxes (text, y centre) of the Catches screen's request panel.

    The panel prints a line such as 'Catch Gooberstar' with its '(0/2)' counter in a box of its own (or in the same
    box). Returns {fish name: how many more are wanted}, or None when no counter can be read.
    """
    counters, names = [], []
    for text, y in boxes:
        found = re.search(r'(\d+)\s*/\s*(\d+)', text)
        label = re.sub(r'\(?\s*\d+\s*/\s*\d+\s*\)?', '', text).strip()
        if found:
            counters.append((y, int(found.group(1)), int(found.group(2)), label))
        elif re.match(r'catch\b', label, re.IGNORECASE):
            names.append((y, label))
    needs = {}
    for y, n, m, own_label in counters:
        label = own_label
        if not label and names:
            label = min(names, key=lambda item: abs(item[0] - y))[1] if min(abs(item[0] - y) for item in names) < 0.02 * 1080 else ''
        key = re.sub(r'^catch\s*', '', label, flags=re.IGNORECASE).strip().lower() or f'line{len(needs)}'
        needs[key] = max(0, m - n)
    return needs or None


class FishingTask(WWOneTimeTask, BaseWWTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "🎣 Daily Fishing (Premium + Common Requests)"
        self.description = ("Riccioli Islands 'Old Man and the…': complete the daily Premium Request, then the Common "
                            "Requests (track, sail to the fish, load the request fish, deliver at the dock). "
                            "Start in the open world or on the boat. Needs an elevated run.")
        self.default_config.update({'Max Sail Minutes': 25, 'Premium Request': True, 'Common Requests': 4,
                                    'Max Casts Per Request': 12,
                                    'Skip Requests': 'Coconut', 'Skip Mutant Requests': False})
        self.real = None
        self.expected_objectives = 1    # how many objective lines the tracked request has
        self.objective_names = []       # the objectives of the tracked request, as the request screen named them
        self.given_up = 0               # requests abandoned after too many casts without finishing them
        self.cargo_full = False         # request fish that did not fit in the cargo
        self.shape_line = {}            # fish shape -> the objective line it counts for, learnt while loading
        self.avoid_side = random.choice([-1, 1])
        self.nav = Navigator()      # walls the minimap does not show, remembered for the whole run
        self.world = WorldMap()     # the sea as the minimap showed it, in world coordinates, kept between sails
        self.world.load(self.WORLD_FILE)
        self.tracker = TargetTracker()
        self.world_aim = None       # minimap bearing of the next waypoint of the route over the world map
        self.obstacle_detector = None   # the sailing model, loaded on first use (False when there is no model file)
        self.avoid_until = 0.0
        self.last_here = None
        self.trail = []             # (time, x, y) of the boat while sailing, to notice a pocket it cannot leave
        self.visited = []           # where earlier pockets were, so the next way out tries somewhere new

    def run(self):
        WWOneTimeTask.run(self)
        self.check_tool_key()
        self.real = RealInput(self.hwnd.hwnd)
        self.given_up = 0           # a fresh run passes over nothing
        self.cargo_full = False
        finished = 0
        if self.resumable_at_sea():
            finished += 1 if self.complete_tracked_request(resume=True) else 0
        self.reach_dock_hub()
        if self.config.get('Premium Request', True):
            finished += 1 if self.work_on('premium') else 0
        limit = int(self.config.get('Common Requests', 4))
        commons = 0
        while commons < limit:
            done = self.work_on('common')
            if done is None:
                break
            if done:
                commons += 1
                finished += 1
        self.log_info(f'Fishing done: {finished} requests delivered, {self.given_up} given up', notify=True)

    def work_on(self, kind):
        """Pick the next request of this kind and see it through. True when one was delivered, False when it was
        given up on (the next pick passes it over), None when none is listed."""
        state = self.pick_request(kind)
        if state == 'none':
            self.log_info(f'No {kind} request listed (done for today or refreshing)', notify=True)
            return None
        if state == 'fish':
            if not self.complete_tracked_request():
                self.given_up += 1
                return False
        else:
            self.sell_all()         # it was ready already: delivered by the pick
        return True

    def reach_dock_hub(self):
        """Whatever the start (open world, on the boat, a Catches screen), end on the Dock hub."""
        self.info_set('current task', 'reach the dock hub')
        if self.has_text(HUB_ANCHOR.pattern):
            return
        if self.cargo_screen_open():
            self.handle_catches()
        if detect.heart_px(self.rgb_frame()) >= detect.FULL_HEARTS_PX * 0.3:        # on the boat at sea
            self.teleport_to_dock()
            self.open_dock_hub()
            return
        if self.has_text(r'Return\s+to\s+the\s+dock'):
            self.open_dock_hub()
            return
        self.ensure_main()
        self.go_to_dock()

    def resumable_at_sea(self):
        """On the boat at sea, at a fish spot, with a request being tracked: carry on from there."""
        if detect.heart_px(self.rgb_frame()) < detect.FULL_HEARTS_PX * 0.3 or self.has_text(HUB_ANCHOR.pattern):
            return False
        pairs = detect.progress_pairs(self.texts(*self.HUD_TRACKER_BOX))
        if not pairs or not self.fish_prompt():
            return False
        self.expected_objectives = len(pairs)
        return True

    def complete_tracked_request(self, resume=False):
        """The request on the Dock hub is tracked: clean the cargo, sail, fish until its objectives are done,
        deliver, sell what is left. False when it was given up on after too many casts."""
        if not resume and not self.hub_objectives_done():
            self.sell_all()                 # an empty cargo has room for every fish of the request
            self.prepare_and_sail()
        deadline = time.time() + self.config.get('Max Sail Minutes', 25) * 60
        casts = 0
        misses = 0
        max_casts = int(self.config.get('Max Casts Per Request', 12))
        while not (self.hub_objectives_done() if self.has_text(HUB_ANCHOR.pattern) else self.objectives_done()):
            if time.time() > deadline or casts >= max_casts:
                self.log_info(f'giving this request up after {casts} casts', notify=True)
                self.back_to_hub()
                return False
            try:
                self.sail_to_fish()
            except BoatDamaged:
                self.repair_boat()
                continue
            except RequestUnreachable as error:
                self.log_info(f'giving this request up: {error}', notify=True)
                self.back_to_hub()
                return False
            if not self.fish():
                misses += 1
                if misses >= 8:
                    self.log_info('could not start fishing at the spot: giving this request up', notify=True)
                    self.back_to_hub()
                    return False
                continue
            casts += 1
            self.handle_catches()
            if self.cargo_full:
                self.empty_cargo_at_dock()
        self.deliver()
        self.sell_all()
        return True

    def back_to_hub(self):
        """From the sea (or wherever) to the Dock hub."""
        if self.has_text(HUB_ANCHOR.pattern):
            return
        if detect.heart_px(self.rgb_frame()) >= detect.FULL_HEARTS_PX * 0.05:
            self.teleport_to_dock()
            self.open_dock_hub()
        else:
            self.ensure_main()
            self.go_to_dock()

    def repair_boat(self):
        """Nearly sunk: fast travel to the dock and set sail again, which restores the durability."""
        self.log_info('the boat is nearly sunk: back to the dock to repair it', notify=True)
        self.sleep(3)
        self.back_to_hub()          # the game may have towed it to the dock already
        self.prepare_and_sail()

    def empty_cargo_at_dock(self):
        """Request fish did not fit: go back, sell the whole cargo and set sail again for what is still missing."""
        self.log_info('the cargo is full of fish the request does not need: selling it at the dock', notify=True)
        self.cargo_full = False
        self.teleport_to_dock()
        self.open_dock_hub()
        self.sell_all()
        self.prepare_and_sail()

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
        if self.wait_until(lambda: self.has_text(r'too\s*far\s*away|Summoning'), time_out=4):
            # the boat was left far away (or sank): summoning it empties its storage, which is acceptable here
            self.log_info('the boat is far from this dock: summoning it', notify=True)
            self.click_at(*self.REQUEST_CONFIRM_AT, after_sleep=3.0)

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

    def pick_request(self, kind):
        # Dock hub -> "Fishing Request"; select the premium or the first open common entry and track it unless it
        # already is. 'none' when nothing is listed, 'delivered' when it was complete and has been handed in, else
        # 'fish' (tracked, the Dock hub is showing again).
        self.wait_ocr(match=HUB_ANCHOR, time_out=20, raise_if_not_found=True, settle_time=0.8)
        # Nothing tracked: the hub shows a "Fishing Request" row. A tracked request replaces it with its own
        # panel, whose "..." opens the same Fishing Request screen.
        if not self.click_ocr_text('Fishing Request', 0.0, 0.1, 0.5, 0.4):
            self.click_at(*self.REQUEST_MORE)
        self.sleep(1.2)
        boxes = [(box.name, (box.y + box.height / 2) * 1080 / self.height)
                 for box in (self.ocr(*self.REQUEST_LIST) or [])]
        while True:
            entry_y = premium_entry(boxes) if kind == 'premium' else common_entry(boxes, self.given_up, self.avoided_requests())
            if entry_y is None:
                self.send_key('esc', after_sleep=1.2)       # back to the Dock hub
                return 'none'
            self.click_at(self.PREMIUM_ENTRY_X, (entry_y - 12) / 1080, after_sleep=0.8)
            shown = objective_needs([(box.name, box.y + box.height / 2) for box in
                                     sorted(self.ocr(*self.OBJECTIVES_BOX) or [], key=lambda b: b.y)])
            self.objective_names = sorted(shown or [])
            self.expected_objectives = len(detect.progress_pairs(self.texts(*self.OBJECTIVES_BOX))) or 1
            self.shape_line = {}
            if (kind == 'common' and self.config.get('Skip Mutant Requests', False)
                    and any('mutant' in name for name in self.objective_names)
                    and track_action(self.texts(*self.TRACK_BUTTON)) != 'deliver'):
                self.log_info(f'skipping a Mutant request ({self.objective_names})')
                self.given_up += 1                          # passed over, like one given up on
                continue
            break
        self.log_info(f'{kind} request: {self.expected_objectives} objectives')
        action = track_action(self.texts(*self.TRACK_BUTTON))
        if action is None:
            self.fail(f'Track button not found on the {kind} request')
        if action == 'deliver':
            self.claim_delivery()           # its fish are in the cargo already (a request left over from earlier)
            return 'delivered'
        if action == 'track':
            self.click_at(*self.TRACK_AT, after_sleep=1.0)
            # live: the game answers with a toast and closes the request screen by itself
            # (the toast is brief, so the hub being back on screen counts as well)
            if not self.wait_until(lambda: self.tracked_now(), time_out=6, settle_time=0.3):
                self.fail(f'{kind} request did not become tracked')
        if track_action(self.texts(*self.TRACK_BUTTON)) == 'tracking':
            self.send_key('esc', after_sleep=1.2)     # still on the request screen: back to the dock hub
        return 'fish'

    def avoided_requests(self):
        """Title patterns of the requests that are never taken (config 'Skip Requests', comma separated)."""
        return [part.strip() for part in str(self.config.get('Skip Requests', 'Coconut')).split(',') if part.strip()]

    def tracked_now(self):
        texts = self.texts()
        return tracked_after_click(texts) or any(HUB_ANCHOR.search(t) for t in texts)

    def prepare_and_sail(self):
        self.click_ocr_text('Set Sail')
        self.sleep(1.5)
        self.screenshot('sail_preparation')
        self.click_at(0.928, 0.256)   # Night
        if not self.restore_ticked():         # the box is a toggle that keeps its state between sailings
            self.click_at(0.703, 0.796)   # Automatically restore durability
            self.sleep(0.4)
            if not self.restore_ticked():
                self.log_info('the restore durability box did not tick')
        self.sleep(0.4)
        self.click_at(0.83, 0.93)     # Set Sail
        self.sleep(random.uniform(4.0, 6.0))

    def restore_ticked(self) -> bool:
        """The Automatically restore durability box shows a green tick once it is on."""
        frame = self.frame
        h, w = frame.shape[:2]
        box = frame[int(h * 0.775):int(h * 0.82), int(w * 0.69):int(w * 0.718)].astype(int)
        green = (box[..., 1] > box[..., 2] + 25) & (box[..., 1] > box[..., 0] + 25)
        return int(green.sum()) >= 8

    def set_time_to_night(self):
        self.set_time('night')

    def set_time(self, want='night'):
        right = is_night_hour if want == 'night' else is_day_hour
        self.send_key('esc', after_sleep=1.2)
        self.click_at(0.713, 0.958, after_sleep=2.0)  # clock icon
        # one drag moves the dial about 5 hours (live: 10:00 -> 15:00); read it after every drag
        changed = False
        boxes = self.dial_boxes()
        now = current_hour(boxes)
        if now is not None and right(now):
            logger.info(f'set time: it is {now}:xx already, nothing to change for {want}')
        else:
            for _ in range(6):
                hour = dial_hour(boxes)
                if hour is not None and right(hour):
                    break
                self.real.drag(random.uniform(0.84, 0.88), 0.5, random.uniform(0.12, 0.17), 0.5,
                               random.uniform(0.8, 1.0))
                changed = True
                self.sleep(random.uniform(0.6, 1.0))
                boxes = self.dial_boxes()
            else:
                self.fail(f'could not set the time to {want} on the Set Time dial; OCR read {boxes}')
        if changed:
            self.click_at(0.5, 0.92, after_sleep=3.0)     # Confirm
        else:
            # live: it is night already, so there is nothing to confirm and Confirm left the dial open
            self.click_at(0.943, 0.06, after_sleep=1.5)   # X
        self.send_key('esc', after_sleep=1.0)
        self.close_menus()
        return changed

    MENU_TEXT = r'Set\s*Time|Current\s*Time|Terminal|Resonators|Data\s*Bank'

    def close_menus(self):
        # live: the Esc menu (Terminal) or the Set Time dial was left open and hid the HUD. Close what is showing
        # with its X; nothing is pressed blindly, since Esc on the plain sea view would open the Terminal.
        for _ in range(5):
            if not self.has_text(self.MENU_TEXT):
                return True
            if self.has_text(r'Set\s*Time|Current\s*Time'):
                self.click_at(0.943, 0.06, after_sleep=1.5)     # X of the dial
            else:
                self.click_at(0.958, 0.06, after_sleep=1.5)     # X of the Terminal
        return False

    def dial_boxes(self):
        return [(box.name, (box.x + box.width / 2) / self.width, (box.y + box.height / 2) / self.height)
                for box in (self.ocr(0.2, 0.05, 0.8, 0.8) or [])]

    # ---- sailing -------------------------------------------------------

    F_PROMPT = r'(?<![A-Za-z])Fish(?![A-Za-z])'     # the OCR reads the F key badge as a separate box

    def fish_prompt(self):
        return self.has_text(self.F_PROMPT, 0.45, 0.45, 0.95, 0.8)

    HUB_REQUEST_BOX = (0.03, 0.27, 0.27, 0.40)    # the tracked request's objectives on the Dock hub

    def hub_objectives_done(self):
        for look in range(2):           # twice: a digit read wrong must not count as a finished request
            pairs = detect.progress_pairs(self.texts(*self.HUB_REQUEST_BOX))
            if not (len(pairs) >= max(1, self.expected_objectives) and all(n >= m for n, m in pairs)):
                return False
            if look == 0:
                self.sleep(0.6)
        return True

    HUD_TRACKER_BOX = (0.0, 0.22, 0.3, 0.45)       # the tracked request on the HUD; a long title wraps onto two lines

    OBJECTIVES_BOX = (0.4, 0.44, 1.0, 0.54)     # "Catch Reinfish (1/1)" and its neighbour on the Fishing Request screen

    def objectives_done(self):
        """True once every objective of the tracked request shows its full count on the HUD tracker.

        The HUD must be showing and every objective line must have been read (a line the OCR missed would
        otherwise let the sum look complete).
        """
        if detect.heart_px(self.rgb_frame()) < detect.FULL_HEARTS_PX * 0.3:
            return False
        for look in range(2):           # twice: a digit read wrong must not end the fishing early
            pairs = detect.progress_pairs(self.texts(*self.HUD_TRACKER_BOX))
            self.info_set('progress', ' '.join(f'{n}/{m}' for n, m in pairs))
            if not (len(pairs) >= max(1, self.expected_objectives) and all(n >= m for n, m in pairs)):
                return False
            if look == 0:
                self.sleep(0.8)
        return True

    WORLD_FILE = 'configs/fishing_sea_map.npz'

    CRUISE_RADIUS = 40      # minimap px from the request icon: closer than this the boat takes short presses
    PROMPT_RADIUS = 35      # the [F] Fish prompt is only looked for once the icon is well inside the minimap
    AVOID_FROM_RADIUS = 45  # nearer the icon the fish spot may itself be by a shore, so nothing is avoided
    AVOID_HOLD = 2.5        # seconds the boat keeps straight on after turning away from an obstacle

    def look_ahead(self):
        """What the sailing model sees in the way of the bow (a obstacles.Verdict), or None without a model."""
        if self.obstacle_detector is None:
            from pathlib import Path
            from src.fishing.obstacles import ObstacleDetector
            path = Path(__file__).resolve().parent.parent.parent / 'assets' / 'sail_model' / 'sail.onnx'
            self.obstacle_detector = ObstacleDetector(str(path)) if path.is_file() else False
        if not self.obstacle_detector:
            return None
        seen = self.obstacle_detector.look(cv2.resize(self.frame, (1920, 1080)))
        if seen is None:
            return None
        from src.fishing.obstacles import verdict
        result = verdict(seen)
        if result.action != 'clear':
            logger.info(f'obstacles {[(o.name, round(o.x1, 2), round(o.y1, 2), round(o.x2, 2), round(o.y2, 2)) for o in seen]}'
                        f' -> {result.action} {result.error_deg:.0f}')
        return result

    def sail_to_fish(self):
        # The boat sails along the yellow minimap arrow and A/D turn it (about 80 degrees per second, the camera
        # follows). So steer by the arrow against the purple request icon on the minimap, not by the camera.
        # Far away W stays held and A/D taps steer, so the boat never stops to think; near the icon it takes
        # short presses so it cannot overshoot the fish spot.
        self.info_set('current task', 'sail to fish')
        first_px = detect.heart_px(self.rgb_frame())
        full_px = first_px if first_px >= detect.FULL_HEARTS_PX * 0.5 else detect.FULL_HEARTS_PX
        last_px = full_px
        time_resets = 0         # 1 after the night was set, 2 after the day too
        lost_in_row = 0
        hidden_in_row = 0
        detours = 0
        bumps = 0
        w_down = False
        self.nav.reset_motion()
        self.nav.bumps.clear()      # walls from an earlier sail (a stuck round at this very dock) must not box in the start
        self.visited = []
        self.trail = []
        self.last_here = None
        self.world.new_trip()
        self.tracker.reset()
        self.world_aim = None
        next_pos = 0.0
        now = time.time()
        next_check = now
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
                    if hidden_in_row in (3, 7):
                        # live: the game opens its Terminal menu when its window loses focus
                        self.close_menus()
                    self.sleep(random.uniform(0.5, 1.0))
                    continue
                hidden_in_row = 0
                if time.time() >= next_pos:
                    next_pos = time.time() + 1.6
                    here_now = self.read_coords()
                    if here_now is not None:
                        self.last_here = here_now
                        self.on_position(here_now, rgb)
                        self.update_world(here_now, rgb)
                        self.trail.append((time.time(), here_now[0], here_now[1]))
                        self.trail = [pt for pt in self.trail if time.time() - pt[0] < 120]
                        if escape.in_pocket(self.trail, time.time()):
                            w_down = self.release_w(w_down)
                            self.leave_pocket(here_now)
                            continue
                if state == 'low':
                    raise BoatDamaged('hearts too low')
                if px < last_px * 0.9:
                    # a lost heart is not a reason to stop: keep sailing, the stuck check below handles a real wall
                    self.on_trouble('hit')
                    hit_at, hit_heading = self.read_coords(), detect.arrow_heading(rgb)
                    self.nav.mark_hit(hit_at, hit_heading)
                    if hit_at is not None and hit_heading is not None:
                        self.world.mark_wall(hit_at, (-hit_heading) % 360)
                last_px = max(px, 1)
                heading = detect.arrow_heading(rgb)
                bearing = detect.minimap_target_bearing(rgb)
                radius = detect.minimap_target_radius(rgb)
                found = heading is not None and bearing is not None
                if found and radius < self.PROMPT_RADIUS and self.fish_prompt():
                    return
                if not found or radius >= self.AVOID_FROM_RADIUS:
                    seen = self.look_ahead()
                    if seen is not None and seen.action != 'clear':
                        if seen.action == 'blocked':
                            if detours >= 12:
                                self.fail('boxed in by land and detours did not free the boat')
                            w_down = self.release_w(w_down)
                            self.on_trouble('boxed')
                            self.detour(detours)
                            detours += 1
                        else:
                            w_down = self.release_w(w_down)
                            self.turn_boat(seen.error_deg)
                            self.hold_key('w', random.uniform(0.8, 1.4))      # carry on past what was in the way
                            self.avoid_until = time.time() + self.AVOID_HOLD
                        continue
                    if seen is not None and time.time() < self.avoid_until:
                        # just got clear of something: go straight on before the minimap steers back at it
                        self.hold_key('w', random.uniform(0.6, 1.0))
                        continue
                aim = bearing
                if found:
                    if radius >= 45:
                        if self.world_aim is not None:
                            aim = self.world_aim         # the route over everything the minimap has shown so far
                        else:
                            aim = self.nav.aim(bearing)      # walls bumped into earlier
                            if aim is not None:
                                aim = self.clear_bearing(rgb, aim, radius)   # land on the minimap
                    if aim is None:
                        # land on every side: back off and go round instead of pushing in
                        if detours >= 12:
                            self.fail('boxed in by land and detours did not free the boat')
                        w_down = self.release_w(w_down)
                        self.on_trouble('boxed')
                        if self.last_here is not None:
                            self.leave_pocket(self.last_here)
                        else:
                            self.detour(detours)
                        detours += 1
                        continue
                err = detect.heading_error(heading, aim) if found else 0.0
                action = next_action(err, found)
                if action == 'lost':
                    # on the fish spot the icon sits under the yellow arrow and cannot be seen: the prompt tells
                    if self.fish_prompt():
                        return
                    lost_in_row += 1
                    # live: the marker needs a few seconds after setting sail (or after the time changed) to show
                    if lost_in_row >= (10 if time_resets == 0 else 15):
                        if time_resets >= 2:
                            raise RequestUnreachable('request icon not found on the minimap by night or by day')
                        w_down = self.release_w(w_down)
                        # the rule: no marker on the map means the time is wrong, so night first (19:00), then day;
                        # a time that was right already changes nothing, so there is no point waiting on it
                        for want in ('night', 'day')[time_resets:]:
                            time_resets += 1
                            if self.set_time(want):
                                break
                        lost_in_row = 0
                    elif lost_in_row % 3 == 0:
                        self.hold_key('w', random.uniform(0.5, 1.0))      # get off the dock while it is awaited
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
                    self.nav.reset_motion()
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
                    # a boat that stops moving with W held has hit something the minimap does not show
                    here = self.read_coords()
                    h_now = detect.arrow_heading(self.rgb_frame())
                    hit = self.nav.update(here, h_now, True)
                    logger.info(f'nav pos={here} heading={h_now} target={bearing:.0f} aim={aim:.0f} '
                                f'radius={radius:.0f} map={self.nav.mapping()} walls={bumps}')
                    if hit:
                        self.world.mark_wall(here, (-h_now) % 360)
                        bumps += 1
                        if bumps > 40:
                            self.fail('boat keeps hitting obstacles and walls did not free it')
                        self.info_set('current task', f'bumped {bumps}')
                        w_down = self.release_w(w_down)
                        self.on_trouble('stuck')
                        self.hold_key('s', random.uniform(0.8, 1.4))
                        self.nav.reset_motion()
                    next_check = time.time() + random.uniform(1.1, 1.6)
                self.sleep(random.uniform(0.25, 0.5))
        finally:
            self.release_w(w_down)
            try:
                self.world.save(self.WORLD_FILE)
            except OSError as error:
                logger.info(f'could not keep the sea map: {error}')

    def leave_pocket(self, here):
        # Minutes of sailing inside a small area: the route and the camera keep pointing at the same wall. Pick the
        # direction with the most open water on the minimap, towards ground not been on yet, and sail out that way.
        self.visited.extend((x, y) for _, x, y in self.trail)
        self.visited.append(tuple(here))
        self.visited = self.visited[-200:]
        mask = detect.minimap_danger(self.rgb_frame())
        bearing = escape.pick_escape(mask, here, self.visited)
        self.trail = []
        self.on_trouble('pocket')
        logger.info(f'pocket at {here}: leaving towards {bearing:.0f}')
        self.info_set('current task', f'leave pocket {bearing:.0f}')
        end = time.time() + 10
        while time.time() < end:
            rgb = self.rgb_frame()
            heading = detect.arrow_heading(rgb)
            seen = self.look_ahead()
            if seen is not None and seen.action == 'blocked':
                self.hold_key('s', random.uniform(0.8, 1.2))
                self.turn_boat(random.choice([-1, 1]) * random.uniform(60, 100))
            elif seen is not None and seen.action == 'turn':
                self.turn_boat(seen.error_deg)
                self.hold_key('w', random.uniform(0.8, 1.2))
            else:
                error = detect.heading_error(heading, bearing) if heading is not None else 0.0
                if abs(error) > 15:
                    self.turn_boat(error)
                else:
                    self.hold_key('w', random.uniform(0.8, 1.2))

    def update_world(self, here, rgb):
        """Draw the minimap into the world map and plan the way to the request icon over everything seen so far."""
        self.world.observe(detect.minimap_danger(rgb), here)
        bearing = detect.minimap_target_bearing(rgb)
        radius = detect.minimap_target_radius(rgb)
        self.tracker.observe(here, bearing, radius)
        target = self.tracker.estimate(here, bearing)
        if target is None:
            self.world_aim = None
            return
        plan = self.world.plan(here, target, prefer=self.avoid_side)
        self.world_aim = None if plan.blocked else plan.bearing(here)
        logger.info(f'route from {here} to {target[0]:.0f},{target[1]:.0f}: aim {self.world_aim} '
                    f'({len(plan.path)} cells, {plan.left:.0f} units left at its end)')

    def on_position(self, here, rgb):
        """Hook called whenever the boat's coordinates were read while sailing. SailTestTask records the minimap."""

    def on_trouble(self, kind):
        """Hook called when the boat loses hearts ('hit'), stops against something ('stuck') or has no way out
        ('boxed'). Does nothing here; SailTestTask records the frames."""

    def release_w(self, w_down):
        if w_down:
            self.send_key_up('w')
        return False

    def clear_bearing(self, rgb, bearing, radius):
        # Plan a route over the whole minimap disc and steer along it, so land is rounded from far off and a bay
        # closed on its far side is never entered. Near the target (icon well inside the rim) the final approach
        # ignores land: the fish spot itself may be by a shore. None means every way out is blocked.
        if radius is not None and radius < 45:
            return bearing
        route = detect.plan_route(detect.minimap_danger(rgb), bearing, radius, self.avoid_side, margin=16)
        if route.blocked:
            return None
        turned = detect.heading_error(bearing, route.bearing)
        if abs(turned) > 10:
            self.avoid_side = 1 if turned > 0 else -1     # keep going round the same side next time
        return route.bearing

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
    # ---- utility wheel -------------------------------------------------

    def wheel_open(self):
        # the utility counts and the centre's "Release to switch" only exist while the wheel is open
        return (parse_count(self.texts(*ui.WHEEL_BOX)) is not None
                or self.has_text(r'Release\s*to\s*switch', *ui.WHEEL_CENTER_BOX))

    def hovering(self, name):
        # the wheel's centre prints "Release to switch" and the name of the utility under the cursor
        def shown():
            if self.has_text(ui.UTILITY_NAMES[name], *ui.WHEEL_CENTER_BOX):
                return True
            # the Sweet Puff label is not known for sure: any hovered utility that is not Baiting counts for it
            # (the teleport's label is not known either; the centre text is logged so it can be fixed)
            if name in ('sweet_puff', 'teleport') and self.has_text(r'Release\s*to\s*switch', *ui.WHEEL_CENTER_BOX):
                others = [ui.UTILITY_NAMES[n] for n in ui.UTILITY_NAMES if n != name]
                return not any(self.has_text(o, *ui.WHEEL_CENTER_BOX) for o in others)
            return False
        return self.wait_until(shown, time_out=1.5)

    def point_cursor(self, fx, fy):
        # the wheel picks the slot under the real cursor when the key is released (see CombatCheck's tab wheel)
        x, y = hi.offset_point(fx, fy)
        px, py = int(x * self.width), int(y * self.height)
        self.move(px, py)
        abs_x, abs_y = self.executor.interaction.capture.get_abs_cords(px, py)
        win32api.SetCursorPos((int(abs_x), int(abs_y)))

    def equip(self, name):
        for _ in range(3):
            if self.pick_utility(name):
                return
            self.sleep(random.uniform(0.8, 1.2))
        self.fail(f'could not pick {name} on the utility wheel')

    def pick_utility(self, name):
        # Tab is a hold-to-open wheel: hold it, point at the utility, release to select. The OCR of the counts on the
        # wheel misses now and then, so only the hovered name in the centre is taken as proof.
        wheel_key = self.key_config.get('Wheel Key')
        self.send_key_down(wheel_key)
        confirmed = False
        try:
            self.wait_until(self.wheel_open, time_out=2)
            self.sleep(random.uniform(0.3, 0.6))
            self.point_cursor(0.5, 0.5)       # the wheel reads the move from its centre, wherever the cursor was parked
            self.sleep(random.uniform(0.2, 0.4))
            for _ in range(3):
                self.point_cursor(*ui.UTILITY_SLOTS[name])
                self.sleep(random.uniform(0.4, 0.8))
                if self.hovering(name):
                    confirmed = True
                    break
                self.point_cursor(0.5, 0.5)
                self.sleep(random.uniform(0.2, 0.4))
        finally:
            self.send_key_up(wheel_key)
        self.sleep(random.uniform(0.4, 0.7))
        self.wait_until(lambda: not self.wheel_open(), time_out=3)
        if not confirmed:
            self.log_info(f'the wheel never showed {name} under the cursor')
        return confirmed

    # ---- deliver and sell ----------------------------------------------

    def teleport_to_dock(self):
        # the boat's utility on the Tool Key fast travels to the dock from anywhere at sea
        self.equip('teleport')                              # the Tool Key uses whichever utility is selected
        self.log_info(f'wheel centre after switching: {self.texts(*ui.WHEEL_CENTER_BOX)}')
        # the utility has a cooldown of about 110 s after each use: until it ends the key does nothing, so ask again
        asked = self.wait_until(self.ask_fast_travel, time_out=150)
        if not asked:
            self.fail('the fast travel to the dock never offered itself (cooldown?)')
        self.click_at(0.657, 0.628, after_sleep=2.0)       # Confirm fast travel to the dock
        if not self.wait_until(lambda: self.has_text('Return to the dock'), time_out=60):
            self.fail('the boat did not arrive at the dock after the fast travel')

    def ask_fast_travel(self) -> bool:
        """Press the Tool Key; True when the 'Fast Travel to Dock' dialog came up."""
        self.send_key(self.key_config.get('Tool Key'), after_sleep=1.5)
        if self.has_text(r'Fast\s*Travel'):
            return True
        self.sleep(6)
        return False

    def deliver(self):
        self.info_set('current task', 'deliver')
        self.teleport_to_dock()
        self.open_dock_hub()
        self.click_at(*self.REQUEST_MORE, after_sleep=1.5)            # the tracked request's "..." opens its screen
        if not self.wait_until(lambda: track_action(self.texts(*self.TRACK_BUTTON)) == 'deliver', time_out=8):
            self.fail(f'no Deliver button on the request screen; read {self.texts(*self.TRACK_BUTTON)}')
        self.claim_delivery()

    def claim_delivery(self):
        """On the request screen with its Deliver button showing: hand in, close the rewards, back to the Dock hub."""
        self.click_at(*self.TRACK_AT, after_sleep=2.0)                 # Deliver sits where Track does
        if not self.wait_until(lambda: self.has_text(r'Items\s*Obtained'), time_out=8):
            self.fail('delivering did not show the rewards')
        self.sleep(random.uniform(0.8, 1.4))
        for _ in range(6):
            if not self.has_text(r'Items\s*Obtained|blank\s*area'):
                break
            self.real.click(0.5, 0.85)              # "Tap the blank area to continue"
            self.sleep(random.uniform(1.5, 2.2))
        self.send_key('esc', after_sleep=1.2)                          # the request list: back to the Dock hub
        if not self.wait_until(lambda: self.has_text(HUB_ANCHOR.pattern), time_out=8):
            self.fail('the Dock hub did not come back after delivering')

    # ---- dock hub, prompts and cargo (shared with the bait fishing) ------

    def open_dock_hub(self):
        # the first F can land while the boat still drifts and the prompt flickers: press it again
        for _ in range(4):
            self.send_key('f', after_sleep=random.uniform(1.8, 2.6))
            if self.wait_until(lambda: self.has_text(HUB_ANCHOR.pattern), time_out=5):
                self.sleep(0.8)
                return
            if prompt_state(self.prompt_texts()).fish:
                self.select_entry(r'return\s+to\s+the\s+dock', 'Return to the dock')
            elif not prompt_state(self.prompt_texts()).return_dock:
                self.nudge_until('s', lambda: prompt_state(self.prompt_texts()).return_dock,
                                 tries=6, label='the Return to the dock prompt')
        self.fail('the Dock hub did not open after pressing F')

    HUB_CARGO_BOX = (0.80, 0.84, 0.88, 0.89)    # "N/52" above the Dock Shop button of the Dock hub

    def hub_cargo_used(self):
        for _ in range(3):
            used = cg.parse_cargo_used(self.texts(*self.HUB_CARGO_BOX))
            if used is not None:
                return used
            self.sleep(0.4)
        return None

    def sell_all(self):
        """At the Dock hub: sell what is in the cargo, then (key C) what is left in the Catch List."""
        self.info_set('current task', 'sell all')
        self.click_at(0.835, 0.93, after_sleep=2.0)         # Dock Shop: it opens on the cargo
        self.screenshot('dock_shop')
        self.sell_view('cargo')
        self.send_key('c', after_sleep=1.2)                 # the Catch List: fish that never went into the cargo
        self.screenshot('dock_shop_catch_list')
        self.sell_view('catch list')
        self.send_key('esc', after_sleep=1.2)
        if not self.wait_until(lambda: self.has_text(HUB_ANCHOR.pattern), time_out=8):
            self.fail('the Dock hub did not come back after Sell All')
        left = self.hub_cargo_used()
        self.log_info(f'sell all: cargo {left}/52 after the sale')
        if left:
            self.fail(f'cargo still holds {left} after Sell All')

    def sell_view(self, label):
        """Press Sell All on the Dock Shop view showing, if it has anything to sell."""
        if self.has_text(r'No\s*Catch') or not self.has_text(r'Sell\s*All'):
            self.log_info(f'sell all: nothing to sell in the {label}')
            return
        if not self.click_ocr_text(r'Sell\s*All'):
            self.fail(f'Sell All not found in the Dock Shop ({label})')
        self.sleep(1.2)
        if self.has_text(r'Request\s*items\s*for\s*sale'):    # the dialog's Confirm button, not its "Confirm" title
            self.click_at(*self.REQUEST_CONFIRM_AT, after_sleep=2.0)
        for _ in range(4):
            if not self.has_text(r'Items\s*Obtained|blank\s*area'):
                break
            self.real.click(*self.REWARD_CLOSE_AT)          # "Tap the blank area to continue"
            self.sleep(random.uniform(1.2, 1.8))

    REQUEST_CONFIRM_AT = (0.656, 0.628)    # Confirm of "You have selected Request items for sale. Continue?"

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

    def cargo_screen_open(self):
        # the Catches screen's title and list header, top left; the fishing mini-game also says "Catch x1" and "Cargo"
        return self.has_text(r'Catches|Catch\s*List', 0.0, 0.0, 0.3, 0.2)

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
            if self.quick_sale_open():       # the panel covers the Finish button
                self.click_at(*self.QUICK_SALE_CLOSE_AT, after_sleep=random.uniform(0.6, 0.9))
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

    def survey_catches(self, slots=None):
        # Clicking a card shows its fish as a draft at the top-left of the grid: diff it against the frame without one
        # (the caller cleared any draft). The value is read off the card. Every draft goes back to the list with Q
        # before the next click: clicking another card while a valid draft is up would auto-place it, and the list
        # would reflow under the survey.
        base = self.rgb_frame()
        occupied = cg.occupied_cells(base)
        catches = []
        for slot in (range(cg.MAX_CARDS) if slots is None else slots):
            self.click_at(*cg.card_center(slot), after_sleep=random.uniform(0.6, 0.9))
            cells = cg.read_draft(base, self.rgb_frame(), occupied)
            if slot == 0:
                self.screenshot('cargo_first_card')
            value = cg.parse_value(self.texts(*cg.PRICE_BOX))
            if value is None:
                value = cg.parse_value(self.texts(*cg.card_box(slot)))
            if not cells:
                if value is not None:
                    self.fail(f'cargo: slot {slot} shows a value of {value} but no draft on the grid; nothing was lost')
                if slots is not None:
                    continue
                break
            self.clear_draft()
            if value is None:
                self.log_info(f'slot {slot}: card value unreadable, using its {len(cells)} cells as the value')
                value = len(cells)
            catches.append(Catch(slot, cells, value))
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
        # placed fish are part of the base and no draft may show in it
        self.clear_draft()
        base = self.settled_frame()
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
            self.clear_draft()      # a valid draft left up would be auto-placed by the next click
            return False
        used_before = self.cargo_used()
        if used_before is None:
            self.log_info(f'slot {catch.slot}: Cargo counter unreadable, leaving it')
            self.clear_draft()      # a valid draft left up would be auto-placed by the next click
            return False
        if cells != placement.cells:
            grab, drop = grab_and_drop(cells, placement)
            src, dst = cg.cell_center(*grab), cg.cell_center(*drop)
            self.real.drag(src[0], src[1], dst[0], dst[1], random.uniform(0.8, 1.1))
            self.sleep(random.uniform(0.5, 0.8))
            landed = cg.read_draft(base, self.rgb_frame(), occupied)
            if landed != placement.cells and self.already_placed(placement, used_before):
                self.log_info(f'slot {catch.slot}: the drop already confirmed the fish on the planned cells')
                return True
            if landed != placement.cells:
                self.screenshot('cargo_after_drag')
                self.log_info(f'slot {catch.slot}: the draft did not land on the planned cells, leaving it: '
                              f'planned {sorted(placement.cells)}, read {sorted(landed)}, '
                              f'dragged {sorted(cells)} from {grab} to {drop}')
                self.clear_draft()      # a valid draft left up would be auto-placed by the next click
                return False
        self.send_key('space', after_sleep=random.uniform(0.6, 1.0))
        want = used_before + len(placement.cells)
        if not self.wait_until(lambda: self.cargo_used() == want, time_out=self.PLACE_WAIT):
            self.log_info(f'slot {catch.slot}: the Cargo counter did not reach {want}, leaving it')
            self.clear_draft()      # a valid draft left up would be auto-placed by the next click
            return False
        return True

    def already_placed(self, placement, used_before):
        # A drop can leave the fish confirmed already: the draft read then finds no draft. Trust the counter and the
        # board together: it rose by the fish's size and the planned cells are occupied.
        want = used_before + len(placement.cells)
        if not self.wait_until(lambda: self.cargo_used() == want, time_out=1.5):
            return False
        board = cg.occupied_cells(self.settled_frame())
        return all(cell in board for cell in placement.cells)

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

    # ---- states (filled in by later tasks) -----------------------------

    def fish(self):
        """At the [F] Fish prompt: start the fishing and wait until the Catches (cargo) screen opens."""
        self.info_set('current task', 'fish')
        for _ in range(4):
            if prompt_state(self.prompt_texts()).fish:
                break
            self.hold_key('w', hi.nudge_press())
            self.sleep(random.uniform(0.3, 0.7))
        else:
            if not prompt_state(self.prompt_texts()).fish:
                self.log_info('the Fish prompt is not there: back to steering for the spot')
                return False
        if prompt_state(self.prompt_texts()).return_dock:
            self.select_entry(r'(?<![A-Za-z])Fish(?![A-Za-z])', 'Fish')     # two entries: the Fish one may not be first
        # a lone entry is always the selected one: its F badge is not reliably read by OCR
        self.send_key('f', after_sleep=random.uniform(0.8, 1.4))
        # the mini-game finishes by itself in 15 to 30 s and opens the Cargo screen
        done = lambda: self.cargo_screen_open() or self.has_text(r'Fishing\s*Complete')
        if not self.wait_until(done, time_out=75):
            self.fail('mini-game did not finish')
        self.sleep(random.uniform(0.6, 1.0))
        shown = time.time()
        for attempt in range(12):
            if self.cargo_screen_open():
                self.log_info(f'the Catches screen opened {time.time() - shown:.1f}s after the result, {attempt} taps')
                return True
            # the result screen waits for a tap on a blank area (live: it ignores the first few seconds of taps)
            self.real.click(*self.RESULT_CLOSE_AT)
            self.sleep(random.uniform(1.8, 2.6))
        self.fail('the Catches screen did not open after the fishing result')

    RESULT_CLOSE_AT = (0.5, 0.9)
    CATCH_PANEL_BOX = (0.0, 0.64, 0.42, 0.84)      # the tracked request's objectives under the Catch List

    def catch_need(self):
        """How many more fish each objective of the tracked request wants, by fish name, read off the Catches screen
        (it counts what is in the cargo); None when no counters can be read."""
        merged = None
        for _ in range(2):              # a digit read wrong (2/3 as 3/3) must not close an objective: the larger need wins
            boxes = sorted(self.ocr(*self.CATCH_PANEL_BOX) or [], key=lambda box: box.y)
            seen = objective_needs([(box.name, box.y + box.height / 2) for box in boxes])
            if seen:
                merged = {name: max(need, (merged or {}).get(name, 0)) for name, need in seen.items()} |                          {name: need for name, need in (merged or {}).items() if name not in seen}
            self.sleep(0.3)
        return merged

    def handle_catches(self):
        """On the Catches screen after fishing: load the fish the tracked request still needs into the cargo (cards
        with the purple badge), leave the rest in the Catch List (Sell All sells them), then Finish."""
        self.info_set('current task', 'load request fish')
        if not self.wait_until(self.cargo_screen_open, time_out=15):
            self.fail('Cargo screen not open')
        self.sleep(random.uniform(0.6, 1.0))
        self.screenshot('catches_screen')
        self.clear_draft()
        rgb = self.rgb_frame()
        wanted = [slot for slot in range(cg.MAX_CARDS) if cg.request_badge(rgb, slot)]
        remaining = self.catch_need()
        if remaining is not None:
            # a line the OCR dropped is not a finished objective (finished ones stay listed in green): assume one more
            for name in self.objective_names:
                remaining.setdefault(name, 1)
        self.log_info(f'catches: request fish on cards {wanted}, objectives still needing {remaining}')
        if wanted and (remaining is None or sum(remaining.values()) > 0):
            catches = self.survey_catches(wanted)
            if remaining is not None:
                catches = needed_catches(catches, self.shape_line, remaining)
            plan = plan_cargo(cg.free_cells(cg.occupied_cells(rgb)), catches)
            self.log_info('catches: ' + ', '.join(f'slot {c.slot} -> {sorted(p.cells)}' for c, p in plan)
                          + f' ({len(plan)} of {len(catches)} fit)')
            before = remaining
            for catch, placement in plan:       # highest slot first: the cards below do not shift
                if not self.place_catch(catch, placement):
                    self.log_info(f'catches: slot {catch.slot} could not be placed, leaving it in the Catch List')
                    self.cargo_full = True
                    continue
                after = self.catch_need()
                if before and after:
                    grew = [name for name in after if name in before and after[name] < before[name]]
                    if len(grew) == 1:          # this shape is the fish of that objective: later ones are told apart
                        self.shape_line[shape_key(catch.cells)] = grew[0]
                before = after
            if len(plan) < len(catches):
                self.log_info(f'catches: {len(catches) - len(plan)} request fish did not fit in the cargo')
                self.cargo_full = True
        self.clear_draft()
        if self.quick_sale_open():              # the panel covers the Finish button
            self.click_at(*self.QUICK_SALE_CLOSE_AT, after_sleep=random.uniform(0.6, 0.9))
        for attempt in range(3):
            if attempt == 0:
                self.click_at(*ui.FINISH_AT, after_sleep=random.uniform(1.0, 1.6))
            else:
                self.log_info('Finish did not take: pressing it with the real cursor')
                self.real.click(*ui.FINISH_AT)
            if self.wait_until(lambda: not self.cargo_screen_open(), time_out=5):
                break
        else:
            self.fail('the Catches screen did not close after Finish')
        self.sleep(random.uniform(0.8, 1.4))
