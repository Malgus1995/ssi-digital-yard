from dataclasses import dataclass
from datetime import date
from typing import Literal, Mapping, Protocol


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
    def requires_yard(self) -> bool:
        return self.inbound_date < self.outbound_date


@dataclass(frozen=True)
class Node:
    code: str
    zone: str
    kind: str
    latitude: float
    longitude: float
    area_m2: float | None


@dataclass(frozen=True)
class Road:
    code: str
    source: str
    target: str
    distance_m: float
    duration_min: float
    bidirectional: bool


@dataclass(frozen=True)
class Baseline:
    yard: str
    factory: str
    distance_m: float
    duration_min: float


@dataclass(frozen=True)
class Scenario:
    blocks: tuple[Block, ...]
    nodes: Mapping[str, Node]
    roads: tuple[Road, ...]
    baselines: Mapping[tuple[str, str], Baseline]


@dataclass(frozen=True)
class YardAssignment:
    by_block: Mapping[str, str]


class Planner(Protocol):
    def plan(self, scenario: Scenario) -> YardAssignment: ...


SearchOrder = Literal["bfs", "dfs"]
