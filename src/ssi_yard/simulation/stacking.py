from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

Cell = tuple[int, int]
SearchOrder = Literal["bfs", "dfs"]


@dataclass(frozen=True)
class Placement:
    block_code: str
    row: int
    col: int
    rows: int
    cols: int
    rotated: bool

    def cells(self) -> Iterator[Cell]:
        for row in range(self.row, self.row + self.rows):
            for col in range(self.col, self.col + self.cols):
                yield row, col


@dataclass(frozen=True)
class YardMove:
    block_code: str
    action: Literal["to_buffer", "outbound", "restack"]
    source: Placement | None
    target: Placement | None


class YardGrid:
    """블록을 직사각형으로 배치하는 야드 바닥 격자."""

    def __init__(
        self,
        rows: int,
        cols: int,
        entrance: Cell = (0, 0),
    ) -> None:
        if rows <= 0 or cols <= 0:
            raise ValueError("격자 크기는 1 이상이어야 합니다.")

        self.rows = rows
        self.cols = cols
        self.entrance = entrance
        if not self._inside(entrance):
            raise ValueError("출입구가 격자 밖에 있습니다.")

        self._occupied: dict[Cell, str] = {}
        self._placements: dict[str, Placement] = {}

    def place(
        self,
        block_code: str,
        length_cells: int,
        width_cells: int,
        *,
        order: SearchOrder = "bfs",
        allow_rotation: bool = True,
        fill_from_back: bool = False,
    ) -> Placement | None:
        """처음 맞는 위치를 점유한다. 안쪽 우선은 BFS 거리 역순이다."""
        if order not in ("bfs", "dfs"):
            raise ValueError(f"지원하지 않는 탐색 순서입니다: {order}")
        if block_code in self._placements:
            raise ValueError(f"이미 적치된 블록입니다: {block_code}")
        if length_cells <= 0 or width_cells <= 0:
            raise ValueError("블록 치수는 1셀 이상이어야 합니다.")

        # 길이는 행 방향, 폭은 열 방향으로 놓는다.
        orientations = [(length_cells, width_cells, False)]
        if allow_rotation and length_cells != width_cells:
            orientations.append((width_cells, length_cells, True))

        candidates = (
            reversed(list(self._candidate_cells("bfs")))
            if fill_from_back
            else self._candidate_cells(order)
        )
        for row, col in candidates:
            for rows, cols, rotated in orientations:
                candidate = Placement(block_code, row, col, rows, cols, rotated)
                if self._fits(candidate):
                    return self._occupy(candidate)

        return None

    def remove(self, block_code: str) -> Placement:
        """블록이 점유한 셀을 해제한다. 미등록 블록은 KeyError를 발생시킨다."""
        placement = self._placements.pop(block_code)
        for cell in placement.cells():
            del self._occupied[cell]
        return placement

    def retrieve(
        self,
        block_code: str,
        *,
        order: SearchOrder = "bfs",
        allow_rotation: bool = True,
    ) -> list[YardMove] | None:
        """막는 블록을 임시 이동하고, 목표 블록을 출고한 뒤 재적치한다."""
        if order not in ("bfs", "dfs"):
            raise ValueError(f"지원하지 않는 탐색 순서입니다: {order}")

        target = self._placements[block_code]
        blockers = self._blocking_blocks(target, order)

        # 재적치에 실패하면 출고 시도 전 상태로 복구한다.
        occupied_before = self._occupied.copy()
        placements_before = self._placements.copy()
        moves: list[YardMove] = []
        buffered: list[Placement] = []

        for code in blockers:
            old = self.remove(code)
            buffered.append(old)
            moves.append(YardMove(code, "to_buffer", source=old, target=None))

        outbound = self.remove(block_code)
        moves.append(YardMove(block_code, "outbound", source=outbound, target=None))

        # 출구에서 먼 쪽의 블록부터 다시 넣는다.
        for old in reversed(buffered):
            new = self._restack(old, outbound, order, allow_rotation)
            if new is None:
                self._occupied = occupied_before
                self._placements = placements_before
                return None

            moves.append(YardMove(old.block_code, "restack", source=None, target=new))

        return moves

    def _blocking_blocks(
        self,
        target: Placement,
        order: SearchOrder,
    ) -> list[str]:
        """빈 경로를 먼저 확인하고, 필요하면 경로 위 블록을 출구 순서로 반환한다."""
        target_cells = set(target.cells())

        for pass_occupied in (False, True):
            pending = deque([(self.entrance, ())])
            visited: set[Cell] = set()

            while pending:
                cell, blockers = (
                    pending.popleft() if order == "bfs" else pending.pop()
                )
                if cell in visited:
                    continue
                visited.add(cell)

                if cell in target_cells:
                    return list(blockers)

                owner = self._occupied.get(cell)
                if owner is not None:
                    if not pass_occupied:
                        continue
                    if owner not in blockers:
                        blockers = (*blockers, owner)

                row, col = cell
                neighbors = [
                    (row, col + 1),
                    (row + 1, col),
                    (row, col - 1),
                    (row - 1, col),
                ]
                if order == "dfs":
                    neighbors.reverse()

                for neighbor in neighbors:
                    if self._inside(neighbor) and neighbor not in visited:
                        pending.append((neighbor, blockers))

        raise RuntimeError(f"출고 경로를 찾을 수 없습니다. {target.block_code}")

    def _restack(
        self,
        old: Placement,
        outbound: Placement,
        order: SearchOrder,
        allow_rotation: bool,
    ) -> Placement | None:
        # 임시 이동 전 방향으로 출고 블록의 시작 좌표에 먼저 넣어 본다.
        preferred = Placement(
            old.block_code, outbound.row, outbound.col,
            old.rows, old.cols, old.rotated,
        )
        reachable = any(
            cell == (preferred.row, preferred.col)
            for cell in self._candidate_cells(order)
        )
        if reachable:
            if self._fits(preferred):
                return self._occupy(preferred)

            if allow_rotation and old.rows != old.cols:
                rotated = Placement(
                    old.block_code, outbound.row, outbound.col,
                    old.cols, old.rows, not old.rotated,
                )
                if self._fits(rotated):
                    return self._occupy(rotated)

        # 대체 위치에서도 임시 이동 전 방향을 먼저 시도한다.
        for row, col in self._candidate_cells(order):
            candidate = Placement(old.block_code, row, col, old.rows, old.cols, old.rotated)
            if self._fits(candidate):
                return self._occupy(candidate)
            if allow_rotation and old.rows != old.cols:
                candidate = Placement(
                    old.block_code, row, col, old.cols, old.rows, not old.rotated,
                )
                if self._fits(candidate):
                    return self._occupy(candidate)
        return None

    def _occupy(self, placement: Placement) -> Placement:
        for cell in placement.cells():
            self._occupied[cell] = placement.block_code
        self._placements[placement.block_code] = placement
        return placement

    def placements(self) -> tuple[Placement, ...]:
        """시뮬레이터와 대시보드가 읽을 현재 배치다."""
        return tuple(self._placements.values())

    def _candidate_cells(self, order: SearchOrder) -> Iterator[Cell]:
        if order not in ("bfs", "dfs"):
            raise ValueError(f"지원하지 않는 탐색 순서입니다: {order}")

        pending = deque([self.entrance])
        visited: set[Cell] = set()

        while pending:
            cell = pending.popleft() if order == "bfs" else pending.pop()
            if cell in visited:
                continue
            visited.add(cell)

            if cell != self.entrance:
                yield cell

            neighbors = self._empty_neighbors(cell)
            # DFS 스택에서도 오른쪽, 아래, 왼쪽, 위 순서로 방문한다.
            pending.extend(neighbors if order == "bfs" else reversed(neighbors))

    def _empty_neighbors(self, cell: Cell) -> list[Cell]:
        row, col = cell
        neighbors = [
            (row, col + 1),
            (row + 1, col),
            (row, col - 1),
            (row - 1, col),
        ]
        return [
            neighbor
            for neighbor in neighbors
            if self._inside(neighbor) and neighbor not in self._occupied
        ]

    def _fits(self, placement: Placement) -> bool:
        if (
            placement.row + placement.rows > self.rows
            or placement.col + placement.cols > self.cols
        ):
            return False

        return all(
            cell != self.entrance and cell not in self._occupied
            for cell in placement.cells()
        )

    def _inside(self, cell: Cell) -> bool:
        row, col = cell
        return 0 <= row < self.rows and 0 <= col < self.cols