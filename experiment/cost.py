"""One shared operating-cost calculation for every solver family."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple


DEFAULT_WEIGHTS = {
    "transport": 1.0,
    "internal_handling": 0.35,
    "first_fit_rank": 0.20,
    "utilization": 1.0,
    "peak_utilization": 6.0,
}

DEFAULT_CONGESTION_BANDS: Tuple[Tuple[float, float], ...] = (
    (0.50, 2.0),
    (0.70, 6.0),
    (0.85, 18.0),
)


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def calculate_standard_cost_from_rows(
    assignments: Sequence[Mapping[str, str]],
    utilization_rows: Sequence[Mapping[str, str]],
    weights: Mapping[str, float] = DEFAULT_WEIGHTS,
    congestion_bands: Iterable[Tuple[float, float]] = DEFAULT_CONGESTION_BANDS,
) -> Dict[str, object]:
    """Recalculate comparable cost without trusting a solver's objective log."""

    required_assignment_fields = {
        "transport_score",
        "handling_risk_score",
        "first_fit_rank",
    }
    if assignments:
        missing = required_assignment_fields - set(assignments[0])
        if missing:
            raise ValueError(
                "Assignment output lacks standard cost columns: "
                + ", ".join(sorted(missing))
            )

    transport = weights["transport"] * sum(
        float(row["transport_score"]) for row in assignments
    )
    internal_handling = weights["internal_handling"] * sum(
        float(row["handling_risk_score"]) for row in assignments
    )
    first_fit_rank = weights["first_fit_rank"] * sum(
        float(row["first_fit_rank"]) for row in assignments
    )

    daily_utilization = 0.0
    peak_by_yard: Dict[str, float] = defaultdict(float)
    for row in utilization_rows:
        used_area = float(row["used_area_m2"])
        capacity = float(row["usable_area_m2"])
        utilization = used_area / capacity if capacity else 0.0
        peak_by_yard[row["yard_code"]] = max(
            peak_by_yard[row["yard_code"]], utilization
        )
        for threshold, slope in congestion_bands:
            excess_area = max(0.0, used_area - threshold * capacity)
            daily_utilization += (
                weights["utilization"] * slope * excess_area / 1_000.0
            )

    peak_utilization = weights["peak_utilization"] * sum(peak_by_yard.values())
    breakdown = {
        "transport": transport,
        "internal_handling": internal_handling,
        "first_fit_rank": first_fit_rank,
        "daily_utilization": daily_utilization,
        "peak_utilization": peak_utilization,
    }
    return {
        "total_cost": sum(breakdown.values()),
        "breakdown": breakdown,
        "weights": dict(weights),
        "congestion_bands": [list(band) for band in congestion_bands],
    }


def calculate_standard_cost(
    assignments_path: Path,
    utilization_path: Path,
    output_path: Path,
) -> Dict[str, object]:
    result = calculate_standard_cost_from_rows(
        read_csv(assignments_path), read_csv(utilization_path)
    )
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result
