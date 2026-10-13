from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, List, Optional, Tuple

Cell = Tuple[int, int]


def normalize(cells: Iterable[Cell]) -> FrozenSet[Cell]:
    cells = list(cells)
    if not cells:
        return frozenset()
    min_r = min(r for r, _ in cells)
    min_c = min(c for _, c in cells)
    return frozenset((r - min_r, c - min_c) for r, c in cells)


def rotate_cw(cells: Iterable[Cell]) -> FrozenSet[Cell]:
    return normalize((c, -r) for r, c in cells)


def orientations(cells: Iterable[Cell]) -> List[Tuple[int, FrozenSet[Cell]]]:
    result, seen = [], set()
    current = normalize(cells)
    for rotation in range(4):
        if current not in seen:
            seen.add(current)
            result.append((rotation, current))
        current = rotate_cw(current)
    return result


@dataclass(frozen=True)
class Placement:
    rotations: int
    cells: FrozenSet[Cell]
    origin: Cell


def pack(free: Iterable[Cell], pieces: Dict[str, Iterable[Cell]]) -> Optional[Dict[str, Placement]]:
    free_set = set(free)
    order = sorted(pieces, key=lambda name: -len(list(pieces[name])))
    shapes = {name: orientations(pieces[name]) for name in order}
    result: Dict[str, Placement] = {}

    def place(index: int, available: set) -> bool:
        if index == len(order):
            return True
        name = order[index]
        for rotation, shape in shapes[name]:
            for r0, c0 in sorted(available):
                cells = frozenset((r + r0, c + c0) for r, c in shape)
                if cells <= available:
                    result[name] = Placement(rotation, cells, (r0, c0))
                    if place(index + 1, available - cells):
                        return True
                    del result[name]
        return False

    return result if place(0, free_set) else None


def pack_best(free, pieces, values, required=(), node_limit=200_000):
    free_set = set(free)
    required = set(required)
    order = sorted(pieces, key=lambda n: (n not in required, -values.get(n, 0), -len(list(pieces[n]))))
    shapes = {name: orientations(pieces[name]) for name in order}
    suffix = [sum(values.get(n, 0) for n in order[i:]) for i in range(len(order) + 1)]
    best = {'value': -1, 'plan': None}
    current: Dict[str, Placement] = {}
    nodes = [0]

    def search(i: int, available: set, value: int):
        nodes[0] += 1
        if nodes[0] > node_limit and best['plan'] is not None:
            return
        if value + suffix[i] <= best['value']:
            return
        if i == len(order):
            best['value'], best['plan'] = value, dict(current)
            return
        name = order[i]
        for rotation, shape in shapes[name]:
            for r0, c0 in sorted(available):
                cells = frozenset((r + r0, c + c0) for r, c in shape)
                if cells <= available:
                    current[name] = Placement(rotation, cells, (r0, c0))
                    search(i + 1, available - cells, value + values.get(name, 0))
                    del current[name]
        if name not in required:
            search(i + 1, available, value)

    search(0, free_set, 0)
    return best['plan']
