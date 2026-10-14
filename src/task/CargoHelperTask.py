from src.fishing.real_input import RealInput
from src.task.BaitFishingTask import BaitFishingTask
from src.task.WWOneTimeTask import WWOneTimeTask


class CargoHelperTask(BaitFishingTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "🐟 Cargo Helper (Catches screen)"
        self.description = ("Open the Catches screen after fishing; reads every fish, optimises the cargo and drags them in, "
                            "confirming each with Space. Does NOT press Finish.")
        self.default_config.pop('Max Rounds', None)

    def run(self):
        WWOneTimeTask.run(self)
        self.real = RealInput(self.hwnd.hwnd)
        self.load_cargo(finish=False)
        self.log_info('Cargo arranged, press Finish yourself', notify=True)
