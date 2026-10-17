import time

import cv2
from ok import Logger

from src.fishing import detect
from src.fishing.recorder import FrameSaver, frame_signature, heart_lost, is_sailing, view_changed
from src.task.BaseWWTask import BaseWWTask

logger = Logger.get_logger(__name__)


class SailRecorderTask(BaseWWTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "🎥 Sailing Recorder (YOLO data)"
        self.description = ("Saves frames of the boat view while YOU sail by hand, for labelling the obstacle model. "
                            "Sends no input. Start it on the boat, steer round bays, rocks and shores, then stop it.")
        self.default_config.update({
            'Seconds Between Frames': 1.0,
            'Max Minutes': 30,
            'Min Change': 4.0,      # skip a frame that looks like the last saved one (0 to 255)
            'Output Folder': '.tmp/sail_dataset',
        })
        self.config_description = {
            'Seconds Between Frames': 'How often a frame is looked at',
            'Max Minutes': 'The recording stops by itself after this long',
            'Min Change': 'Higher saves fewer, more different frames',
            'Output Folder': 'Relative to the project folder',
        }

    def run(self):
        saver = FrameSaver(self.config.get('Output Folder', '.tmp/sail_dataset'))
        interval = float(self.config.get('Seconds Between Frames', 1.0))
        min_change = float(self.config.get('Min Change', 4.0))
        deadline = time.time() + float(self.config.get('Max Minutes', 30)) * 60
        signature = None
        last_px = None
        hits = 0
        self.log_info(f'Recording sailing frames to {saver.folder}', notify=True)
        while time.time() < deadline:
            self.sleep(interval)
            frame = self.frame
            if frame is None:
                continue
            bgr = cv2.resize(frame, (1920, 1080))
            px = detect.heart_px(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            if not is_sailing(px):
                self.info_set('recording', 'paused: not sailing')
                last_px = None
                continue
            hit = heart_lost(last_px, px)
            last_px = px
            current = frame_signature(bgr)
            if hit or view_changed(signature, current, min_change):
                saver.save(bgr, 'hit' if hit else 'ok')
                signature = current
                hits += hit
            self.info_set('recording', f'{saver.count} frames, {hits} hits')
        self.log_info(f'Recorded {saver.count} frames ({hits} hits) in {saver.folder}', notify=True)
