"""Data objects shared by the grid-placement modules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Tuple


Cell = Tuple[int, int]


@dataclass(frozen=True)
class BlockRequest:
    """A rectangular block that occupies the yard over a date interval."""

    code: str
    length_m: float
    width_m: float
    height_m: float
    inbound_date: date
    outbound_date: date
    allow_rotation: bool = True

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("Block code cannot be blank")
        if min(self.length_m, self.width_m, self.height_m) <= 0:
            raise ValueError(f"{self.code}: block dimensions must be positive")
        if self.outbound_date < self.inbound_date:
            raise ValueError(f"{self.code}: outbound_date precedes inbound_date")

    def active_on(self, day: date) -> bool:
        """The outbound day is treated as an occupied day."""

        return self.inbound_date <= day <= self.outbound_date

    def overlaps(self, other: "BlockRequest") -> bool:
        return not (
            self.outbound_date < other.inbound_date
            or other.outbound_date < self.inbound_date
        )


@dataclass(frozen=True)
class Placement:
    """A block placed on a rectangular set of grid cells."""

    block: BlockRequest
    top_row: int
    left_col: int
    row_span: int
    col_span: int
    rotated: bool
    cells: Tuple[Cell, ...]
    access_path: Tuple[Cell, ...]
    access_distance: int
    estimated_rehandles: int = 0

    @property
    def block_code(self) -> str:
        return self.block.code

    def active_on(self, day: date) -> bool:
        return self.block.active_on(day)

    def overlaps(self, other: "Placement") -> bool:
        return self.block.overlaps(other.block)
