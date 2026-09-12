from datetime import date
from unittest import TestCase

from grid_placement.blocking import build_blocking_graph, dfs_blockers
from grid_placement.first_fit import FirstFitPlacer
from grid_placement.grid import GridYard
from grid_placement.models import BlockRequest, Placement


class GridPlacementTests(TestCase):
    def test_first_fit_uses_nearest_available_rectangle(self) -> None:
        yard = GridYard("Y1", width_m=8, depth_m=8, cell_size_m=2)
        block = BlockRequest(
            "B1", 2, 2, 2, date(2026, 1, 1), date(2026, 1, 3)
        )
        placement = FirstFitPlacer(yard).place(block)

        self.assertEqual((placement.top_row, placement.left_col), (0, 1))
        self.assertEqual(placement.access_distance, 1)
        self.assertAlmostEqual(yard.utilization(date(2026, 1, 2)), 1 / 15)

    def test_same_cells_can_be_reused_after_departure(self) -> None:
        yard = GridYard("Y1", width_m=8, depth_m=8, cell_size_m=2)
        placer = FirstFitPlacer(yard)
        first = placer.place(
            BlockRequest("B1", 2, 2, 2, date(2026, 1, 1), date(2026, 1, 2))
        )
        second = placer.place(
            BlockRequest("B2", 2, 2, 2, date(2026, 1, 3), date(2026, 1, 4))
        )

        self.assertEqual(first.cells, second.cells)

    def test_rotation_allows_a_block_to_fit(self) -> None:
        yard = GridYard(
            "Y1",
            width_m=4,
            depth_m=6,
            cell_size_m=2,
            entrances=((0, 0),),
            blocked_cells=((1, 0), (2, 0)),
        )
        block = BlockRequest(
            "B1", 2, 4, 2, date(2026, 1, 1), date(2026, 1, 2)
        )
        placement = FirstFitPlacer(yard).place(block)

        self.assertTrue(placement.rotated)
        self.assertEqual((placement.row_span, placement.col_span), (2, 1))

    def test_dfs_follows_a_blocker_chain(self) -> None:
        yard = GridYard("Y1", width_m=2, depth_m=10, cell_size_m=2)
        active = (date(2026, 1, 1), date(2026, 1, 10))

        def make_placement(code: str, row: int) -> Placement:
            block = BlockRequest(code, 2, 2, 2, *active)
            cells = ((row, 0),)
            path = tuple((path_row, 0) for path_row in range(row + 1))
            return Placement(
                block=block,
                top_row=row,
                left_col=0,
                row_span=1,
                col_span=1,
                rotated=False,
                cells=cells,
                access_path=path,
                access_distance=row,
            )

        for placement in (
            make_placement("C", 1),
            make_placement("B", 2),
            make_placement("A", 3),
        ):
            yard.add_placement(placement)

        graph = build_blocking_graph(yard, date(2026, 1, 5))
        self.assertEqual(graph["A"], {"B"})
        self.assertEqual(graph["B"], {"C"})
        self.assertEqual(dfs_blockers(graph, "A"), {"B", "C"})
