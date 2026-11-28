import argparse
import json
import math
import sys
from pathlib import Path
from time import perf_counter

# Support direct execution from a fresh checkout as well as editable installs.
sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
from ssi_yard.data.load_scenario import load_scenario
from ssi_yard.data.prepare_milp import prepare_milp_inputs
from ssi_yard.benchmark.environment import environment_fingerprint, objective_parameters, save_metrics
from ssi_yard.benchmark.evaluation import evaluate_assignment
from ssi_yard.benchmark.results import create_daily_moves, save_result


def main() -> None:
    parser = argparse.ArgumentParser(description='MILP 배정 및 비교용 실행 정보 저장')
    parser.add_argument('--data-dir', type=Path, default=Path('raw-data'))
    parser.add_argument('--config', type=Path, default=Path('scenarios/milp.json'))
    parser.add_argument('--output', type=Path, default=Path('runs/milp/result.json'))
    parser.add_argument('--time-limit', type=float, default=300, help='MILP 풀이 시간 제한 (초)')
    parser.add_argument('--solver-log', action='store_true', help='SCIP 탐색 로그 출력')
    args = parser.parse_args()
    if not math.isfinite(args.time_limit) or args.time_limit <= 0:
        parser.error('time-limit는 유한한 양수여야 합니다.')
    from ssi_yard.planners.milp.planner import plan
    started = perf_counter()
    config = json.loads(args.config.read_text(encoding='utf-8'))
    scenario = load_scenario(args.data_dir)
    inputs = prepare_milp_inputs(scenario, spacing_factor=config['spacing_factor'],
                                max_utilization=config['max_utilization'],
                                movement_rate_per_m=config['movement_rate_per_m'])
    objective = objective_parameters(config, inputs['capacity'])
    fingerprint = environment_fingerprint(args.data_dir, config)
    preparation_seconds = perf_counter() - started
    solve_started = perf_counter()
    diagnostics = {}
    result = plan(**inputs, **objective, time_limit_ms=max(1, int(args.time_limit * 1000)),
                  diagnostics=diagnostics, enable_output=args.solver_log)
    solver_seconds = perf_counter() - solve_started
    if result is None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.with_name('diagnostics.json').write_text(json.dumps({
            'problem_fingerprint': fingerprint, 'solver': diagnostics,
            'preparation_seconds': preparation_seconds, 'solver_seconds': solver_seconds,
        }, indent=2, allow_nan=False), encoding='utf-8')
        return
    assignment, total_cost = result

    # ==================================================
    # 1. SCIP 원본 해 저장 (검증 실패 시에도 보존)
    # ==================================================
    args.output.parent.mkdir(parents=True, exist_ok=True)

    raw_path = args.output.with_name('solver_candidate.json')

    raw_path.write_text(
        json.dumps({
            'problem_fingerprint': fingerprint,
            'assignment': assignment,
            'solver_objective': total_cost,
            'solver': diagnostics,
            'solver_seconds': solver_seconds,
        }, ensure_ascii=False, indent=2, allow_nan=False),
        encoding='utf-8'
    )

    print(f'SCIP 원본 해 저장 완료: {raw_path}', flush=True)

    # ==================================================
    # 2. 독립적인 목적함수 재계산
    # ==================================================
    validation_started = perf_counter()

    check = evaluate_assignment(
        assignment, **inputs, **objective
    )

    evaluated_cost = check['cost']['total']
    difference = total_cost - evaluated_cost

    # ==================================================
    # 3. 목적함수 비교 및 상세 로그
    # ==================================================
    print('\n===== OBJECTIVE AUDIT =====')
    print(f'SCIP Objective : {total_cost:,.10f}')
    print(f'Evaluated Cost : {evaluated_cost:,.10f}')
    print(f'Difference     : {difference:,.10f}')
    print(f'Abs Difference : {abs(difference):,.10f}')

    print('\n===== COST BREAKDOWN =====')
    print(json.dumps(check['cost'], indent=2))

    print('\n===== FEASIBILITY =====')
    print(json.dumps(check['feasibility'], indent=2))

    print('\n===== SOLVER DIAGNOSTICS =====')
    print(json.dumps(diagnostics, indent=2))

    # ==================================================
    # 4. 검증 결과 별도 저장
    # ==================================================
    audit_path = args.output.with_name('objective_audit.json')

    objective_matched = math.isclose(
        total_cost,
        evaluated_cost,
        rel_tol=1e-9,
        abs_tol=1e-4,
    )

    audit_path.write_text(
        json.dumps({
            'problem_fingerprint': fingerprint,
            'solver_objective': total_cost,
            'evaluated_objective': evaluated_cost,
            'difference': difference,
            'absolute_difference': abs(difference),
            'objective_matched': objective_matched,
            'solver': diagnostics,
            **check,
        }, ensure_ascii=False, indent=2, allow_nan=False),
        encoding='utf-8'
    )

    # ==================================================
    # 5. 기존 검증 조건 유지
    # ==================================================
    if not objective_matched:
        raise ValueError(
            f'MILP 목적함수와 독립 평가 비용이 다릅니다. '
            f'SCIP={total_cost:.10f}, '
            f'Evaluated={evaluated_cost:.10f}, '
            f'Difference={difference:.10f}'
        )

    if check['feasibility']['valid'] is not True:
        raise ValueError('MILP 배정 결과가 제약조건을 위반했습니다.')

    validation_seconds = perf_counter() - validation_started
    
    save_result(args.output, assignment, create_daily_moves(inputs['blocks'], assignment), total_cost)
    save_metrics(args.output, {
        'algorithm': 'MILP', 'problem_fingerprint': fingerprint,
        'status': 'optimal' if diagnostics.get('optimality_proven') else 'feasible',
        'solver': diagnostics,
        'provenance': 'measured_solver_run', 'parameters': {'time_limit_seconds': args.time_limit},
        'timing': {'preparation_seconds': preparation_seconds, 'solver_seconds': solver_seconds,
                   'validation_seconds': validation_seconds,
                   'total_seconds': preparation_seconds + solver_seconds + validation_seconds},
        **check, 'history': [],
    })
    print(f'결과 저장 완료 {args.output} · 풀이 {solver_seconds:.3f}s · 비용·용량 검증 통과')


if __name__ == '__main__':
    main()
