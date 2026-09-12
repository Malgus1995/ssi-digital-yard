"""Small executable example for the grid-placement package."""

from datetime import date

from grid_placement import BlockRequest, FirstFitPlacer, GridYard, blocking_report


def main() -> None:
    yard = GridYard(
        code="demo-yard",
        width_m=18,
        depth_m=14,
        cell_size_m=2,
        entrances=((0, 0), (0, 1)),
        blocked_cells=((3, 4), (4, 4), (5, 4)),
    )
    blocks = [
        BlockRequest("B01", 4, 4, 3, date(2026, 1, 1), date(2026, 1, 6)),
        BlockRequest("B02", 6, 4, 3, date(2026, 1, 2), date(2026, 1, 4)),
        BlockRequest("B03", 4, 6, 3, date(2026, 1, 3), date(2026, 1, 8)),
    ]

    placed, failures = FirstFitPlacer(yard).place_many(blocks)
    for placement in placed:
        print(
            placement.block_code,
            (placement.top_row, placement.left_col),
            f"{placement.row_span}x{placement.col_span}",
            f"rehandles={placement.estimated_rehandles}",
        )
    if failures:
        print("failures:", failures)

    view_date = date(2026, 1, 3)
    print(f"\n{view_date} utilization={yard.utilization(view_date):.1%}")
    print(yard.render_ascii(view_date))
    print(blocking_report(yard, view_date))


if __name__ == "__main__":
    main()
