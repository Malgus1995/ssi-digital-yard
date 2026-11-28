"""Run and benchmark methods, writing MILP-compatible results and separate metrics."""
import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from ssi_yard.benchmark.environment import environment_fingerprint, objective_parameters, save_metrics
from ssi_yard.benchmark.evaluation import evaluate_assignment
from ssi_yard.benchmark.results import create_daily_moves, save_result
from ssi_yard.data.load_scenario import load_scenario
from ssi_yard.data.prepare_milp import prepare_milp_inputs
from .planner import greedy, search
from .problem import Problem


def _save(path, assignment, cost, inputs, metrics):
    save_result(path, assignment, create_daily_moves(inputs['blocks'], assignment), cost)
    return save_metrics(path, metrics)


def baseline_report(path, inputs, objective, fingerprint):
    if not path.exists():
        return None
    result = json.loads(path.read_text(encoding='utf-8'))
    check = evaluate_assignment(result['assignment'], **inputs, **objective)
    if not math.isclose(result['total_cost'], check['cost']['total'], abs_tol=1e-4, rel_tol=1e-9):
        raise ValueError('기존 MILP 비용이 현재 환경의 재계산 비용과 다릅니다.')
    metrics_path = path.with_name('metrics.json')
    existing = json.loads(metrics_path.read_text()) if metrics_path.exists() else {}
    result_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if existing.get('result_sha256') != result_sha or existing.get('problem_fingerprint') != fingerprint:
        # Validate a legacy baseline, but never invent a duration for its past solver run.
        existing = save_metrics(path, {
            'algorithm': 'MILP', 'problem_fingerprint': fingerprint, 'status': 'feasible',
            'provenance': 'legacy_result_revalidated', 'timing': {'solver_seconds': None, 'total_seconds': None},
            **check, 'history': [],
        })
    return {'path': str(path), 'cost': result['total_cost'], 'metrics': existing}


