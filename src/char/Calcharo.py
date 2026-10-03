import time

from src.char.BaseChar import BaseChar


class Calcharo(BaseChar):
    def do_perform(self):
        if self.has_intro:
            self.logger.debug('Calcharo wait intro animation')
            self.sleep(1)
            self.task.wait_in_team_and_world(time_out=3, raise_if_not_found=False)
            self.check_combat()
        self.wait_intro(1.2)
        self.click_echo(time_out=0)
        if self.click_liberation():
            # Deathblade Gear: Hounds Roar hits build Killing Intent, 5 enables heavy Death Messenger
            start = time.time()
            while not self.is_mouse_forte_full() and time.time() - start < 4 and not self.need_fast_perform():
                self.click(after_sleep=0.1)
                self.check_combat()
            self.heavy_click_forte(self.is_mouse_forte_full)
            return self.switch_next_char()
        self.click_resonance()
        # Mercy (3 Cruelty) must not depend on E being on cooldown
        self.heavy_click_forte(self.is_mouse_forte_full)
        self.switch_next_char()
