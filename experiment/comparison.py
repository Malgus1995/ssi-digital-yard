"""Build machine-readable comparisons across optimization methods."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, List, Sequence

from .contracts import MethodRun


def _peak_utilization(summary: Dict[str, object]) -> object:
    peak = summary.get("peak_yard_utilization")
    if isinstance(peak, dict):
        return peak.get("utilization", "")
    return peak if peak is not None else ""


def build_comparison_rows(runs: Sequence[MethodRun]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for run in runs:
        summary = run.solver_summary
        standard_cost = run.standard_cost
        rows.append(
            {
                "method": run.method,
                "status": run.status,
                "total_cost": standard_cost.get("total_cost", ""),
                "transport_cost": standard_cost.get("breakdown", {}).get(
                    "transport", ""
                ),
                "internal_handling_cost": standard_cost.get("breakdown", {}).get(
                    "internal_handling", ""
                ),
                "utilization_cost": standard_cost.get("breakdown", {}).get(
                    "daily_utilization", ""
                ),
                "route_distance_km": summary.get("total_route_distance_km", ""),
                "peak_yard_utilization": _peak_utilization(summary),
                "wall_time_seconds": summary.get("wall_time_seconds", ""),
                "relative_gap": summary.get("relative_gap", ""),
                "message": run.message,
            }
        )
    return rows


def write_comparison(run_dir: Path, runs: Sequence[MethodRun]) -> List[Dict[str, object]]:
    rows = build_comparison_rows(runs)
    csv_path = run_dir / "comparison.csv"
    json_path = run_dir / "comparison.json"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return rows
