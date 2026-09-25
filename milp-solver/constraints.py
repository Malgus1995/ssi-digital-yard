"""OR-Tools MIP constraints for stockyard scheduling.

Minimize transport, first-fit deviation, daily congestion, and peak utilization.
Yard counts do not describe internal geometry, so no handling-risk proxy is used.
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
    def volume_m3(self) -> float:
        return self.footprint_m2 * self.height_m

    @property
    def dwell_days(self) -> int:
        """Days spent waiting between release and factory acceptance."""

        return (self.outbound_date - self.inbound_date).days



@dataclass(frozen=True)
class Yard:
    code: str
    zone: str
    raw_area_m2: float
    usable_area_m2: float


@dataclass(frozen=True)
class AssignmentOption:
    """One feasible block-to-yard choice and its linear cost drivers."""

    block_code: str
    yard_code: str
    route_distance_m: float
    first_fit_rank: int
    transport_score: float


@dataclass(frozen=True)
class CostWeights:
    """Relative operating-cost weights; these are scores, not currency."""

    transport: float = 1.0
    first_fit_rank: float = 0.20
    utilization: float = 1.0
    peak_utilization: float = 6.0


@dataclass(frozen=True)
class ModelConfig:
    """Capacity and congestion assumptions used by the MIP."""

    spacing_factor: float = 1.15
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

    The interval is half-open: the release day consumes capacity and the day
    accepted by the next factory does not.  A same-day yard visit
    therefore consumes no stockyard capacity.
    """

    current = block.inbound_date
    while current < block.outbound_date:
        yield current
        current += timedelta(days=1)


