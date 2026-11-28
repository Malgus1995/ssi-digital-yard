# 배정 방법

공통 계약은 `Planner.plan(Scenario) -> YardAssignment`다. 배정에는 대기 블록만 포함한다.

- `meta-heuristics/`에 그리디 초기해와 증분 비용 기반 SA·Tabu 탐색을 구현한다. `python3 run_meta.py`로 실행하며 [실행 및 출력 안내](meta-heuristics/README.md)를 참고한다.
- `milp/model.py`에 PDF 순서대로 배정 변수, 일별 점유, 혼잡 초과면적, 목적함수, C1–C5를 정의한다. `milp/planner.py`에서 OR-Tools 풀이와 후보 재검증을 연결한다.
- `rl/environment.py`, `rl/train.py`, `rl/policy.py`에 환경, 학습, 추론을 구현한다. 각 행동은 다음 블록의 야드 선택이다.
