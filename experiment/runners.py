"""Subprocess adapters for optimization methods."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Sequence

from .contracts import MethodRun, RunConfig


SOLVER_SCRIPTS = {
    "or": Path("milp-solver") / "solver.py",
    "sa": Path("sa-solver") / "solver.py",
    "rl": Path("rl-solver") / "solver.py",
}


def expected_solver_path(method: str, project_root: Path) -> Path:
    try:
        relative_path = SOLVER_SCRIPTS[method]
    except KeyError as exc:
        raise ValueError(f"Unknown optimization method: {method}") from exc
    return project_root / relative_path


def build_command(method: str, config: RunConfig) -> List[str]:
    """Build the standardized CLI command for one optimization method."""

    script = expected_solver_path(method, config.project_root)
    method_dir = config.run_dir / method
    common = [
        sys.executable,
        str(script),
        "--schedule",
        str(config.schedule_path),
        "--nodes",
        str(config.nodes_path),
        "--distances",
        str(config.distances_path),
        "--output-dir",
        str(method_dir),
        "--limit",
        str(config.limit),
        "--time-limit-seconds",
        str(config.time_limit_seconds),
        "--threads",
        str(config.threads),
    ]
    if method == "or":
        common.extend(
            [
                "--candidate-yards",
                str(config.candidate_yards),
                "--overflow-yards",
                str(config.overflow_yards),
                "--backend",
                config.backend,
            ]
        )
    return common


def run_method(method: str, config: RunConfig) -> MethodRun:
    """Run one solver and validate its standard output files."""

    script = expected_solver_path(method, config.project_root)
    output_dir = config.run_dir / method
    if not script.exists():
        return MethodRun(
            method=method,
            status="NOT_IMPLEMENTED",
            output_dir=output_dir,
            message=f"Expected solver script does not exist: {script}",
        )

    command = build_command(method, config)
    completed = subprocess.run(command, cwd=config.project_root, check=False)
    result = MethodRun(
        method=method,
        status="FAILED" if completed.returncode else "FINISHED",
        output_dir=output_dir,
        command=tuple(command),
        return_code=completed.returncode,
    )
    if completed.returncode != 0:
        result.message = f"Solver process exited with code {completed.returncode}"
        return result

    required_files = (
        result.assignments_path,
        result.utilization_path,
        result.summary_path,
    )
    missing = [str(path) for path in required_files if not path.exists()]
    if missing:
        result.status = "INVALID_OUTPUT"
        result.message = "Missing solver outputs: " + ", ".join(missing)
        return result

    result.solver_summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    result.status = str(result.solver_summary.get("status", "FINISHED"))
    return result


def implemented_methods(project_root: Path) -> Dict[str, bool]:
    return {
        method: expected_solver_path(method, project_root).exists()
        for method in SOLVER_SCRIPTS
    }


def normalize_methods(requested: Sequence[str]) -> List[str]:
    if "all" in requested:
        return ["or", "sa", "rl"]
    return list(dict.fromkeys(requested))
