from src.char.BaseChar import BaseChar


class Baizhi(BaseChar):

    def do_perform(self):
        if self.has_intro:
            self.logger.debug('has_intro wait click 1.2 sec')
        else:
            self.wait_down()
        # basic attack hits build Concentration (max 4), consumed by E / heavy for Concerto/Resonance Energy refunds
        self.continues_normal_attack(1.2)
        self.click_liberation(con_less_than=1)
        if not self.click_resonance()[0]:
            self.heavy_attack()
        self.click_echo()
        self.switch_next_char()
