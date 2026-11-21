from ortools.linear_solver import pywraplp
from collections import defaultdict
from datetime import date, timedelta
from ssi_yard.domain import Block

def create_solver() -> pywraplp.Solver:
    solver = pywraplp.Solver.CreateSolver("SCIP")
    if solver is None:
        raise RuntimeError("SCIP 솔버를 사용할 수 없습니다.")
    return solver

def create_assignment_variables(
    solver: pywraplp.Solver,
    candidates: dict[str, list[str]],
) -> dict[tuple[str, str], pywraplp.Variable]:
    x = {}

    for block_code, yard_codes in candidates.items():
        for yard_code in yard_codes:
            x[block_code, yard_code] = solver.BoolVar(
                f"x[{block_code},{yard_code}]"
            )

    return x

def add_assignment_constraints(
    solver: pywraplp.Solver,
    candidates: dict[str, list[str]],
    x: dict[tuple[str, str], pywraplp.Variable],
) -> None:
    for block_code, yard_codes in candidates.items():
        if not yard_codes:
            raise ValueError(f"{block_code}: 배정 가능한 야드가 없습니다.")

        solver.Add(
            solver.Sum(x[block_code, yard_code] for yard_code in yard_codes) == 1
        )

def add_capacity_constraints(
    solver: pywraplp.Solver,
    blocks: dict[str, Block],
    x: dict[tuple[str, str], pywraplp.Variable],
    allowed_area: dict[str, float],
    spacing_factor: float,
) -> dict:
    # (야드, 날짜)별로 그날 점유할 수 있는 블록의 면적 항을 모은다.
    terms_by_yard_day: dict[tuple[str, date], list] = defaultdict(list)

    for (block_code, yard_code), variable in x.items():
        block = blocks[block_code]
        area = spacing_factor * block.length_m * block.width_m

        day = block.inbound_date
        while day < block.outbound_date:
            terms_by_yard_day[yard_code, day].append(area * variable)
            day += timedelta(days=1)
    load_by_yard_day = {}

    # (C2) 일별 점유면적 L[y, d] ≤ 야드 허용 면적
    for (yard_code, day), terms in terms_by_yard_day.items():
        L = solver.Sum(terms)
        solver.Add(L <= allowed_area[yard_code], f"C2[{yard_code},{day}]")
        load_by_yard_day[yard_code, day] = L
    return load_by_yard_day

def add_congestion_constraints(
    solver: pywraplp.Solver,
    load_by_yard_day: dict,
    capacity: dict[str, float],
    tier_by_yard: dict[str, int],
    threshold_by_tier: dict[int, float],
) -> dict[tuple[str, date], pywraplp.Variable]:
    e = {}

    for (yard_code, day), L in load_by_yard_day.items():
        k = tier_by_yard[yard_code]
        threshold = threshold_by_tier[k]
        threshold_area = threshold * capacity[yard_code]

        e[yard_code, day] = solver.NumVar(
            0, solver.infinity(), f"e[{yard_code},{day}]"
        )
        solver.Add(
            e[yard_code, day] >= L - threshold_area,
            f"C3[{yard_code},{day}]",
        )

    return e

def set_objective(
    solver: pywraplp.Solver,
    x: dict,
    load_by_yard_day: dict,
    e: dict,
    movement_cost: dict[tuple[str, str], float],
    yard_rate: dict[str, float],
    tier_by_yard: dict[str, int],
    congestion_rate: dict[int, float],
) -> None:
    # 블록을 해당 야드에 배정했을 때의 입고·출고 이동비
    movement = solver.Sum(
        movement_cost[block_code, yard_code] * variable
        for (block_code, yard_code), variable in x.items()
    )

    # 일별 점유면적 × 야드별 면적당 하루 운영비
    occupancy = solver.Sum(
        yard_rate[yard_code] * L
        for (yard_code, day), L in load_by_yard_day.items()
    )

    # 야드에 지정된 단계의 단가 × 그날의 초과면적
    congestion = solver.Sum(
        congestion_rate[tier_by_yard[yard_code]] / 1000 * excess
        for (yard_code, day), excess in e.items()
    )

    solver.Minimize(movement + occupancy + congestion)


