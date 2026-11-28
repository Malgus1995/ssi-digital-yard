# SSI Digital Yard

생산 스케줄을 입력으로 휴리스틱, OR-Tools MILP, 강화학습의 야드 배정을
비교하기 위한 프로젝트다.

도메인과 배정 계약, CSV 검증, 최단시간 도로 경로, MILP 배정과
그리디 기반 SA·Tabu 탐색, 결과 재생용 웹 대시보드를 제공한다. 공통 시뮬레이터와 추가 배정 알고리즘은
각 디렉터리의 설계에 따라 구현한다.

```sh
PYTHONPATH=src python -m ssi_yard.cli --data-dir raw-data
```

## 디렉터리

- `raw-data/`와 `example_data/`는 입력 데이터다.
- `scenarios/`는 야드 레이아웃과 운영 가정을 담는다.
- `src/ssi_yard/data/`는 입력 검증과 도로 경로를 담당한다.
- `src/ssi_yard/planners/`는 배정안 생성, `simulation/`은 고정 운영 규칙 실행을 담당한다.
- `src/ssi_yard/benchmark/`는 공통 기준으로 실행을 평가한다.
- `runs/`는 실행 결과, `dashboard/`는 비교와 재생 화면을 담는다.

## 웹 대시보드

MILP 결과를 날짜별 애니메이션과 면적 비례 지도에서 확인합니다. 별도 패키지 설치나 지도 API 키가 필요하지 않습니다.

```sh
python3 dashboard/serve.py
```

http://127.0.0.1:8080 에서 날짜 재생, 지도 확대·축소, 구역 이동, 블록 검색, 적치장 점유율을 확인할 수 있습니다. 시설 좌표는 원본 GPS와 면적을 보존하며 경계 간 최소 24m 간격으로 보정합니다. 자세한 데이터 해석과 검증 방법은 [대시보드 안내](dashboard/README.md)를 참고하세요.

## 그리디 기반 메타휴리스틱

MILP와 동일한 입력·제약·비용식으로 그리디 초기해를 구축하고 SA와 타부 서치로 개선합니다. 외부 패키지 없이 실행할 수 있습니다.

```sh
python3 run_meta.py --time-limit 5
python3 dashboard/serve.py
```

각 방법에 최대 5초 탐색 예산을 주며 그리디와 전처리·저장은 별도입니다. `runs/meta-heuristics/result.json`에 이번 실행의 최선 결과를 MILP와 같은 형식으로 저장하고, `greedy/`, `sa/`, `tabu/`에 방법별 결과와 실행 지표를 저장합니다. 대시보드에서 지도 전환, 비용·속도 비교, 수렴 그래프를 확인합니다. [메타휴리스틱 상세 안내](src/ssi_yard/planners/meta-heuristics/README.md).

## 구현된 알고리즘 선택·전체 실행

```sh
# MILP + Greedy/SA/Tabu 동시 실행 (기본 옵션)
python3 run_planners.py --algorithm all

# 시간 제한 지정: MILP 300초, SA/Tabu 각각 5초
python3 run_planners.py --algorithm all --milp-time-limit 300 --meta-time-limit 5

# 개별 실행
python3 run_planners.py --algorithm milp --milp-time-limit 300
python3 run_planners.py --algorithm meta --meta-time-limit 5 --seed 42
```

새 검증 결과는 `runs/milp/result.json`과 `runs/meta-heuristics/result.json`에 덮어쓰고 대시보드 데이터를 자동 갱신합니다. 실행 이력과 이전 결과 백업은 `runs/dashboard-jobs/<실행 ID>/`에 보존합니다. MILP에는 OR-Tools가 필요하며 프로젝트 `.venv/bin/python`이 있으면 자동 사용합니다. 시간 제한은 탐색 기준이며 전처리·모델 구성·저장은 별도입니다.

웹에서 실행하려면 `python3 dashboard/serve.py` 후 http://127.0.0.1:8080 상단의 **둘 다 동시 실행**, **MILP 실행**, **메타휴리스틱 실행** 버튼을 사용하세요. 기능 추가 전에 켜둔 서버는 `Ctrl+C`로 종료하고 다시 시작해야 합니다. 하단 **재생** 버튼은 계산이 아니라 결과 애니메이션입니다.
