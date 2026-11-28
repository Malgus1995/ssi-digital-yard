# 그리디 기반 메타휴리스틱

MILP의 `prepare_milp_inputs`를 그대로 사용합니다. 같은 후보 적치장, 최단시간 경로의 이동거리 비용, 간격 계수, 일별 용량, 야드별 운영 단가와 혼잡 단가를 적용합니다. 기본 실행에는 외부 패키지가 필요하지 않습니다.

프로젝트 루트에서:

```sh
python3 run_meta.py
python3 dashboard/serve.py
```

대시보드 상단 알고리즘 선택기로 MILP / 메타휴리스틱 최선 / Greedy / SA / Tabu 지도를 전환합니다. 하단 **알고리즘 성능 비교**에서 비용, 시간, 그리디 대비 개선율, MILP 저장 결과 대비 비용차, 반복 수와 수렴 그래프를 확인합니다.

## 실행 옵션

```sh
# 같은 그리디 초기해에서 SA와 Tabu를 각각 최대 5초 탐색 (기본값)
python3 run_meta.py --algorithm all --time-limit 5 --seed 42

# 빠른 단일 실행
python3 run_meta.py --algorithm tabu --time-limit 2
python3 run_meta.py --algorithm sa --time-limit 2
python3 run_meta.py --algorithm greedy

# 시간 제한이 먼저 걸리지 않으면 동일 시드와 반복 수로 해를 재현
python3 run_meta.py --algorithm sa --iterations 100000 --time-limit 60 --seed 42

# Tabu 후보 집합 크기와 금지 기간, SA 초기 온도 조정
python3 run_meta.py --neighborhood-size 48 --tabu-tenure 17 --temperature 5

# 다른 공통 환경과 출력 위치
python3 run_meta.py --data-dir raw-data --config scenarios/milp.json --output-dir runs/meta-heuristics

# 패키지 엔트리 포인트도 지원
PYTHONPATH=src python3 -m ssi_yard.planners.meta-heuristics --time-limit 2
```

`--time-limit`는 **각 탐색 방법별** 예산이며 전처리, 필수 그리디 구축, 최선 해 복원/검증과 JSON 저장 시간은 별도입니다. `all`은 그리디 한 번 + SA + Tabu이므로 기본 탐색 예산 합계는 최대 약 10초입니다. 반복 수와 시간 제한 중 먼저 도달하는 조건에서 멈춥니다. 타부 이웃 후보를 조사하는 도중에도 시간 예산을 확인합니다. 시간이 먼저 만료되는 실행은 하드웨어 부하에 따라 반복 수와 결과가 달라질 수 있습니다.

그리디 결과는 매 실행 저장합니다. SA/Tabu는 실행한 방법의 폴더만 갱신합니다. 다른 방법의 과거 결과는 보존하므로, 같은 실행의 결과끼리 비교하려면 `all`을 실행하거나 `metrics.json`의 `run_id`를 확인합니다. 루트 `result.json`은 **이번 실행에서 실행한 방법들 중 최선**입니다.

## 목적함수와 제약

- 블록마다 후보 야드 한 개를 선택합니다. 당일 직행은 야드 배정에서 제외하고 공통 이벤트 생성기가 직행 이동을 기록합니다.
- 일별 점유는 입고일 포함, 출고일 제외입니다.
- `A[b] = spacing_factor × length[b] × width[b]`.
- 모든 야드·날짜에서 `L[y,d] ≤ capacity[y] × max_utilization`.
- 이동비: 공통 전처리기가 계산한 `movement_cost[b,y]`의 합.
- 운영비: `Σ yard_rate[y] × L[y,d]`.
- 혼잡비: `Σ congestion_rate[tier[y]] / 1000 × max(0, L[y,d] − threshold[tier[y]] × capacity[y])`.

실제 2D 도형 패킹·통로·적층은 기존 MILP와 동일하게 제약에 포함하지 않습니다. 대시보드의 겹침 보정 좌표도 운송 거리나 비용에 적용하지 않습니다.

## 탐색 구조와 속도

