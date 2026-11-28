"""Unified local runner for all implemented planners and dashboard publication."""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'dashboard'))
from build_data import build
from jobs import JobManager, TERMINAL


def main(argv=None):
    parser = argparse.ArgumentParser(description='MILP·메타휴리스틱 선택 실행. all은 두 방법을 동시에 실행합니다.')
    parser.add_argument('--algorithm', choices=('all', 'milp', 'meta'), default='all')
    parser.add_argument('--milp-time-limit', type=float, default=300, help='MILP Solve 제한 초 (기본 300, 모델 구성 별도)')
    parser.add_argument('--meta-time-limit', type=float, default=5, help='SA·Tabu 각각의 탐색 제한 초 (기본 5)')
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args(argv)
    manager = JobManager(ROOT, build)
    try:
        job = manager.start({'target': 'both' if args.algorithm == 'all' else args.algorithm,
                             'milp_seconds': args.milp_time_limit, 'meta_seconds': args.meta_time_limit,
                             'seed': args.seed})
    except (ValueError, RuntimeError) as error:
        parser.error(str(error))
    print(f"실행 시작: {job['id']} · 옵션 {args.algorithm}\n기록: {ROOT / job['directory']}", flush=True)
    print('결과 저장: runs/milp/result.json · runs/meta-heuristics/result.json (선택한 방법만 갱신)', flush=True)
    if args.algorithm == 'all':
        print('동시 실행: CPU·메모리를 공유하므로 단독 실행보다 느려질 수 있습니다.', flush=True)
    previous = None
    last_print = 0
    try:
        while True:
            job = manager.status()
            summary = [(name, task['status']) for name, task in job['tasks'].items()]
            if summary != previous or time.monotonic() - last_print > 10:
                for name, task in job['tasks'].items():
                    print(f"{name.upper()}: {task['status']} · 경과 {task['elapsed_seconds']}초", flush=True)
                    if task.get('error'): print(task['error'], flush=True)
                previous = summary; last_print = time.monotonic()
            if job['status'] in TERMINAL:
                break
            time.sleep(.5)
    except KeyboardInterrupt:
        print('\n실행 중지 요청', flush=True)
        manager.cancel(job['id'])
    finally:
        manager.close()
    job = manager.status()
    print(f"전체 상태: {job['status']} · 반영된 결과: {', '.join(job['published']) or '없음'}", flush=True)
    return 0 if job['status'] == 'succeeded' else 1


if __name__ == '__main__':
    raise SystemExit(main())
