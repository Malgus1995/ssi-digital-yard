from collections import defaultdict
from dataclasses import dataclass
from heapq import heappop, heappush

from ssi_yard.domain import Road


@dataclass(frozen=True)
class Route:
    nodes: tuple[str, ...]
    distance_m: float
    duration_min: float


class RoadNetwork:
    def __init__(self, roads: tuple[Road, ...]):
        self._neighbors = defaultdict(list)
        for road in roads:
            self._neighbors[road.source].append((road.target, road))
            if road.bidirectional:
                self._neighbors[road.target].append((road.source, road))

    def fastest_route(self, source: str, target: str) -> Route | None:
        queue = [(0.0, 0.0, (source,))]
        visited = set()
        while queue:
            duration, distance, path = heappop(queue)
            node = path[-1]
            if node in visited:
                continue
            if node == target:
                return Route(path, distance, duration)
            visited.add(node)
            for neighbor, road in self._neighbors[node]:
                if neighbor not in visited:
                    heappush(queue, (duration + road.duration_min,
                                     distance + road.distance_m, (*path, neighbor)))
        return None
