"""Time-aware rectangular occupancy grid."""

from __future__ import annotations

import math
from collections import defaultdict, deque
from datetime import date
from typing import DefaultDict, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .models import BlockRequest, Cell, Placement


class GridYard:
    """A reusable stockyard grid with entrances and permanently blocked cells.

    Rows represent yard depth and columns represent yard width.  Grid dimensions
    use ``floor(real_size / cell_size)`` so the model never allocates space
    outside the physical boundary.
    """

    def __init__(
        self,
        code: str,
        width_m: float,
        depth_m: float,
        cell_size_m: float = 2.0,
        entrances: Sequence[Cell] = ((0, 0),),
        blocked_cells: Iterable[Cell] = (),
    ) -> None:
        if not code:
            raise ValueError("Yard code cannot be blank")
        if min(width_m, depth_m, cell_size_m) <= 0:
            raise ValueError("Yard dimensions and cell size must be positive")

        self.code = code
        self.width_m = float(width_m)
        self.depth_m = float(depth_m)
        self.cell_size_m = float(cell_size_m)
        self.rows = math.floor(self.depth_m / self.cell_size_m)
        self.cols = math.floor(self.width_m / self.cell_size_m)
        if self.rows < 1 or self.cols < 1:
            raise ValueError("Cell size is larger than the yard")

        self.entrances = tuple(dict.fromkeys(entrances))
        self.blocked_cells = frozenset(blocked_cells)
        if not self.entrances:
            raise ValueError("At least one entrance cell is required")
        for cell in (*self.entrances, *self.blocked_cells):
            if not self.in_bounds(cell):
                raise ValueError(f"Cell outside yard boundary: {cell}")
        if set(self.entrances) & set(self.blocked_cells):
            raise ValueError("An entrance cell cannot be permanently blocked")

        self._placements: Dict[str, Placement] = {}
        self._placements_by_cell: DefaultDict[Cell, List[Placement]] = defaultdict(list)

    @property
    def usable_cell_count(self) -> int:
        # Entrances remain clear and are not available for storage.
        return self.rows * self.cols - len(self.blocked_cells) - len(self.entrances)

    @property
    def usable_area_m2(self) -> float:
        return self.usable_cell_count * self.cell_size_m**2

    def in_bounds(self, cell: Cell) -> bool:
        row, col = cell
        return 0 <= row < self.rows and 0 <= col < self.cols

    def rectangle_cells(
        self, top_row: int, left_col: int, row_span: int, col_span: int
    ) -> Tuple[Cell, ...]:
        return tuple(
            (row, col)
            for row in range(top_row, top_row + row_span)
            for col in range(left_col, left_col + col_span)
        )

    def placements(self) -> Tuple[Placement, ...]:
        return tuple(self._placements.values())

    def get_placement(self, block_code: str) -> Placement:
        return self._placements[block_code]

    def active_placements(self, day: date) -> Tuple[Placement, ...]:
        return tuple(
            placement
            for placement in self._placements.values()
            if placement.active_on(day)
        )

    def occupants(self, cell: Cell, day: date) -> Tuple[Placement, ...]:
        return tuple(
            placement
            for placement in self._placements_by_cell.get(cell, ())
            if placement.active_on(day)
        )

    def is_rectangle_free(
        self,
        block: BlockRequest,
        top_row: int,
        left_col: int,
        row_span: int,
        col_span: int,
    ) -> bool:
        if min(top_row, left_col) < 0:
            return False
        if top_row + row_span > self.rows or left_col + col_span > self.cols:
            return False

        cells = self.rectangle_cells(top_row, left_col, row_span, col_span)
        unavailable = self.blocked_cells | frozenset(self.entrances)
        if any(cell in unavailable for cell in cells):
            return False
        for cell in cells:
            if any(block.overlaps(placement.block) for placement in self._placements_by_cell[cell]):
                return False
        return True

    def add_placement(self, placement: Placement) -> None:
        if placement.block_code in self._placements:
            raise ValueError(f"Block is already placed: {placement.block_code}")
        if not self.is_rectangle_free(
            placement.block,
            placement.top_row,
            placement.left_col,
            placement.row_span,
            placement.col_span,
        ):
            raise ValueError(f"Placement is not feasible: {placement.block_code}")
        expected_cells = self.rectangle_cells(
            placement.top_row,
            placement.left_col,
            placement.row_span,
            placement.col_span,
        )
        if placement.cells != expected_cells:
            raise ValueError(f"Placement cells do not match its rectangle: {placement.block_code}")

        self._placements[placement.block_code] = placement
        for cell in placement.cells:
            self._placements_by_cell[cell].append(placement)

    def remove_placement(self, block_code: str) -> Placement:
        placement = self._placements.pop(block_code)
        for cell in placement.cells:
            self._placements_by_cell[cell].remove(placement)
            if not self._placements_by_cell[cell]:
                del self._placements_by_cell[cell]
        return placement

    def bfs_tree(
        self,
        day: Optional[date] = None,
        ignore_block_codes: Iterable[str] = (),
    ) -> Tuple[Dict[Cell, int], Dict[Cell, Optional[Cell]]]:
        """Return BFS distance and predecessor maps from all entrances.

        When ``day`` is supplied, cells occupied on that day are obstacles.
        Without a day, the tree represents the permanent yard geometry only.
        """

        ignored = set(ignore_block_codes)
        dynamic_blocked: Set[Cell] = set(self.blocked_cells)
        if day is not None:
            for placement in self.active_placements(day):
                if placement.block_code not in ignored:
                    dynamic_blocked.update(placement.cells)

        distance: Dict[Cell, int] = {}
        predecessor: Dict[Cell, Optional[Cell]] = {}
        queue = deque()
        for entrance in self.entrances:
            if entrance in dynamic_blocked:
                continue
            distance[entrance] = 0
            predecessor[entrance] = None
            queue.append(entrance)

        while queue:
            row, col = queue.popleft()
            for neighbor in (
                (row - 1, col),
                (row + 1, col),
                (row, col - 1),
                (row, col + 1),
            ):
                if (
                    self.in_bounds(neighbor)
                    and neighbor not in dynamic_blocked
                    and neighbor not in distance
                ):
                    distance[neighbor] = distance[(row, col)] + 1
                    predecessor[neighbor] = (row, col)
                    queue.append(neighbor)
        return distance, predecessor

    @staticmethod
    def reconstruct_path(
        target: Cell, predecessor: Dict[Cell, Optional[Cell]]
    ) -> Tuple[Cell, ...]:
        if target not in predecessor:
            return ()
        path = []
        current: Optional[Cell] = target
        while current is not None:
            path.append(current)
            current = predecessor[current]
        path.reverse()
        return tuple(path)

    def utilization(self, day: date) -> float:
        if self.usable_cell_count == 0:
            return 0.0
        occupied = {
            cell
            for placement in self.active_placements(day)
            for cell in placement.cells
        }
        return len(occupied) / self.usable_cell_count

    def render_ascii(self, day: date) -> str:
        """Return a compact text view useful for tests and small examples."""

        canvas = [["." for _col in range(self.cols)] for _row in range(self.rows)]
        for row, col in self.blocked_cells:
            canvas[row][col] = "#"
        for row, col in self.entrances:
            canvas[row][col] = "E"
        for placement in self.active_placements(day):
            marker = placement.block_code[-1].upper()
            for row, col in placement.cells:
                canvas[row][col] = marker
        return "\n".join("".join(row) for row in canvas)
