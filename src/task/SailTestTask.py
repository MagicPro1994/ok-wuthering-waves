import random
import time

import cv2
from ok import Logger

from src.fishing import detect
from src.fishing.real_input import RealInput
from src.fishing.recorder import FrameSaver, RecentFrames
from src.task.FishingTask import HUB_ANCHOR, FishingTask
from src.task.WWOneTimeTask import WWOneTimeTask

logger = Logger.get_logger(__name__)


class SailTestTask(FishingTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "🧪 Sail Test (records bumps)"
        self.description = ("Sails to the tracked request like the daily fishing does, without fishing, and saves "
                            "frames whenever the boat is hit, stuck or boxed in. After each round it fast travels "
                            "back to the dock, repairs and sails again. Start it on the boat, at sea or at the dock, "
                            "with the request tracked. Needs an elevated run.")
        self.default_config.pop('Max Sail Minutes', None)
        self.default_config.update({'Rounds': 3, 'Max Minutes Per Round': 6,
                                    'Output Folder': '.tmp/sail_dataset', 'Seconds Between Frames': 2.5})
        self.saver = None
        self.recent = RecentFrames()
        self.deadline = 0.0
        self.next_plain = 0.0

    def run(self):
        WWOneTimeTask.run(self)
        self.real = RealInput(self.hwnd.hwnd)
        self.saver = None       # nothing is recorded until the boat is confirmed
        results = []
        rounds = int(self.config.get('Rounds', 3))
        self.close_menus()
        if not self.has_text('Return to the dock') and not self.has_text(HUB_ANCHOR.pattern):
            self.back_to_dock()         # every round, the first too, starts from the dock
        for number in range(1, rounds + 1):
            self.saver = None
            self.ready_to_sail()
            self.saver = FrameSaver(self.config.get('Output Folder', '.tmp/sail_dataset'))
            self.recent = RecentFrames()
            self.deadline = time.time() + float(self.config.get('Max Minutes Per Round', 6)) * 60
            self.next_plain = 0.0
            started = time.time()
            self.log_info(f'Sail test round {number}/{rounds}: recording to {self.saver.folder}')
            try:
                self.sail_to_fish()
                outcome = 'reached the [F] Fish prompt'
            except TimeoutError:
                outcome = 'time is up'
            except Exception as error:      # FishingTask.fail already saved a screenshot
                outcome = f'failed: {error}'
            results.append(f'round {number}: {outcome} after {time.time() - started:.0f}s, {self.saver.count} frames')
            self.log_info(results[-1], notify=True)
            if number < rounds:
                self.saver = None
                self.back_to_dock()
        self.log_info('Sail test done:\n' + '\n'.join(results), notify=True)

    def back_to_dock(self):
        self.info_set('current task', 'back to the dock')
        self.close_menus()
        self.teleport_to_dock()

    def ready_to_sail(self):
        # Hearts at 2 or fewer abort the sailing loop. At the dock a damaged boat is repaired by sailing again with
        # "Automatically restore durability" ticked, which prepare_and_sail does.
        self.close_menus()
        px = detect.heart_px(self.rgb_frame())
        at_dock = self.has_text('Return to the dock')
        full = detect.hearts_from_px(px) >= detect.MAX_HEARTS
        if self.hearts_ok() and (full or not at_dock):
            return
        on_hub = self.has_text(HUB_ANCHOR.pattern)
        if (not at_dock and not on_hub
                and detect.hearts_state(px) == 'low'):      # too damaged to sail: fast travel to the dock first
            self.log_info('Boat is nearly sunk at sea: fast travelling to the dock to repair it', notify=True)
            self.teleport_to_dock()
            at_dock = True
        if not at_dock and not on_hub:
            self.fail('Start on the boat with the fishing request tracked, at sea, at the dock or on the Dock screen')
        self.log_info('Boat is damaged or docked: sailing again from the dock before the test', notify=True)
        for _ in range(4):
            if self.has_text(HUB_ANCHOR.pattern):
                break
            if at_dock:
                self.send_key('f', after_sleep=random.uniform(1.8, 2.6))     # the first F can land while the boat drifts
            self.wait_until(lambda: self.has_text(HUB_ANCHOR.pattern), time_out=5)
        else:
            self.fail('the Dock hub did not open after pressing F')
        self.sleep(0.8)
        for attempt in range(2):
            self.prepare_and_sail()
            if self.wait_until(self.hearts_ok, time_out=30, settle_time=1.0):
                return
            self.log_info(f'Not at sea after set sail (attempt {attempt + 1})')
            if not self.has_text(HUB_ANCHOR.pattern):
                break               # no Dock screen to retry on: do not click blindly at sea
        self.fail('The boat did not set sail from the dock with full durability')

    def hearts_ok(self):
        return detect.hearts_state(detect.heart_px(self.rgb_frame())) == 'ok'

    def rgb_frame(self):
        # called on every pass of the sailing loop: keep the recent frames and a plain frame now and then
        if self.saver is not None:
            if time.time() > self.deadline:
                raise TimeoutError('sail test time is up')
            bgr = self.bgr_frame()
            self.recent.push(bgr)
            if time.time() >= self.next_plain:
                self.saver.save(bgr, 'ok')
                self.next_plain = time.time() + float(self.config.get('Seconds Between Frames', 2.5))
        return super().rgb_frame()

    def bgr_frame(self):
        return cv2.resize(self.frame, (1920, 1080))

    def on_position(self, here, rgb):
        # the minimap with the boat's coordinates, to replay the planning offline
        if self.saver is None:
            return
        import json
        folder = self.saver.folder / 'trace'
        folder.mkdir(parents=True, exist_ok=True)
        index = len(list(folder.glob('*.png')))
        cv2.imwrite(str(folder / f'{index:04d}.png'), cv2.cvtColor(rgb[:260, :260], cv2.COLOR_RGB2BGR))
        record = {'i': index, 't': time.time(), 'pos': list(here), 'heading': detect.arrow_heading(rgb),
                  'bearing': detect.minimap_target_bearing(rgb), 'radius': detect.minimap_target_radius(rgb)}
        with open(folder / 'trace.jsonl', 'a', encoding='utf-8') as out:
            out.write(json.dumps(record) + '\n')

    def on_trouble(self, kind):
        if self.saver is None:
            return
        for bgr in self.recent.take():
            self.saver.save(bgr, 'approach')
        self.saver.save(self.bgr_frame(), kind)
        self.info_set('recording', f'{self.saver.count} frames; last: {kind}')
