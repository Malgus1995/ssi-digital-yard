"""Blocking relationships and DFS-based rehandle estimates."""

from __future__ import annotations

from datetime import date
from typing import Dict, Iterable, Mapping, Optional, Set, Tuple

from .grid import GridYard
from .models import Placement


def _path_occupants(
    yard: GridYard,
    path: Iterable[Tuple[int, int]],
    day: date,
    ignored_code: str,
) -> Dict[str, int]:
    """Map block code to its deepest index on a canonical access path."""

    positions: Dict[str, int] = {}
    for index, cell in enumerate(path):
        for placement in yard.occupants(cell, day):
            if placement.block_code != ignored_code:
                positions[placement.block_code] = max(
                    index, positions.get(placement.block_code, -1)
                )
    return positions


def direct_blockers(
    yard: GridYard,
    target: Placement,
    day: Optional[date] = None,
) -> Set[str]:
    """Return the closest block on the target's canonical access path.

    The path is based on the empty-yard BFS tree.  Selecting the closest block
    to the target creates a blocker chain that DFS can traverse.
    """

    extraction_day = day or target.block.outbound_date
    positions = _path_occupants(
        yard, target.access_path, extraction_day, target.block_code
    )
    if not positions:
        return set()
    deepest_index = max(positions.values())
    return {code for code, index in positions.items() if index == deepest_index}


def build_blocking_graph(
    yard: GridYard, day: date
) -> Dict[str, Set[str]]:
    """Build target -> direct blocker edges for placements active on a day."""

    return {
        target.block_code: direct_blockers(yard, target, day)
        for target in yard.active_placements(day)
    }


def dfs_blockers(
    graph: Mapping[str, Iterable[str]], target_code: str
) -> Set[str]:
    """Return all direct and transitive blockers of a target block."""

    visited: Set[str] = set()
    stack = list(graph.get(target_code, ()))
    while stack:
        blocker = stack.pop()
        if blocker == target_code or blocker in visited:
            continue
        visited.add(blocker)
        stack.extend(graph.get(blocker, ()))
    return visited


def estimate_incremental_rehandles(
    yard: GridYard, candidate: Placement
) -> int:
    """Estimate new direct blocking events caused by a candidate placement.

    Two cases count as risk:

    * an existing block lies on the candidate's path when the candidate leaves;
    * the candidate lies on an existing block's path when that block leaves.

    This is an explainable proxy, not an exact vehicle-movement simulation.
    """

    events: Set[Tuple[str, str]] = set()
    existing_on_candidate_path = _path_occupants(
        yard,
        candidate.access_path,
        candidate.block.outbound_date,
        candidate.block_code,
    )
    for blocker_code in existing_on_candidate_path:
        events.add((candidate.block_code, blocker_code))

    candidate_cells = set(candidate.cells)
    for existing in yard.placements():
        departure = existing.block.outbound_date
        if not candidate.block.active_on(departure):
            continue
        if candidate_cells.intersection(existing.access_path):
            events.add((existing.block_code, candidate.block_code))
    return len(events)


def blocking_report(yard: GridYard, day: date) -> Dict[str, Dict[str, object]]:
    """Return direct and DFS-expanded blockers for each active block."""

    graph = build_blocking_graph(yard, day)
    return {
        code: {
            "direct_blockers": sorted(direct),
            "all_blockers": sorted(dfs_blockers(graph, code)),
            "rehandle_count": len(dfs_blockers(graph, code)),
        }
        for code, direct in graph.items()
    }