class StockyardModelBuilder:
    """Own all variables, constraints, and the objective for one MIP model."""

    def __init__(
        self,
        solver: pywraplp.Solver,
        config: ModelConfig,
        weights: CostWeights,
    ) -> None:
        self.solver = solver
        self.config = config
        self.weights = weights

        self.assignment_vars = {}
        self.option_by_key = {}
        self.active_terms = {}
        self.excess_area_vars = {}
        self.peak_utilization_vars = {}

        self._built = False

    def create_assignment_variables(
        self,
        blocks: Sequence[Block],
        options_by_block: Mapping[str, Sequence[AssignmentOption]],
    ) -> None:
        """Create x[b,y] = 1 when block b is assigned to yard y."""

        for block_index, block in enumerate(blocks):
            options = options_by_block.get(block.code, ())
            if not options:
                raise ValueError(f"Block {block.code} has no feasible yard candidate")
            for option_index, option in enumerate(options):
                key = (block.code, option.yard_code)
                self.assignment_vars[key] = self.solver.BoolVar(
                    f"x_b{block_index}_o{option_index}"
                )
                self.option_by_key[key] = option

    def add_exactly_one_yard_constraints(
        self,
        blocks: Sequence[Block],
        options_by_block: Mapping[str, Sequence[AssignmentOption]],
    ) -> None:
        """Every scheduled block must be placed in one candidate yard."""

        for block_index, block in enumerate(blocks):
            constraint = self.solver.Constraint(
                1.0, 1.0, f"assign_once_{block_index}"
            )
            for option in options_by_block[block.code]:
                constraint.SetCoefficient(
                    self.assignment_vars[(block.code, option.yard_code)], 1.0
                )

    def build_daily_active_terms(
        self,
        blocks: Sequence[Block],
        options_by_block: Mapping[str, Sequence[AssignmentOption]],
    ) -> None:
        """Index assignment variables by yard and occupied day."""

        for block in blocks:
            occupied_area = block.footprint_m2 * self.config.spacing_factor
            for option in options_by_block[block.code]:
                variable = self.assignment_vars[(block.code, option.yard_code)]
                for day in occupied_dates(block):
                    self.active_terms.setdefault(
                        (option.yard_code, day), []
                    ).append((variable, occupied_area, block.code))

    def add_daily_capacity_and_congestion_constraints(
        self,
        yards: Sequence[Yard],
    ) -> None:
        """Add hard daily capacity and soft convex congestion constraints.

        For a congestion threshold t, excess_area >= load - t * capacity.
        Multiple cumulative excess variables create a convex piecewise-linear
        penalty without a nonlinear utilization-squared term.
        """

        yard_by_code = {yard.code: yard for yard in yards}
        infinity = self.solver.infinity()
        self.peak_utilization_vars = {
            yard.code: self.solver.NumVar(
                0.0,
                self.config.max_utilization,
                f"peak_util_{yard_index}",
            )
            for yard_index, yard in enumerate(yards)
        }

        for day_index, ((yard_code, day), terms) in enumerate(
            sorted(
                self.active_terms.items(),
                key=lambda item: (item[0][0], item[0][1]),
            )
        ):
            yard = yard_by_code[yard_code]
            capacity = yard.usable_area_m2

            hard_capacity = self.solver.Constraint(
                -infinity,
                self.config.max_utilization * capacity,
                f"capacity_{day_index}",
            )
            for variable, area, _block_code in terms:
                hard_capacity.SetCoefficient(variable, area)

            # peak >= daily_load / usable_capacity
            peak_constraint = self.solver.Constraint(
                -infinity, 0.0, f"peak_{day_index}"
            )
            for variable, area, _block_code in terms:
                peak_constraint.SetCoefficient(variable, area)
            peak_constraint.SetCoefficient(
                self.peak_utilization_vars[yard_code], -capacity
            )

            for band_index, (threshold, slope) in enumerate(
                self.config.congestion_bands
            ):
                max_excess = max(
                    0.0,
                    (self.config.max_utilization - threshold) * capacity,
                )
                excess = self.solver.NumVar(
                    0.0,
                    max_excess,
                    f"excess_{day_index}_{band_index}",
                )
                # load - excess <= threshold * capacity
                band_constraint = self.solver.Constraint(
                    -infinity,
                    threshold * capacity,
                    f"band_{day_index}_{band_index}",
                )
                for variable, area, _block_code in terms:
                    band_constraint.SetCoefficient(variable, area)
                band_constraint.SetCoefficient(excess, -1.0)
                self.excess_area_vars[(yard_code, day, threshold)] = (
                    excess,
                    slope,
                )

    def set_minimum_operating_cost_objective(self) -> None:
        """Minimize transport, first-fit deviation, and congestion."""

        objective = self.solver.Objective()
        for key, variable in self.assignment_vars.items():
            option = self.option_by_key[key]
            coefficient = (
                self.weights.transport * option.transport_score
                + self.weights.first_fit_rank * option.first_fit_rank
            )
            objective.SetCoefficient(variable, coefficient)

        for excess, marginal_slope in self.excess_area_vars.values():
            objective.SetCoefficient(
                excess,
                self.weights.utilization * marginal_slope / 1_000.0,
            )

        for peak_variable in self.peak_utilization_vars.values():
            objective.SetCoefficient(
                peak_variable, self.weights.peak_utilization
            )

        objective.SetMinimization()

    def build(
        self,
        blocks: Sequence[Block],
        yards: Sequence[Yard],
        options_by_block: Mapping[str, Sequence[AssignmentOption]],
    ) -> ModelArtifacts:
        """Build the complete model in dependency order."""

        if self._built:
            raise RuntimeError(
                "A StockyardModelBuilder instance can build only one model"
            )
        self.create_assignment_variables(blocks, options_by_block)
        self.add_exactly_one_yard_constraints(blocks, options_by_block)
        self.build_daily_active_terms(blocks, options_by_block)
        self.add_daily_capacity_and_congestion_constraints(yards)
        self.set_minimum_operating_cost_objective()
        self._built = True

        return ModelArtifacts(
            assignment_vars=self.assignment_vars,
            option_by_key=self.option_by_key,
            excess_area_vars=self.excess_area_vars,
            peak_utilization_vars=self.peak_utilization_vars,
            active_terms=self.active_terms,
        )
