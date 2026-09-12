"""Single entry point for OR, simulated-annealing, and RL experiments."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

from experiment.comparison import write_comparison
from experiment.contracts import MethodRun, RunConfig
from experiment.cost import calculate_standard_cost
from experiment.runners import implemented_methods, normalize_methods, run_method
from experiment.visualization import (
    MissingVisualizationDependency,
    render_visualizations,
)


PROJECT_ROOT = Path(__file__).resolve().parent


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run and compare stockyard optimization methods."
    )
    parser.add_argument(
        "--methods",
        nargs="+",
        choices=("or", "sa", "rl", "all"),
        default=("or",),
        help="One or more methods; 'all' expands to OR, SA, and RL.",
    )
    parser.add_argument(
        "--schedule", type=Path, default=PROJECT_ROOT / "data/block_schedule.csv"
    )
    parser.add_argument(
        "--nodes", type=Path, default=PROJECT_ROOT / "data/적치장 노드 정보.csv"
    )
    parser.add_argument(
        "--distances",
        type=Path,
        default=PROJECT_ROOT / "data/yard_process_distances.csv",
    )
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "runs")
    parser.add_argument(
        "--run-name",
        default=None,
        help="Output folder name; default is a timestamp.",
    )
    parser.add_argument("--limit", type=int, default=2_000)
    parser.add_argument("--time-limit-seconds", type=float, default=60.0)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--candidate-yards", type=int, default=8)
    parser.add_argument("--overflow-yards", type=int, default=2)
    parser.add_argument("--backend", choices=("SCIP", "CBC"), default="SCIP")
    parser.add_argument(
        "--visualize",
        choices=("none", "gif", "mp4", "both"),
        default="none",
    )
    parser.add_argument("--fps", type=float, default=4.0)
    parser.add_argument(
        "--frame-step-days",
        type=int,
        default=7,
        help="Render every Nth day to keep GIF and MP4 sizes manageable.",
    )
    args = parser.parse_args(argv)

    if args.limit < 0:
        parser.error("--limit must be zero or positive")
    if args.time_limit_seconds <= 0 or args.threads <= 0:
        parser.error("time limit and threads must be positive")
    if args.candidate_yards < 0 or args.overflow_yards < 0:
        parser.error("candidate counts must be zero or positive")
    if args.fps <= 0 or args.frame_step_days <= 0:
        parser.error("fps and frame-step-days must be positive")
    return args


def create_run_config(args: argparse.Namespace) -> RunConfig:
    run_name = args.run_name or datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = args.output_root.resolve() / run_name
    if run_dir.exists():
        raise FileExistsError(
            f"Run directory already exists: {run_dir}. Choose another --run-name."
        )
    for input_path in (args.schedule, args.nodes, args.distances):
        if not input_path.exists():
            raise FileNotFoundError(input_path)
    run_dir.mkdir(parents=True)
    return RunConfig(
        project_root=PROJECT_ROOT,
        schedule_path=args.schedule.resolve(),
        nodes_path=args.nodes.resolve(),
        distances_path=args.distances.resolve(),
        run_dir=run_dir,
        limit=args.limit,
        time_limit_seconds=args.time_limit_seconds,
        threads=args.threads,
        candidate_yards=args.candidate_yards,
        overflow_yards=args.overflow_yards,
        backend=args.backend,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    methods = normalize_methods(args.methods)
    config = create_run_config(args)
    availability = implemented_methods(PROJECT_ROOT)

    metadata = {
        "methods": methods,
        "implemented_methods": availability,
        "inputs": {
            "schedule": str(config.schedule_path),
            "nodes": str(config.nodes_path),
            "distances": str(config.distances_path),
        },
        "parameters": {
            "limit": config.limit,
            "time_limit_seconds": config.time_limit_seconds,
            "threads": config.threads,
            "candidate_yards": config.candidate_yards,
            "overflow_yards": config.overflow_yards,
            "backend": config.backend,
        },
    }
    (config.run_dir / "run_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    runs: List[MethodRun] = []
    for method in methods:
        print(f"\n[{method.upper()}] starting", flush=True)
        run = run_method(method, config)
        if run.assignments_path.exists() and run.utilization_path.exists():
            run.standard_cost = calculate_standard_cost(
                run.assignments_path,
                run.utilization_path,
                run.output_dir / "standard_cost.json",
            )
        print(f"[{method.upper()}] {run.status}: {run.message}")
        runs.append(run)

    comparison_rows = write_comparison(config.run_dir, runs)
    visual_outputs = []
    if args.visualize != "none":
        visual_outputs = render_visualizations(
            config.run_dir,
            runs,
            comparison_rows,
            args.visualize,
            args.fps,
            args.frame_step_days,
        )

    print(f"\nRun directory: {config.run_dir}")
    print(json.dumps(comparison_rows, ensure_ascii=False, indent=2))
    for path in visual_outputs:
        print(f"Visualization: {path}")

    successful = [run for run in runs if run.standard_cost]
    if not successful:
        return 2
    if len(methods) == 1 and runs[0].status in {
        "FAILED",
        "INVALID_OUTPUT",
        "NOT_IMPLEMENTED",
    }:
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except MissingVisualizationDependency as exc:
        print(f"visualization error: {exc}", file=sys.stderr)
        raise SystemExit(3)
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
