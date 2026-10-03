from datetime import date
from pathlib import Path
import sys
from unittest import TestCase


SOLVER_DIR = Path(__file__).resolve().parents[1]
if str(SOLVER_DIR) not in sys.path:
    sys.path.insert(0, str(SOLVER_DIR))

from constraints import (  # noqa: E402
    AssignmentOption,
    Block,
    CostWeights,
    ModelConfig,
    StockyardModelBuilder,
    Yard,
    occupied_dates,
)
from ortools.linear_solver import pywraplp  # noqa: E402
from solver import build_assignment_options, extract_assignments, apply_first_fit_hint  # noqa: E402


def make_block(code: str, outbound_date: date) -> Block:
    return Block(
        code=code,
        inbound_factory="FACTORY_A",
        outbound_factory="FACTORY_B",
        inbound_date=date(2026, 1, 1),
        outbound_date=outbound_date,
        length_m=10.0,
        width_m=5.0,
        height_m=4.0,
    )


class WaitingPolicyTests(TestCase):
    def test_same_day_block_has_no_daily_occupancy(self) -> None:
        block = make_block("DIRECT", date(2026, 1, 1))

        self.assertEqual(block.dwell_days, 0)
        self.assertEqual(tuple(occupied_dates(block)), ())

    def test_factory_acceptance_day_does_not_consume_yard_capacity(self) -> None:
        block = make_block("WAIT", date(2026, 1, 3))

        self.assertEqual(
            tuple(occupied_dates(block)),
            (date(2026, 1, 1), date(2026, 1, 2)),
        )

    def test_builder_assigns_all_blocks_including_same_day(self) -> None:
        direct = make_block("DIRECT", date(2026, 1, 1))
        waiting = make_block("WAIT", date(2026, 1, 3))
        yard = Yard("Y1", "ZONE", 1_000.0, 1_000.0)
        option = AssignmentOption(
            block_code=waiting.code,
            yard_code=yard.code,
            route_distance_m=100.0,
            first_fit_rank=0,
            transport_score=0.1,
        )
        solver = pywraplp.Solver.CreateSolver("CBC")
        self.assertIsNotNone(solver)
        builder = StockyardModelBuilder(solver, ModelConfig(), CostWeights())

        from dataclasses import replace
        same_day_option = replace(option, block_code=direct.code)
        artifacts = builder.build(
            [direct, waiting],
            [yard],
            {direct.code: [same_day_option], waiting.code: [option]},
        )

        self.assertEqual(set(artifacts.assignment_vars), {(waiting.code, yard.code), (direct.code, yard.code)})
        self.assertEqual(apply_first_fit_hint(
            solver, [direct, waiting], [yard],
            {direct.code: [same_day_option], waiting.code: [option]},
            artifacts, ModelConfig()), (2, 0))
        self.assertEqual(solver.Solve(), pywraplp.Solver.OPTIMAL)
        rows, daily = extract_assignments([direct, waiting], artifacts, ModelConfig())
        self.assertEqual([row["assigned_yard"] for row in rows], [yard.code, yard.code])
        self.assertGreater(rows[0]["transport_score"], 0)
        self.assertEqual(daily[(yard.code, date(2026, 1, 1))]["active_blocks"], 1)

        self.assertEqual(
            artifacts.assignment_vars[(waiting.code, yard.code)].solution_value(),
            1.0,
        )

    def test_daily_terms_include_every_active_block(self) -> None:
        first = make_block("WAIT_1", date(2026, 1, 3))
        second = make_block("WAIT_2", date(2026, 1, 2))
        yard = Yard("Y1", "ZONE", 1_000.0, 1_000.0)

        def option(block: Block) -> AssignmentOption:
            return AssignmentOption(
                block_code=block.code,
                yard_code=yard.code,
                route_distance_m=100.0,
                first_fit_rank=0,
                transport_score=0.1,
            )

        solver = pywraplp.Solver.CreateSolver("CBC")
        self.assertIsNotNone(solver)
        artifacts = StockyardModelBuilder(
            solver, ModelConfig(), CostWeights()
        ).build(
            [first, second],
            [yard],
            {first.code: [option(first)], second.code: [option(second)]},
        )

        first_day_codes = {
            block_code
            for _variable, _area, block_code in artifacts.active_terms[
                (yard.code, date(2026, 1, 1))
            ]
        }
        second_day_codes = {
            block_code
            for _variable, _area, block_code in artifacts.active_terms[
                (yard.code, date(2026, 1, 2))
            ]
        }
        self.assertEqual(first_day_codes, {first.code, second.code})
        self.assertEqual(second_day_codes, {first.code})

    def test_larger_block_has_higher_transport_cost(self) -> None:
        small = make_block("SMALL", date(2026, 1, 3))
        large = Block(
            code="LARGE",
            inbound_factory=small.inbound_factory,
            outbound_factory=small.outbound_factory,
            inbound_date=small.inbound_date,
            outbound_date=small.outbound_date,
            length_m=20.0,
            width_m=10.0,
            height_m=8.0,
        )
        yard = Yard("Y1", "ZONE", 10_000.0, 10_000.0)
        distances = {
            (yard.code, small.inbound_factory): 100.0,
            (yard.code, small.outbound_factory): 200.0,
        }

        options = build_assignment_options(
            [small, large],
            [yard],
            distances,
            ModelConfig(),
            candidate_yard_count=0,
            overflow_yard_count=0,
        )
        small_option = options[small.code][0]
        large_option = options[large.code][0]

        self.assertGreater(
            large_option.transport_score, small_option.transport_score
        )
