import re
from typing import Iterable, NamedTuple, Optional, Sequence, Tuple

_COUNT = re.compile(r'\d{1,5}')
_FISH = re.compile(r'(?<![A-Za-z])Fish(?![A-Za-z])')


def parse_count(texts: Iterable[str]) -> Optional[int]:
    for text in texts:
        value = text.strip()
        if _COUNT.fullmatch(value):
            return int(value)
    return None


def dialog_open(texts: Iterable[str]) -> bool:
    joined = ' '.join(texts).lower()
    return 'use' in joined and 'bait' in joined


def sandworm_launched(texts: Iterable[str]) -> bool:
    return any('launched' in text.lower() for text in texts)


class PromptState(NamedTuple):
    return_dock: bool
    fish: bool


def prompt_state(texts: Iterable[str]) -> PromptState:
    texts = list(texts)
    return PromptState(
        return_dock=any(re.search(r'return\s+to\s+the\s+dock', t, re.IGNORECASE) for t in texts),
        fish=any(_FISH.search(t) for t in texts),
    )


def entry_selected(boxes: Sequence[Tuple[str, float]], pattern: str) -> Optional[bool]:
    """Whether the prompt entry matching `pattern` carries the F key badge (is the selected one).

    `boxes` are OCR (text, y centre) pairs of the prompt list in fractions of the frame height.
    """
    regex = re.compile(pattern, re.IGNORECASE)
    rows = [y for text, y in boxes if regex.search(text.strip())]
    if not rows:
        return None
    keys = [y for text, y in boxes if text.strip().strip('[]').upper() == 'F']
    return any(abs(key - rows[0]) < 0.025 for key in keys)


class RoundGuard:
    """Stops the loop when the bait count has not dropped for `max_stalls` rounds in a row."""

    def __init__(self, max_stalls: int = 2):
        self.max_stalls = max_stalls
        self.stalls = 0

    def record(self, before: int, after: int) -> bool:
        self.stalls = self.stalls + 1 if after >= before else 0
        return self.stalls < self.max_stalls
