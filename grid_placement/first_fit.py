"""BFS-ordered, rehandle-aware first-fit rectangle placement."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import List, Sequence, Tuple

from .blocking import estimate_incremental_rehandles
from .grid import GridYard
from .models import BlockRequest, Placement


class NoFeasiblePlacement(RuntimeError):
    pass


@dataclass(frozen=True)
class FirstFitConfig:
    """Controls candidate ordering and the rehandle-aware fallback."""

    prefer_zero_rehandle: bool = True
    max_preferred_rehandles: int = 0
    fallback_to_lowest_rehandle: bool = True

    def __post_init__(self) -> None:
        if self.max_preferred_rehandles < 0:
            raise ValueError("max_preferred_rehandles cannot be negative")


class FirstFitPlacer:
    def __init__(
        self, yard: GridYard, config: FirstFitConfig = FirstFitConfig()
    ) -> None:
        self.yard = yard
        self.config = config

    def _orientations(self, block: BlockRequest) -> Tuple[Tuple[int, int, bool], ...]:
        row_span = math.ceil(block.length_m / self.yard.cell_size_m)
        col_span = math.ceil(block.width_m / self.yard.cell_size_m)
        orientations = [(row_span, col_span, False)]
        if block.allow_rotation and row_span != col_span:
            orientations.append((col_span, row_span, True))
        return tuple(orientations)

    def feasible_candidates(self, block: BlockRequest) -> List[Placement]:
        """Enumerate collision-free placements in BFS access order."""

        dynamic_distance, _dynamic_parent = self.yard.bfs_tree(block.inbound_date)
        _static_distance, static_parent = self.yard.bfs_tree()
        candidates: List[Placement] = []

        for row_span, col_span, rotated in self._orientations(block):
            if row_span > self.yard.rows or col_span > self.yard.cols:
                continue
            for top_row in range(self.yard.rows - row_span + 1):
                for left_col in range(self.yard.cols - col_span + 1):
                    if not self.yard.is_rectangle_free(
                        block, top_row, left_col, row_span, col_span
                    ):
                        continue
                    cells = self.yard.rectangle_cells(
                        top_row, left_col, row_span, col_span
                    )
                    reachable = [cell for cell in cells if cell in dynamic_distance]
                    if not reachable:
                        continue
                    access_cell = min(
                        reachable,
                        key=lambda cell: (dynamic_distance[cell], cell[0], cell[1]),
                    )
                    access_path = self.yard.reconstruct_path(access_cell, static_parent)
                    candidate = Placement(
                        block=block,
                        top_row=top_row,
                        left_col=left_col,
                        row_span=row_span,
                        col_span=col_span,
                        rotated=rotated,
                        cells=cells,
                        access_path=access_path,
                        access_distance=dynamic_distance[access_cell],
                    )
                    candidates.append(
                        replace(
                            candidate,
                            estimated_rehandles=estimate_incremental_rehandles(
                                self.yard, candidate
                            ),
                        )
                    )

        candidates.sort(
            key=lambda item: (
                item.access_distance,
                item.top_row,
                item.left_col,
                item.rotated,
            )
        )
        return candidates

    def choose(self, block: BlockRequest) -> Placement:
        """Choose the first BFS candidate satisfying the handling policy."""

        candidates = self.feasible_candidates(block)
        if not candidates:
            raise NoFeasiblePlacement(
                f"{block.code}: no collision-free and reachable rectangle"
            )

        if not self.config.prefer_zero_rehandle:
            return candidates[0]
        for candidate in candidates:
            if (
                candidate.estimated_rehandles
                <= self.config.max_preferred_rehandles
            ):
                return candidate
        if self.config.fallback_to_lowest_rehandle:
            return min(
                candidates,
                key=lambda item: (
                    item.estimated_rehandles,
                    item.access_distance,
                    item.top_row,
                    item.left_col,
                    item.rotated,
                ),
            )
        raise NoFeasiblePlacement(
            f"{block.code}: feasible rectangles exist, but all exceed the "
            f"preferred rehandle limit {self.config.max_preferred_rehandles}"
        )

    def place(self, block: BlockRequest) -> Placement:
        placement = self.choose(block)
        self.yard.add_placement(placement)
        return placement

    def place_many(
        self, blocks: Sequence[BlockRequest]
    ) -> Tuple[List[Placement], List[Tuple[BlockRequest, str]]]:
        """Place blocks by arrival date and return successes and failures."""

        placed: List[Placement] = []
        failures: List[Tuple[BlockRequest, str]] = []
        for block in sorted(blocks, key=lambda item: (item.inbound_date, item.code)):
            try:
                placed.append(self.place(block))
            except NoFeasiblePlacement as exc:
                failures.append((block, str(exc)))
        return placed, failures
