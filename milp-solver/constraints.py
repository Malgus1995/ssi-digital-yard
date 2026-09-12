"""OR-Tools MIP constraints for the stockyard scheduling example.

The source data has yard-level capacity, but it does not contain exact lane,
stack, or entrance geometry.  Therefore this model does not pretend to count
physical rehandles exactly.  It uses two transparent proxies instead:

1. a per-assignment handling-risk score based on block size, dwell time, and
   the number of sections in a yard; and
2. a steep, piecewise-linear daily congestion cost above 50%, 70%, and 85%
   utilization.

This keeps the formulation linear and easy to study.  Exact stack rehandling
can be added later when slot coordinates and access order become available.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

try:
    from ortools.linear_solver import pywraplp
except ModuleNotFoundError as exc:  # pragma: no cover - depends on local setup
    raise ModuleNotFoundError(
        "OR-Tools is required. Install it with: python -m pip install ortools"
    ) from exc


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
    def dwell_days(self) -> int:
        """Calendar difference; same-day arrival/departure returns zero."""

        return (self.outbound_date - self.inbound_date).days


@dataclass(frozen=True)
class Yard:
    code: str
    zone: str
    raw_area_m2: float
    sections: int
    usable_area_m2: float


@dataclass(frozen=True)
class AssignmentOption:
    """One feasible block-to-yard choice and its linear cost drivers."""

    block_code: str
    yard_code: str
    route_distance_m: float
    first_fit_rank: int
    transport_score: float
    handling_risk_score: float


@dataclass(frozen=True)
class CostWeights:
    """Relative operating-cost weights; these are scores, not currency."""

    transport: float = 1.0
    internal_handling: float = 0.35
    first_fit_rank: float = 0.20
    utilization: float = 1.0
    peak_utilization: float = 6.0


@dataclass(frozen=True)
class ModelConfig:
    """Capacity and congestion assumptions used by the MIP."""

    spacing_factor: float = 1.15
    usable_area_ratio: float = 0.75
    max_utilization: float = 0.95
    # (utilization threshold, marginal score per 1,000 excess m2-day)
    congestion_bands: Tuple[Tuple[float, float], ...] = (
        (0.50, 2.0),
        (0.70, 6.0),
        (0.85, 18.0),
    )


@dataclass
class ModelArtifacts:
    """Variables and metadata required to inspect the solved model."""

    assignment_vars: Dict[Tuple[str, str], pywraplp.Variable]
    option_by_key: Dict[Tuple[str, str], AssignmentOption]
    excess_area_vars: Dict[
        Tuple[str, date, float], Tuple[pywraplp.Variable, float]
    ]
    peak_utilization_vars: Dict[str, pywraplp.Variable]
    active_terms: Dict[
        Tuple[str, date], List[Tuple[pywraplp.Variable, float, str]]
    ]


def occupied_dates(block: Block) -> Iterable[date]:
    """Yield dates on which a block consumes yard capacity.

    The interval is inclusive of the outbound date.  That conservative choice
    treats a block leaving during the day as occupying space for that day's
    capacity plan.
    """

    current = block.inbound_date
    while current <= block.outbound_date:
        yield current
        current += timedelta(days=1)


def create_assignment_variables(
    solver: pywraplp.Solver,
    blocks: Sequence[Block],
    options_by_block: Mapping[str, Sequence[AssignmentOption]],
) -> Tuple[
    Dict[Tuple[str, str], pywraplp.Variable],
    Dict[Tuple[str, str], AssignmentOption],
]:
    """Create x[b,y] = 1 when block b is assigned to yard y."""

    assignment_vars: Dict[Tuple[str, str], pywraplp.Variable] = {}
    option_by_key: Dict[Tuple[str, str], AssignmentOption] = {}

    for block_index, block in enumerate(blocks):
        options = options_by_block.get(block.code, ())
        if not options:
            raise ValueError(f"Block {block.code} has no feasible yard candidate")
        for option_index, option in enumerate(options):
            key = (block.code, option.yard_code)
            assignment_vars[key] = solver.BoolVar(
                f"x_b{block_index}_o{option_index}"
            )
            option_by_key[key] = option

    return assignment_vars, option_by_key


def add_exactly_one_yard_constraints(
    solver: pywraplp.Solver,
    blocks: Sequence[Block],
    options_by_block: Mapping[str, Sequence[AssignmentOption]],
    assignment_vars: Mapping[Tuple[str, str], pywraplp.Variable],
) -> None:
    """Every block must be placed in exactly one candidate yard."""

    for block_index, block in enumerate(blocks):
        constraint = solver.Constraint(1.0, 1.0, f"assign_once_{block_index}")
        for option in options_by_block[block.code]:
            constraint.SetCoefficient(
                assignment_vars[(block.code, option.yard_code)], 1.0
            )


def build_daily_active_terms(
    blocks: Sequence[Block],
    options_by_block: Mapping[str, Sequence[AssignmentOption]],
    assignment_vars: Mapping[Tuple[str, str], pywraplp.Variable],
    config: ModelConfig,
) -> Dict[Tuple[str, date], List[Tuple[pywraplp.Variable, float, str]]]:
    """Index assignment variables by yard and occupied day."""

    active_terms: Dict[
        Tuple[str, date], List[Tuple[pywraplp.Variable, float, str]]
    ] = {}
    for block in blocks:
        occupied_area = block.footprint_m2 * config.spacing_factor
        for option in options_by_block[block.code]:
            variable = assignment_vars[(block.code, option.yard_code)]
            for day in occupied_dates(block):
                active_terms.setdefault((option.yard_code, day), []).append(
                    (variable, occupied_area, block.code)
                )
    return active_terms


def add_daily_capacity_and_congestion_constraints(
    solver: pywraplp.Solver,
    yards: Sequence[Yard],
    active_terms: Mapping[
        Tuple[str, date], Sequence[Tuple[pywraplp.Variable, float, str]]
    ],
    config: ModelConfig,
) -> Tuple[
    Dict[Tuple[str, date, float], Tuple[pywraplp.Variable, float]],
    Dict[str, pywraplp.Variable],
]:
    """Add hard daily capacity and soft convex congestion constraints.

    For a congestion threshold t, excess_area >= load - t * capacity.
    Multiple cumulative excess variables create a convex piecewise-linear
    penalty without a nonlinear utilization-squared term.
    """

    yard_by_code = {yard.code: yard for yard in yards}
    infinity = solver.infinity()
    excess_vars: Dict[
        Tuple[str, date, float], Tuple[pywraplp.Variable, float]
    ] = {}
    peak_vars = {
        yard.code: solver.NumVar(
            0.0, config.max_utilization, f"peak_util_{yard_index}"
        )
        for yard_index, yard in enumerate(yards)
    }

    for day_index, ((yard_code, day), terms) in enumerate(
        sorted(active_terms.items(), key=lambda item: (item[0][0], item[0][1]))
    ):
        yard = yard_by_code[yard_code]
        capacity = yard.usable_area_m2

        hard_capacity = solver.Constraint(
            -infinity,
            config.max_utilization * capacity,
            f"capacity_{day_index}",
        )
        for variable, area, _block_code in terms:
            hard_capacity.SetCoefficient(variable, area)

        # peak >= daily_load / usable_capacity
        peak_constraint = solver.Constraint(-infinity, 0.0, f"peak_{day_index}")
        for variable, area, _block_code in terms:
            peak_constraint.SetCoefficient(variable, area)
        peak_constraint.SetCoefficient(peak_vars[yard_code], -capacity)

        for band_index, (threshold, slope) in enumerate(config.congestion_bands):
            max_excess = max(0.0, (config.max_utilization - threshold) * capacity)
            excess = solver.NumVar(
                0.0,
                max_excess,
                f"excess_{day_index}_{band_index}",
            )
            # load - excess <= threshold * capacity
            band_constraint = solver.Constraint(
                -infinity,
                threshold * capacity,
                f"band_{day_index}_{band_index}",
            )
            for variable, area, _block_code in terms:
                band_constraint.SetCoefficient(variable, area)
            band_constraint.SetCoefficient(excess, -1.0)
            excess_vars[(yard_code, day, threshold)] = (excess, slope)

    return excess_vars, peak_vars


def set_minimum_operating_cost_objective(
    solver: pywraplp.Solver,
    assignment_vars: Mapping[Tuple[str, str], pywraplp.Variable],
    option_by_key: Mapping[Tuple[str, str], AssignmentOption],
    excess_area_vars: Mapping[
        Tuple[str, date, float], Tuple[pywraplp.Variable, float]
    ],
    peak_utilization_vars: Mapping[str, pywraplp.Variable],
    weights: CostWeights,
) -> None:
    """Minimize transport, handling, first-fit deviation, and congestion."""

    objective = solver.Objective()
    for key, variable in assignment_vars.items():
        option = option_by_key[key]
        coefficient = (
            weights.transport * option.transport_score
            + weights.internal_handling * option.handling_risk_score
            + weights.first_fit_rank * option.first_fit_rank
        )
        objective.SetCoefficient(variable, coefficient)

    for excess, marginal_slope in excess_area_vars.values():
        objective.SetCoefficient(
            excess,
            weights.utilization * marginal_slope / 1_000.0,
        )

    for peak_variable in peak_utilization_vars.values():
        objective.SetCoefficient(peak_variable, weights.peak_utilization)

    objective.SetMinimization()


def build_stockyard_model(
    solver: pywraplp.Solver,
    blocks: Sequence[Block],
    yards: Sequence[Yard],
    options_by_block: Mapping[str, Sequence[AssignmentOption]],
    config: ModelConfig,
    weights: CostWeights,
) -> ModelArtifacts:
    """Build the complete stockyard assignment MIP."""

    assignment_vars, option_by_key = create_assignment_variables(
        solver, blocks, options_by_block
    )
    add_exactly_one_yard_constraints(
        solver, blocks, options_by_block, assignment_vars
    )
    active_terms = build_daily_active_terms(
        blocks, options_by_block, assignment_vars, config
    )
    excess_vars, peak_vars = add_daily_capacity_and_congestion_constraints(
        solver, yards, active_terms, config
    )
    set_minimum_operating_cost_objective(
        solver,
        assignment_vars,
        option_by_key,
        excess_vars,
        peak_vars,
        weights,
    )
    return ModelArtifacts(
        assignment_vars=assignment_vars,
        option_by_key=option_by_key,
        excess_area_vars=excess_vars,
        peak_utilization_vars=peak_vars,
        active_terms=active_terms,
    )