1. 날짜·후보 수·면적을 고려한 순서로, 일별 용량을 지키면서 추가 비용이 가장 낮은 야드를 그리디로 선택합니다. 비음수 혼잡비의 하한을 이용해 비싼 후보를 조기에 제외합니다. 구축에 실패하면 후보 수/면적 중심의 대체 순서 2개로 재시도합니다. 여전히 실패하면 초기해 구축 실패를 알리며 문제 자체가 불가능하다고 판정하지 않습니다.
2. SA와 Tabu는 **동일한 완성 그리디 배정**에서 독립적으로 시작합니다. 공통 입력/초기해는 수정하지 않습니다.
3. 이웃은 한 블록의 야드 변경과 두 블록의 야드 교환입니다. 야드·날짜별 재고 인덱스에서 보관 기간이 겹치는 교환 상대를 바로 추출합니다.
4. 변화가 생긴 두 야드와 블록 보관 기간만 평가합니다. 이동비+운영비는 블록-야드별로 미리 계산하고, 비선형 혼잡비만 해당 날짜의 증분으로 계산합니다. 전체 블록 재평가나 후보 쌍 전수 탐색을 피합니다.
5. SA는 지수 냉각과 `exp(-Δ/T)` 확률로 나빠지는 이동도 허용합니다. Tabu는 표본 이웃 중 허용된 최선 이동을 고르고 역이동을 일정 반복 동안 금지하며, 전체 최선 해를 갱신하는 이동은 금지를 해제합니다.
6. 용량 초과 이웃은 거부합니다. 탐색 중 최선 해를 보관하므로 반환 비용은 그리디보다 나빠지지 않습니다. 종료 시 별도 평가기로 전체 비용과 모든 일별 용량을 재검증합니다.

`relaxed_lower_bound`는 혼잡비와 동시 용량 제약을 제외한 블록별 최저 비용의 합입니다. 이 하한에 대한 차이는 최적해와의 정확한 차이가 아닙니다. 저장된 MILP 결과보다 비용이 낮아도 새 해의 최적성이 증명되는 것은 아닙니다.

## 출력 계약

```text
runs/meta-heuristics/
  result.json          # 이번 실행의 최선 해 (정확히 MILP의 세 필드)
  metrics.json         # 최선 방법과 실행 정보
  comparison.json      # 이번 실행의 방법별 지표와 MILP 참조 결과
  greedy/result.json
  greedy/metrics.json
  sa/result.json
  sa/metrics.json
  tabu/result.json
  tabu/metrics.json
```

모든 `result.json`은 `total_cost`, `assignment`, `daily_moves`만 포함합니다. 기존 공통 `save_result`와 `create_daily_moves`를 사용하므로 MILP와 동일한 형식입니다. `metrics.json`에는 비용 구성, 초기해 개선율, 시드, 반복·이웃 수, 시간, 탐색 이력, 용량 검증, 입력/설정 지문과 결과 파일 SHA-256을 별도로 저장합니다. 최적화 결과 폴더는 기존 `.gitignore`에 의해 버전 관리에서 제외됩니다.

시간 정의:

- `solver_seconds`: 그리디 구축 + 해당 방법의 탐색/최선 해 복원. MILP는 모델 구성 + Solve.
- `total_seconds`: 공통 전처리 + 풀이 + 독립 검증. JSON 저장 제외. 공통 전처리와 그리디를 각각 실행한 것으로 계산한 방법별 비교 시간입니다.
- `comparison.json.elapsed_seconds`: 여러 방법을 한 번에 실행한 실제 경과 시간. 결과 저장과 MILP 참조 검증도 포함합니다.

기존 `runs/milp/result.json`은 현재 환경에서 비용과 용량을 재검증하고, 가능하면 `runs/milp/metrics.json`에 비교용 지문을 기록합니다. 과거 MILP 실행 시간은 추정하지 않습니다. 이후 `.venv/bin/python main.py --time-limit 300`으로 MILP를 다시 실행하면 실제 시간도 저장됩니다. 원본 MILP 결과 자체는 메타휴리스틱 실행에서 수정하지 않습니다.

## Python 호출

요청된 폴더 이름에 하이픈이 있으므로 Python 코드에서는 `importlib`를 사용합니다.

```python
from importlib import import_module
meta = import_module('ssi_yard.planners.meta-heuristics')
assignment, total_cost = meta.plan(
    **inputs,                 # prepare_milp_inputs(...) 반환값
    **objective_parameters,  # benchmark.environment.objective_parameters(...) 반환값
    algorithm='tabu', time_limit=5, seed=42,
)
```

## 검증

```sh
python3 -m unittest discover -s tests -v
# OR-Tools가 있는 환경에서는 원래 MILP 모델과의 목적함수 비교도 실행
.venv/bin/python -m unittest discover -s tests -v
node dashboard/test_dashboard.cjs
python3 dashboard/test_layout.py
```

작은 문제의 모든 가능한 배정을 열거해 독립 평가 비용과 이동/교환 증분 비용을 비교합니다. 용량을 꽉 채운 야드의 동시 교환, 서로 다른 보관 기간·면적·단가·혼잡 임계값, 날짜 경계, 직행, 구축 재시도, 최선 해 보존, 재현성, 0초 예산, 출력 파일과 CLI를 검증합니다.
