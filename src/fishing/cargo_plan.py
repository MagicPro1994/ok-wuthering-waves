from dataclasses import dataclass
from typing import FrozenSet, Iterable, List, Sequence, Tuple

from src.fishing.cargo_packer import Placement, normalize, pack_best

Cell = Tuple[int, int]


@dataclass(frozen=True)
class Catch:
    slot: int
    cells: FrozenSet[Cell]
    value: int


def plan_cargo(free: Iterable[Cell], catches: Sequence[Catch]) -> List[Tuple[Catch, Placement]]:
    """Value-optimised set of catches that fits the free cells, highest slot first.

    Highest slot first: placing a card removes it from the list, so the slots below it do not shift.
    """
    by_slot = {c.slot: c for c in catches}
    pieces = {str(c.slot): c.cells for c in catches}
    values = {str(c.slot): c.value for c in catches}
    plan = pack_best(free, pieces, values)
    if not plan:
        return []
    placed = [(by_slot[int(name)], placement) for name, placement in plan.items()]
    return sorted(placed, key=lambda item: -item[0].slot)


def shape_matches(preview: Iterable[Cell], placement: Placement) -> bool:
    return normalize(preview) == normalize(placement.cells)


def grab_and_drop(preview: Iterable[Cell], placement: Placement) -> Tuple[Cell, Cell]:
    cells = list(preview)
    top = min(r for r, _ in cells)
    left = min(c for _, c in cells)
    grab = min(cells)
    target_top = min(r for r, _ in placement.cells)
    target_left = min(c for _, c in placement.cells)
    return grab, (target_top + grab[0] - top, target_left + grab[1] - left)
