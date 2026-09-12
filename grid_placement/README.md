# Grid placement

날짜별로 재사용되는 직사각형 적치 공간을 위한 범용 Python 패키지입니다.

## 구성

- `GridYard`: 셀 크기, 입구, 영구 장애물, 날짜별 점유 상태 관리
- `FirstFitPlacer`: 입구로부터 BFS 거리순 직사각형 first-fit
- `blocking`: 표준 접근 경로의 방해 관계와 DFS 재취급 추정
- `BlockRequest`: 크기, 회전 가능 여부, 입고일과 출고일

블록의 점유 기간은 입고일과 출고일을 모두 포함합니다. 서로 기간이 겹치지
않는 블록은 같은 셀을 재사용할 수 있습니다.

## 실행

외부 라이브러리가 필요하지 않습니다.

```bash
python -m grid_placement.demo
python -m unittest discover -s grid_placement/tests -v
```

## 기본 사용법

```python
from datetime import date

from grid_placement import BlockRequest, FirstFitPlacer, GridYard

yard = GridYard(
    code="yard-1",
    width_m=100,
    depth_m=60,
    cell_size_m=2,
    entrances=((0, 0), (0, 1)),
    blocked_cells=((10, 10), (11, 10)),
)

block = BlockRequest(
    code="B001",
    length_m=12,
    width_m=8,
    height_m=5,
    inbound_date=date(2026, 1, 1),
    outbound_date=date(2026, 1, 10),
)

placement = FirstFitPlacer(yard).place(block)
print(placement.top_row, placement.left_col)
```

## 알고리즘 경계

배치 가능 여부는 블록의 직사각형 크기, 날짜 중첩, 입구 접근 가능성을
검사합니다. 방해 관계는 빈 적치장에서 계산한 표준 BFS 경로를 기준으로
추정합니다. 실제 차량 회전반경, 통로 폭, 복수 우회경로, 크레인 동선까지
정확하게 계산하는 시뮬레이터는 아닙니다.

MIP와 연결할 때는 MIP가 선택한 `assigned_yard`별로 블록을 묶고,
`FirstFitPlacer.place_many()`에 입고일 순으로 전달하면 됩니다.
