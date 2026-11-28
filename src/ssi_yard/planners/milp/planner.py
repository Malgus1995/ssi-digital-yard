from ortools.linear_solver import pywraplp
import math
from collections import defaultdict
from datetime import timedelta

from ssi_yard.domain import Block

from .model import (
    create_solver,
    create_assignment_variables,
    add_assignment_constraints,
    add_capacity_constraints,
    add_congestion_constraints,
    set_objective,
)

def solve_assignment(
    solver: pywraplp.Solver,
    x: dict[tuple[str, str], pywraplp.Variable],
    time_limit_ms: int = 30_0000,
    diagnostics: dict | None = None,
) -> dict[str, str] | None:
    solver.SetTimeLimit(time_limit_ms)
    status = solver.Solve()
    if diagnostics is not None:
        labels = {solver.OPTIMAL: 'OPTIMAL', solver.FEASIBLE: 'FEASIBLE',
                  solver.INFEASIBLE: 'INFEASIBLE', solver.UNBOUNDED: 'UNBOUNDED',
                  solver.ABNORMAL: 'ABNORMAL', solver.NOT_SOLVED: 'NOT_SOLVED'}
        diagnostics.update(termination_status=labels.get(status, str(status)),
                           optimality_proven=status == solver.OPTIMAL,
                           solver_version=solver.SolverVersion(),
                           solve_time_limit_ms=time_limit_ms)
        if status in (solver.OPTIMAL, solver.FEASIBLE):
            value, bound = solver.Objective().Value(), solver.Objective().BestBound()
            diagnostics.update(objective=value, best_bound=bound if math.isfinite(bound) else None,
                               relative_gap=max(0., value-bound)/max(1e-10,abs(value)) if math.isfinite(bound) else None,
                               relative_gap_definition='(objective - best_bound) / abs(objective); may differ from SCIP display gap',
                               solution_verified=solver.VerifySolution(1e-5, True))

    if status not in (solver.OPTIMAL, solver.FEASIBLE):
        print(f"배정 결과를 얻지 못했습니다. 솔버 상태 코드 {status}")
        return None

    if status == solver.OPTIMAL:
        print("최적해를 찾았습니다.")
    else:
        print("가능한 해를 찾았습니다. 최적성은 아직 확인되지 않았습니다.")

    assignment = {}

    for (block_code, yard_code), variable in x.items():
        if variable.solution_value() > 0.5:
            assignment[block_code] = yard_code

    print(f"목적함수 값 {solver.Objective().Value():,.2f}")
    return assignment

def plan(
    blocks: dict[str, Block],
    candidates: dict[str, list[str]],
    *,
    capacity: dict[str, float],
    max_utilization: float,
    spacing_factor: float,
    movement_cost: dict[tuple[str, str], float],
    yard_rate: dict[str, float],
    tier_by_yard: dict[str, int],
    threshold_by_tier: dict[int, float],
    congestion_rate: dict[int, float],
    time_limit_ms: int = 300_000,
    diagnostics: dict | None = None,
    enable_output: bool = False,
) -> tuple[dict[str, str], float] | None:
    solver = create_solver()
    if enable_output:
        solver.EnableOutput()

    x = create_assignment_variables(solver, candidates)
    add_assignment_constraints(solver, candidates, x)

    allowed_area = {
        yard_code: area * max_utilization
        for yard_code, area in capacity.items()
    }

    load_by_yard_day = add_capacity_constraints(
        solver=solver,
        blocks=blocks,
        x=x,
        allowed_area=allowed_area,
        spacing_factor=spacing_factor,
    )

    e = add_congestion_constraints(
        solver=solver,
        load_by_yard_day=load_by_yard_day,
        capacity=capacity,
        tier_by_yard=tier_by_yard,
        threshold_by_tier=threshold_by_tier,
    )

    set_objective(
        solver=solver,
        x=x,
        load_by_yard_day=load_by_yard_day,
        e=e,
        movement_cost=movement_cost,
        yard_rate=yard_rate,
        tier_by_yard=tier_by_yard,
        congestion_rate=congestion_rate,
    )

    assignment = solve_assignment(
        solver, x,
        time_limit_ms=time_limit_ms,
        diagnostics=diagnostics
    )

    if assignment is None:
        return None

    solver_objective = solver.Objective()
    total_cost = solver_objective.Value()

    # ==========================================
    # 1. 배정 변수의 실제 목적함수 기여량
    # ==========================================
    raw_base_cost = math.fsum(
        solver_objective.GetCoefficient(var)
        * var.solution_value()
        for var in x.values()
    )

    assigned_base_cost = math.fsum(
        solver_objective.GetCoefficient(
            x[block_code, yard_code]
        )
        for block_code, yard_code in assignment.items()
    )

    # ==========================================
    # 2. 반환된 배정 결과로 점유면적 재계산
    # ==========================================
    actual_loads = defaultdict(float)

    for block_code, yard_code in assignment.items():

        block = blocks[block_code]

        area = (
            spacing_factor
            * block.length_m
            * block.width_m
        )

        day = block.inbound_date

        while day < block.outbound_date:
            actual_loads[yard_code, day] += area
            day += timedelta(days=1)

    # ==========================================
    # 3. SCIP 혼잡 변수와 실제 초과면적 비교
    # ==========================================
    solver_congestion_terms = []
    expected_congestion_terms = []

    slack_count = 0
    max_excess_slack = 0.0
    max_excess_deficit = 0.0

    for (yard_code, day), var in e.items():

        tier = tier_by_yard[yard_code]

        rate = congestion_rate[tier] / 1000

        threshold = (
            threshold_by_tier[tier]
            * capacity[yard_code]
        )

        actual_load = actual_loads[yard_code, day]

        expected_excess = max(
            0.0, actual_load - threshold
        )

        solver_excess = var.solution_value()

        slack = solver_excess - expected_excess

        if slack > 1e-6:
            slack_count += 1

        max_excess_slack = max(
            max_excess_slack, slack
        )

        max_excess_deficit = max(
            max_excess_deficit, -slack
        )

        solver_congestion_terms.append(
            rate * solver_excess
        )

        expected_congestion_terms.append(
            rate * expected_excess
        )

    solver_congestion = math.fsum(
        solver_congestion_terms
    )

    expected_congestion = math.fsum(
        expected_congestion_terms
    )

    # ==========================================
    # 4. 목적함수 차이 분석
    # ==========================================
    reconstructed_cost = (
        assigned_base_cost
        + expected_congestion
    )

    audit = {
        'solver_objective': total_cost,

        'raw_base_cost': raw_base_cost,
        'assigned_base_cost': assigned_base_cost,

        'solver_congestion': solver_congestion,
        'expected_congestion': expected_congestion,

        'assignment_rounding_difference':
            raw_base_cost - assigned_base_cost,

        'congestion_difference':
            solver_congestion - expected_congestion,

        'solver_objective_residual':
            total_cost - (
                raw_base_cost + solver_congestion
            ),

        'reconstructed_objective':
            reconstructed_cost,

        'objective_difference':
            total_cost - reconstructed_cost,

        'excess_slack_count': slack_count,
        'max_excess_slack': max_excess_slack,
        'max_excess_deficit': max_excess_deficit,

        'num_variables': solver.NumVariables(),
        'num_constraints': solver.NumConstraints(),
    }

    if diagnostics is not None:
        diagnostics['objective_audit'] = audit

    print('\n===== MILP OBJECTIVE AUDIT =====')

    for key, value in audit.items():
        print(f'{key:35s}: {value:,.10f}')

    return assignment, total_cost
