"""Run the stockyard assignment MIP and write an inspectable solution.

Example (small study run):

    python milp-solver/solver.py --limit 500 --time-limit-seconds 30

Use ``--limit 0`` for all 30,000 schedule rows.  The full model can be large,
so candidate-yard pruning and a time limit are enabled by default.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from constraints import (
    AssignmentOption,
    Block,
    CostWeights,
    ModelArtifacts,
    ModelConfig,
    StockyardModelBuilder,
    Yard,
    occupied_dates,
)
from ortools.linear_solver import pywraplp


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEDULE = PROJECT_ROOT / "data" / "block_schedule.csv"
DEFAULT_NODES = PROJECT_ROOT / "data" / "적치장 노드 정보.csv"
DEFAULT_DISTANCES = PROJECT_ROOT / "data" / "yard_process_distances.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "solution"


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_positive_float(value: str, label: str) -> float:
    cleaned = str(value).replace(",", "").strip()
    number = float(cleaned)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be positive, got {value!r}")
    return number


def load_blocks(path: Path, limit: int) -> List[Block]:
    rows = read_csv(path)
    if limit > 0:
        rows = rows[:limit]

    blocks: List[Block] = []
    seen_codes = set()
    for row_number, row in enumerate(rows, start=2):
        code = row["block_code"].strip()
        if not code or code in seen_codes:
            raise ValueError(f"Duplicate or blank block_code at row {row_number}: {code!r}")
        seen_codes.add(code)

        inbound_date = date.fromisoformat(row["inbound_date"])
        outbound_date = date.fromisoformat(row["outbound_date"])
        if outbound_date < inbound_date:
            raise ValueError(f"{code}: outbound_date precedes inbound_date")

        blocks.append(
            Block(
                code=code,
                inbound_factory=row["inbound_factory"].strip(),
                outbound_factory=row["outbound_factory"].strip(),
                inbound_date=inbound_date,
                outbound_date=outbound_date,
                length_m=parse_positive_float(row["length_m"], f"{code}.length_m"),
                width_m=parse_positive_float(row["width_m"], f"{code}.width_m"),
                height_m=parse_positive_float(row["height_m"], f"{code}.height_m"),
            )
        )

    if not blocks:
        raise ValueError("No schedule rows were loaded")
    return blocks


def load_yards(path: Path) -> Tuple[List[Yard], List[str]]:
    yards: List[Yard] = []
    skipped: List[str] = []
    for row in read_csv(path):
        if row.get("object", "").strip() != "적치장":
            continue
        code = row["code"].strip()
        try:
            raw_area = parse_positive_float(row["area(m^2)"], f"{code}.area")
        except (TypeError, ValueError):
            # A hard capacity constraint cannot be built for values such as
            # "첨부참조".  The source row remains unchanged and is reported.
            skipped.append(code)
            continue
        yards.append(
            Yard(
                code=code,
                zone=row["position"].strip(),
                raw_area_m2=raw_area,
                usable_area_m2=raw_area,
            )
        )
    if not yards:
        raise ValueError("No yards with numeric capacity were found")
    return yards, skipped


def load_distances(path: Path) -> Dict[Tuple[str, str], float]:
    """Return distance[(yard_code, process_code)] in metres."""

    distances: Dict[Tuple[str, str], float] = {}
    for row_number, row in enumerate(read_csv(path), start=2):
        key = (row["yard_code"].strip(), row["process_code"].strip())
        if key in distances:
            raise ValueError(f"Duplicate yard/process distance at row {row_number}: {key}")
        distances[key] = parse_positive_float(
            row["l2_distance_m"], f"distance row {row_number}"
        )
    return distances


def build_assignment_options(
    blocks: Sequence[Block],
    yards: Sequence[Yard],
    distances: Mapping[Tuple[str, str], float],
    config: ModelConfig,
    candidate_yard_count: int,
    overflow_yard_count: int,
) -> Dict[str, List[AssignmentOption]]:
    """Create distance-ordered yard candidates for all scheduled blocks.

    The nearest candidates implement the first-fit order.  A few largest yards
    are always retained as overflow choices so the MIP can avoid concentrating
    every block in the nearest yard. Same-day blocks also receive yard candidates.
    """

    median_footprint = (
        statistics.median(block.footprint_m2 for block in blocks)
        if blocks
        else 1.0
    )
    median_volume = (
        statistics.median(block.volume_m3 for block in blocks)
        if blocks
        else 1.0
    )
    overflow_codes = {
        yard.code
        for yard in sorted(yards, key=lambda item: item.usable_area_m2, reverse=True)[
            : max(0, overflow_yard_count)
        ]
    }
    options_by_block: Dict[str, List[AssignmentOption]] = {}

    for block in blocks:
        occupied_area = block.footprint_m2 * config.spacing_factor
        feasible_routes: List[Tuple[Yard, float]] = []
        for yard in yards:
            if occupied_area > yard.usable_area_m2 * config.max_utilization:
                continue
            inbound_distance = distances.get((yard.code, block.inbound_factory))
            outbound_distance = distances.get((yard.code, block.outbound_factory))
            if inbound_distance is None or outbound_distance is None:
                continue
            feasible_routes.append((yard, inbound_distance + outbound_distance))

        feasible_routes.sort(key=lambda item: (item[1], item[0].code))
        if not feasible_routes:
            raise ValueError(
                f"{block.code}: no yard has both distance data and enough block-level capacity"
            )

        if candidate_yard_count <= 0:
            selected_codes = {yard.code for yard, _distance in feasible_routes}
        else:
            selected_codes = {
                yard.code for yard, _distance in feasible_routes[:candidate_yard_count]
            }
            selected_codes.update(
                yard.code for yard, _distance in feasible_routes if yard.code in overflow_codes
            )

        footprint_ratio = block.footprint_m2 / median_footprint
        volume_ratio = block.volume_m3 / median_volume
        # Floor area drives most yard work, while volume makes height affect
        # crane and transport difficulty as well.  Both terms are monotone:
        # increasing any dimension increases the resulting size factor.
        size_ratio = 0.70 * footprint_ratio + 0.30 * volume_ratio
        options: List[AssignmentOption] = []
        for rank, (yard, route_distance_m) in enumerate(feasible_routes):
            if yard.code not in selected_codes:
                continue
            # Larger blocks cost somewhat more to transport.  The coefficient
            # is deliberately mild so route distance remains the main driver.
            transport_score = (route_distance_m / 1_000.0) * (
                0.75 + 0.25 * size_ratio
            )
            options.append(
                AssignmentOption(
                    block_code=block.code,
                    yard_code=yard.code,
                    route_distance_m=route_distance_m,
                    first_fit_rank=rank,
                    transport_score=transport_score,
                )
            )
        options_by_block[block.code] = options

    return options_by_block


def create_mip_solver(requested_backend: str) -> Tuple[pywraplp.Solver, str]:
    """Create SCIP when available and fall back to CBC."""

    if requested_backend.upper() == "CBC":
        candidates = ("CBC_MIXED_INTEGER_PROGRAMMING", "CBC")
    else:
        candidates = ("SCIP", "CBC_MIXED_INTEGER_PROGRAMMING", "CBC")

    for backend in candidates:
        solver = pywraplp.Solver.CreateSolver(backend)
        if solver is not None:
            return solver, backend
    raise RuntimeError("Neither the SCIP nor CBC OR-Tools MIP backend is available")


def apply_first_fit_hint(
    solver: pywraplp.Solver,
    blocks: Sequence[Block],
    yards: Sequence[Yard],
    options_by_block: Mapping[str, Sequence[AssignmentOption]],
    artifacts: ModelArtifacts,
    config: ModelConfig,
) -> Tuple[int, int]:
    """Create a distance-ordered first-fit warm start.

    For each scheduled block in arrival order, choose the first candidate yard
    whose daily hard capacity remains feasible.  This is only a MIP hint: the
    solver may move a block when total transport, first-fit, or congestion cost
    drops.
    """

    yard_by_code = {yard.code: yard for yard in yards}
    loads: Dict[Tuple[str, date], float] = defaultdict(float)
    chosen_yard: Dict[str, str] = {}

    for block in sorted(blocks, key=lambda item: (item.inbound_date, item.code)):
        area = block.footprint_m2 * config.spacing_factor
        days = tuple(occupied_dates(block))
        ordered_options = sorted(
            options_by_block[block.code],
            key=lambda option: (option.first_fit_rank, option.yard_code),
        )
        for option in ordered_options:
            capacity = (
                yard_by_code[option.yard_code].usable_area_m2
                * config.max_utilization
            )
            if all(loads[(option.yard_code, day)] + area <= capacity for day in days):
                chosen_yard[block.code] = option.yard_code
                for day in days:
                    loads[(option.yard_code, day)] += area
                break

    hint_variables = []
    hint_values = []
    for key, variable in artifacts.assignment_vars.items():
        block_code, yard_code = key
        if block_code not in chosen_yard:
            continue
        hint_variables.append(variable)
        hint_values.append(1.0 if chosen_yard[block_code] == yard_code else 0.0)

    if hint_variables:
        solver.SetHint(hint_variables, hint_values)
    return len(chosen_yard), len(blocks) - len(chosen_yard)


def iter_dates(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def extract_assignments(
    blocks: Sequence[Block], artifacts: ModelArtifacts, config: ModelConfig
) -> Tuple[List[Dict[str, object]], Dict[Tuple[str, date], Dict[str, float]]]:
    """Read yard choices for all blocks, including same-day yard visits."""

    daily: Dict[Tuple[str, date], Dict[str, float]] = defaultdict(
        lambda: {"used_area_m2": 0.0, "active_blocks": 0.0}
    )
    rows: List[Dict[str, object]] = []
    variables_by_block: Dict[
        str, List[Tuple[Tuple[str, str], pywraplp.Variable]]
    ] = defaultdict(list)
    for key, variable in artifacts.assignment_vars.items():
        variables_by_block[key[0]].append((key, variable))

    for block in blocks:
        selected = [
            (key, variable)
            for key, variable in variables_by_block[block.code]
            if variable.solution_value() > 0.5
        ]
        if len(selected) != 1:
            raise RuntimeError(
                f"{block.code}: expected one selected yard, found {len(selected)}"
            )
        key, _variable = selected[0]
        option = artifacts.option_by_key[key]
        occupied_area = block.footprint_m2 * config.spacing_factor
        for day in occupied_dates(block):
            values = daily[(option.yard_code, day)]
            values["used_area_m2"] += occupied_area
            values["active_blocks"] += 1

        rows.append(
            {
                "block_code": block.code,
                "storage_mode": "STOCKYARD",
                "assigned_yard": option.yard_code,
                "inbound_factory": block.inbound_factory,
                "outbound_factory": block.outbound_factory,
                "inbound_date": block.inbound_date.isoformat(),
                "outbound_date": block.outbound_date.isoformat(),
                "waiting_days": block.dwell_days,
                "length_m": block.length_m,
                "width_m": block.width_m,
                "height_m": block.height_m,
                "occupied_area_m2": round(occupied_area, 9),
                "route_distance_m": round(option.route_distance_m, 1),
                "first_fit_rank": option.first_fit_rank,
                "transport_score": round(option.transport_score, 12),
            }
        )
    return rows, daily


def calculate_objective_breakdown(
    artifacts: ModelArtifacts,
    weights: CostWeights,
) -> Dict[str, float]:
    selected_options = [
        artifacts.option_by_key[key]
        for key, variable in artifacts.assignment_vars.items()
        if variable.solution_value() > 0.5
    ]
    transport = sum(option.transport_score for option in selected_options)
    first_fit = sum(option.first_fit_rank for option in selected_options)
    utilization = sum(
        weights.utilization * slope * variable.solution_value() / 1_000.0
        for variable, slope in artifacts.excess_area_vars.values()
    )
    peak = sum(
        weights.peak_utilization * variable.solution_value()
        for variable in artifacts.peak_utilization_vars.values()
    )
    return {
        "transport": weights.transport * transport,
        "first_fit_rank": weights.first_fit_rank * first_fit,
        "daily_utilization": utilization,
        "peak_utilization": peak,
    }


def write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    if not rows:
        raise ValueError(f"Cannot write empty CSV: {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_solution(
    output_dir: Path,
    blocks: Sequence[Block],
    yards: Sequence[Yard],
    artifacts: ModelArtifacts,
    solver: pywraplp.Solver,
    backend: str,
    status_name: str,
    config: ModelConfig,
    weights: CostWeights,
    skipped_yards: Sequence[str],
    hint_assigned: int,
    hint_unassigned: int,
) -> Dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    assignment_rows, daily_values = extract_assignments(blocks, artifacts, config)

    start = min(block.inbound_date for block in blocks)
    end = max(block.outbound_date for block in blocks)
    utilization_rows: List[Dict[str, object]] = []
    for day in iter_dates(start, end):
        for yard in yards:
            values = daily_values.get(
                (yard.code, day), {"used_area_m2": 0.0, "active_blocks": 0.0}
            )
            used_area = values["used_area_m2"]
            utilization_rows.append(
                {
                    "date": day.isoformat(),
                    "yard_code": yard.code,
                    "yard_zone": yard.zone,
                    "active_blocks": int(values["active_blocks"]),
                    "used_area_m2": round(used_area, 9),
                    "usable_area_m2": round(yard.usable_area_m2, 9),
                    "utilization": round(used_area / yard.usable_area_m2, 12),
                }
            )

    assignments_path = output_dir / "optimized_assignments.csv"
    utilization_path = output_dir / "daily_yard_utilization.csv"
    summary_path = output_dir / "solution_summary.json"
    write_csv(assignments_path, assignment_rows)
    write_csv(utilization_path, utilization_rows)

    objective_value = solver.Objective().Value()
    try:
        best_bound: Optional[float] = solver.Objective().BestBound()
        relative_gap: Optional[float] = abs(objective_value - best_bound) / max(
            1.0, abs(objective_value)
        )
    except AttributeError:
        best_bound = None
        relative_gap = None

    breakdown = calculate_objective_breakdown(artifacts, weights)
    total_breakdown = sum(breakdown.values())
    peak_row = max(utilization_rows, key=lambda row: float(row["utilization"]))
    nonzero_utilization = [
        float(row["utilization"])
        for row in utilization_rows
        if int(row["active_blocks"]) > 0
    ]

    summary: Dict[str, object] = {
        "status": status_name,
        "backend": backend,
        "block_count": len(blocks),
        "stockyard_block_count": len(blocks),
        "yard_count": len(yards),
        "binary_assignment_variable_count": len(artifacts.assignment_vars),
        "constraint_count": solver.NumConstraints(),
        "objective_value": objective_value,
        "best_bound": best_bound,
        "relative_gap": relative_gap,
        "wall_time_seconds": solver.WallTime() / 1_000.0,
        "objective_breakdown": breakdown,
        "objective_breakdown_total": total_breakdown,
        "total_route_distance_km": round(
            sum(float(row["route_distance_m"]) for row in assignment_rows) / 1_000.0,
            3,
        ),
        "mean_nonempty_yard_utilization": (
            statistics.mean(nonzero_utilization) if nonzero_utilization else 0.0
        ),
        "peak_yard_utilization": peak_row,
        "first_fit_hint": {
            "assigned_blocks": hint_assigned,
            "unassigned_blocks": hint_unassigned,
        },
        "skipped_yards_without_numeric_capacity": list(skipped_yards),
        "model_config": asdict(config),
        "cost_weights": asdict(weights),
        "outputs": {
            "assignments": str(assignments_path),
            "daily_utilization": str(utilization_path),
        },
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assign scheduled blocks to stockyards with an OR-Tools MIP."
    )
    parser.add_argument("--schedule", type=Path, default=DEFAULT_SCHEDULE)
    parser.add_argument("--nodes", type=Path, default=DEFAULT_NODES)
    parser.add_argument("--distances", type=Path, default=DEFAULT_DISTANCES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--limit",
        type=int,
        default=2_000,
        help="Number of chronologically sorted blocks to solve; 0 uses all rows.",
    )
    parser.add_argument(
        "--candidate-yards",
        type=int,
        default=8,
        help="Nearest feasible yards per block; 0 keeps every feasible yard.",
    )
    parser.add_argument(
        "--overflow-yards",
        type=int,
        default=2,
        help="Largest yards retained in addition to nearest candidates.",
    )
    parser.add_argument("--backend", choices=("SCIP", "CBC"), default="SCIP")
    parser.add_argument("--time-limit-seconds", type=float, default=60.0)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--spacing-factor", type=float, default=1.15)
    parser.add_argument("--max-utilization", type=float, default=0.95)
    parser.add_argument("--transport-weight", type=float, default=1.0)
    parser.add_argument("--first-fit-weight", type=float, default=0.20)
    parser.add_argument("--utilization-weight", type=float, default=1.0)
    parser.add_argument("--peak-utilization-weight", type=float, default=6.0)
    parser.add_argument(
        "--no-first-fit-hint",
        action="store_true",
        help="Disable the distance-ordered first-fit warm start.",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    if args.limit < 0:
        parser.error("--limit must be zero or positive")
    if args.candidate_yards < 0 or args.overflow_yards < 0:
        parser.error("candidate counts must be zero or positive")
    if args.time_limit_seconds <= 0 or args.threads <= 0:
        parser.error("time limit and thread count must be positive")
    if not 0 < args.max_utilization <= 1:
        parser.error("--max-utilization must be in (0, 1]")
    if args.spacing_factor < 1:
        parser.error("--spacing-factor must be at least 1")
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    config = ModelConfig(
        spacing_factor=args.spacing_factor,
        max_utilization=args.max_utilization,
    )
    weights = CostWeights(
        transport=args.transport_weight,
        first_fit_rank=args.first_fit_weight,
        utilization=args.utilization_weight,
        peak_utilization=args.peak_utilization_weight,
    )

    blocks = load_blocks(args.schedule, args.limit)
    yards, skipped_yards = load_yards(args.nodes)
    distances = load_distances(args.distances)
    options_by_block = build_assignment_options(
        blocks,
        yards,
        distances,
        config,
        args.candidate_yards,
        args.overflow_yards,
    )

    solver, backend = create_mip_solver(args.backend)
    solver.SetTimeLimit(int(args.time_limit_seconds * 1_000))
    solver.SetNumThreads(args.threads)
    if args.verbose:
        solver.EnableOutput()

    model_builder = StockyardModelBuilder(
        solver=solver,
        config=config,
        weights=weights,
    )
    artifacts = model_builder.build(blocks, yards, options_by_block)
    if args.no_first_fit_hint:
        hint_assigned = 0
        hint_unassigned = len(blocks)
    else:
        hint_assigned, hint_unassigned = apply_first_fit_hint(
            solver, blocks, yards, options_by_block, artifacts, config
        )

    print(
        json.dumps(
            {
                "backend": backend,
                "blocks": len(blocks),
                "stockyard_blocks": len(blocks),
                "yards": len(yards),
                "assignment_variables": len(artifacts.assignment_vars),
                "constraints": solver.NumConstraints(),
                "first_fit_hint_assigned": hint_assigned,
                "skipped_yards": skipped_yards,
            },
            ensure_ascii=False,
        )
    )
    status = solver.Solve()
    status_names = {
        pywraplp.Solver.OPTIMAL: "OPTIMAL",
        pywraplp.Solver.FEASIBLE: "FEASIBLE",
        pywraplp.Solver.INFEASIBLE: "INFEASIBLE",
        pywraplp.Solver.UNBOUNDED: "UNBOUNDED",
        pywraplp.Solver.ABNORMAL: "ABNORMAL",
        pywraplp.Solver.NOT_SOLVED: "NOT_SOLVED",
    }
    status_name = status_names.get(status, f"UNKNOWN_{status}")
    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        print(f"Solver finished with status {status_name}; no solution files written.")
        return 2

    summary = write_solution(
        args.output_dir,
        blocks,
        yards,
        artifacts,
        solver,
        backend,
        status_name,
        config,
        weights,
        skipped_yards,
        hint_assigned,
        hint_unassigned,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, KeyError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
