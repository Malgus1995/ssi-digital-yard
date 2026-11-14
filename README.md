# SSI Digital Yard

생산 스케줄을 입력으로 휴리스틱, OR-Tools MILP, 강화학습의 야드 배정을
비교하기 위한 프로젝트다.

현재 구현 범위는 도메인과 배정 계약, CSV 검증, 최단시간 도로 경로다.
배정 알고리즘, 공통 시뮬레이터와 웹 화면은 각 디렉터리의 설계에 따라 구현한다.

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
