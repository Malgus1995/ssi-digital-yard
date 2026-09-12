"""Shared input and output contracts for optimization experiments."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class RunConfig:
    project_root: Path
    schedule_path: Path
    nodes_path: Path
    distances_path: Path
    run_dir: Path
    limit: int
    time_limit_seconds: float
    threads: int
    candidate_yards: int
    overflow_yards: int
    backend: str


@dataclass
class MethodRun:
    method: str
    status: str
    output_dir: Path
    command: Tuple[str, ...] = ()
    return_code: Optional[int] = None
    message: str = ""
    solver_summary: Dict[str, object] = field(default_factory=dict)
    standard_cost: Dict[str, object] = field(default_factory=dict)

    @property
    def assignments_path(self) -> Path:
        return self.output_dir / "optimized_assignments.csv"

    @property
    def utilization_path(self) -> Path:
        return self.output_dir / "daily_yard_utilization.csv"

    @property
    def summary_path(self) -> Path:
        return self.output_dir / "solution_summary.json"
