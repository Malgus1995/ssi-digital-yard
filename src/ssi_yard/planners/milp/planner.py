from ortools.linear_solver import pywraplp

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
) -> dict[str, str] | None:
    solver.SetTimeLimit(time_limit_ms)
    status = solver.Solve()

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
) -> tuple[dict[str, str], float] | None:
    solver = create_solver()

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

    assignment = solve_assignment(solver, x)
    if assignment is None:
        return None

    return assignment, solver.Objective().Value()
