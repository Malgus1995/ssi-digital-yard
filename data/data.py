"""Solver-independent stockyard data types (Python standard library only).

No OR-Tools variables, RL tensors, or mutable search caches belong here.
All algorithms should consume the same ProblemData and return AssignmentSolution.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable


@dataclass(frozen=True)
class Block:
    code: str
    inbound_factory: str
    outbound_factory: str
    inbound_date: date
    outbound_date: date
    length_m: float
    width_m: float
    height_m: float

    @property
    def footprint_m2(self) -> float:
        return self.length_m * self.width_m

    @property
    def volume_m3(self) -> float:
        return self.footprint_m2 * self.height_m

    @property
    def dwell_days(self) -> int:
        return (self.outbound_date - self.inbound_date).days


@dataclass(frozen=True)
class Yard:
    code: str
    zone: str
    raw_area_m2: float
    usable_area_m2: float


@dataclass(frozen=True)
class Node:
    code: str
    position: str
    object: str
    latitude: float
    longitude: float
    number: int
    width: str
    depth: str
    area_m2: float | None
    area_raw: str

    @property
    def zone(self) -> str:
        return self.position


@dataclass(frozen=True)
class Road:
    road_id: str
    from_node: str
    to_node: str
    from_lat: float
    from_lon: float
    to_lat: float
    to_lon: float
    l2_distance_m: float
    road_distance_m: float
    road_class: str
    speed_kmh: float
    travel_time_min: float
    is_bidirectional: bool


@dataclass(frozen=True)
class AssignmentOption:
    """One eligible yard choice; stores cost inputs, never solver variables."""
    block_code: str
    yard_code: str
    route_distance_m: float
    first_fit_rank: int
    transport_score: float


@dataclass(frozen=True)
class CostWeights:
    """Common objective weights. Values are scores, not currency."""
    transport: float = 1.0
    first_fit_rank: float = 0.20
    utilization: float = 1.0
    peak_utilization: float = 6.0