def main(argv=None):
    parser = argparse.ArgumentParser(description='MILP와 동일한 환경에서 Greedy → SA/Tabu 실행')
    parser.add_argument('--data-dir', type=Path, default=Path('raw-data'))
    parser.add_argument('--config', type=Path, default=Path('scenarios/milp.json'))
    parser.add_argument('--output-dir', type=Path, default=Path('runs/meta-heuristics'))
    parser.add_argument('--algorithm', choices=('all', 'greedy', 'sa', 'tabu'), default='all')
    parser.add_argument('--time-limit', type=float, default=5.0, help='SA/Tabu 각각의 탐색 시간 예산 (초, 그리디/입출력 별도)')
    parser.add_argument('--iterations', type=int, default=1_000_000, help='방법별 최대 반복 수 (시간 예산과 먼저 도달하는 조건)')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--neighborhood-size', type=int, default=48)
    parser.add_argument('--tabu-tenure', type=int, default=17)
    parser.add_argument('--temperature', type=float, default=None, help='SA 초기 온도 (기본: 후보 비용차에서 자동 산정)')
    parser.add_argument('--baseline', type=Path, default=Path('runs/milp/result.json'))
    args = parser.parse_args(argv)
    if not math.isfinite(args.time_limit) or args.time_limit < 0 or args.iterations < 0:
        parser.error('time-limit와 iterations는 유한한 0 이상의 값이어야 합니다.')
    if args.neighborhood_size < 1 or args.tabu_tenure < 1:
        parser.error('neighborhood-size와 tabu-tenure는 1 이상이어야 합니다.')
    if args.temperature is not None and (not math.isfinite(args.temperature) or args.temperature <= 0):
        parser.error('temperature는 유한한 양수여야 합니다.')
    started = perf_counter()
    config = json.loads(args.config.read_text(encoding='utf-8'))
    scenario = load_scenario(args.data_dir)
    inputs = prepare_milp_inputs(scenario, spacing_factor=config['spacing_factor'],
                                max_utilization=config['max_utilization'],
                                movement_rate_per_m=config['movement_rate_per_m'])
    objective = objective_parameters(config, inputs['capacity'])
    problem = Problem(**inputs, **objective)
    fingerprint = environment_fingerprint(args.data_dir, config)
    preparation = perf_counter() - started
    print(f'동일 환경: {problem.n:,}개 배정 · {len(problem.yards)}개 적치장 · 준비 {preparation:.3f}s', flush=True)
    initial = greedy(problem)
    print(f"Greedy: {initial['cost']:,.3f} · {initial['seconds']:.3f}s · 시도 {initial['attempts']}회", flush=True)
    methods = ['greedy'] + (['sa', 'tabu'] if args.algorithm == 'all' else [args.algorithm] if args.algorithm != 'greedy' else [])
    outputs, reports = {}, {}
    initial_cost = None
    run_id = datetime.now(timezone.utc).isoformat()
    for method in methods:
        output = initial if method == 'greedy' else search(
            problem, initial, algorithm=method, time_limit=args.time_limit, max_iterations=args.iterations,
            seed=args.seed, neighborhood_size=args.neighborhood_size, tabu_tenure=args.tabu_tenure,
            initial_temperature=args.temperature)
        assignment = problem.assignment_dict(output['assignment'])
        validation_started = perf_counter()
        check = evaluate_assignment(assignment, **inputs, **objective)
        validation_seconds = perf_counter() - validation_started
        cost = check['cost']['total']
        if method == 'greedy':
            initial_cost = cost
        if not math.isclose(cost, output['cost'], abs_tol=1e-4, rel_tol=1e-9):
            raise AssertionError(f'{method}: 증분 비용과 독립 평가 비용 불일치')
        search_seconds = 0.0 if method == 'greedy' else output['seconds']
        solver_seconds = initial['seconds'] + search_seconds
        metrics = {
            'algorithm': {'greedy': 'Greedy', 'sa': 'Greedy + SA', 'tabu': 'Greedy + Tabu'}[method],
            'method': method, 'run_id': run_id, 'seed': args.seed,
            'problem_fingerprint': fingerprint, 'status': 'feasible',
            'timing': {'preparation_seconds': preparation, 'greedy_seconds': initial['seconds'],
                       'search_seconds': search_seconds, 'solver_seconds': solver_seconds,
                       'validation_seconds': validation_seconds,
                       'total_seconds': preparation + solver_seconds + validation_seconds},
            'initial_cost': initial_cost, 'improvement_percent': (initial_cost - cost) / initial_cost * 100 if initial_cost else 0,
            'relaxed_lower_bound': problem.lower_bound,
            'gap_to_relaxed_bound_percent': (cost - problem.lower_bound) / problem.lower_bound * 100 if problem.lower_bound else 0,
            'iterations': output.get('iterations', 0), 'evaluated_neighbors': output.get('evaluated_neighbors', 0),
            'accepted_moves': output.get('accepted_moves', 0), 'improvements': output.get('improvements', 0),
            'stop_reason': output.get('stop_reason', 'greedy_complete'),
            'parameters': {'time_limit_seconds': args.time_limit, 'max_iterations': args.iterations,
                           'neighborhood_size': args.neighborhood_size, 'tabu_tenure': args.tabu_tenure,
                           'initial_temperature': output.get('initial_temperature')},
            'history': output.get('history', [{'iteration': 0, 'seconds': 0.0, 'current_cost': cost, 'best_cost': cost}]),
            **check,
        }
        path = args.output_dir / method / 'result.json'
        reports[method] = _save(path, assignment, cost, inputs, metrics)
        outputs[method] = (assignment, cost)
        print(f"{method.upper():6} 비용 {cost:,.3f} · 풀이 {solver_seconds:.3f}s · 개선 {metrics['improvement_percent']:.4f}% · 이웃 {metrics['evaluated_neighbors']:,} · 용량 검증 통과", flush=True)
    winner = min(outputs, key=lambda m: outputs[m][1])
    assignment, cost = outputs[winner]
    best_metrics = dict(reports[winner], selected_method=winner)
    _save(args.output_dir / 'result.json', assignment, cost, inputs, best_metrics)
    baseline = None
    try:
        baseline = baseline_report(args.baseline, inputs, objective, fingerprint)
    except (ValueError, KeyError) as error:
        print(f'MILP 비교 제외: {error}', flush=True)
    comparison = {'problem_fingerprint': fingerprint, 'run_id': run_id, 'selected_method': winner,
                  'methods': {m: {'total_cost': c, 'metrics': reports[m]} for m, (_, c) in outputs.items()},
                  'baseline': baseline, 'elapsed_seconds': perf_counter() - started}
    (args.output_dir / 'comparison.json').write_text(json.dumps(comparison, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    if baseline:
        gap = (cost - baseline['cost']) / baseline['cost'] * 100 if baseline['cost'] else 0
        print(f"MILP {baseline['cost']:,.3f} 대비 비용차 {gap:+.4f}% (음수면 더 낮음). 기존 MILP 시간은 기록이 없으면 표시하지 않습니다.", flush=True)
    print(f"최선 {winner.upper()} → {args.output_dir / 'result.json'} · 전체 실행 {comparison['elapsed_seconds']:.3f}s", flush=True)


if __name__ == '__main__':
    main()
