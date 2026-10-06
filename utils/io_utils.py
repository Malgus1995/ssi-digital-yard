# io_utils.py
import math
import csv
import date
from typing import Dict, List, Tuple
from data import Block, Yard, Node, Road


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_positive_float(value: str, label: str) -> float:
    cleaned = str(value).replace(",", "").strip()
    number = float(cleaned)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be positive, got {value!r}")
    return number


def load_blocks(path: Path, limit: int) -> List[Block]:
    rows = read_csv(path)
    if limit > 0:
        rows = rows[:limit]

    blocks: List[Block] = []
    seen_codes = set()
    for row_number, row in enumerate(rows, start=2):
        code = row["block_code"].strip()
        if not code or code in seen_codes:
            raise ValueError(f"Duplicate or blank block_code at row {row_number}: {code!r}")
        seen_codes.add(code)

        inbound_date = date.fromisoformat(row["inbound_date"])
        outbound_date = date.fromisoformat(row["outbound_date"])
        if outbound_date < inbound_date:
            raise ValueError(f"{code}: outbound_date precedes inbound_date")

        blocks.append(
            Block(
                code=code,
                inbound_factory=row["inbound_factory"].strip(),
                outbound_factory=row["outbound_factory"].strip(),
                inbound_date=inbound_date,
                outbound_date=outbound_date,
                length_m=parse_positive_float(row["length_m"], f"{code}.length_m"),
                width_m=parse_positive_float(row["width_m"], f"{code}.width_m"),
                height_m=parse_positive_float(row["height_m"], f"{code}.height_m"),
            )
        )

    if not blocks:
        raise ValueError("No schedule rows were loaded")
    return blocks


def load_yards(path: Path) -> Tuple[List[Yard], List[str]]:
    yards: List[Yard] = []
    skipped: List[str] = []
    for row in read_csv(path):
        if row.get("object", "").strip() != "적치장":
            continue
        code = row["code"].strip()
        try:
            raw_area = parse_positive_float(row["area(m^2)"], f"{code}.area")
        except (TypeError, ValueError):
            # A hard capacity constraint cannot be built for values such as
            # "첨부참조".  The source row remains unchanged and is reported.
            skipped.append(code)
            continue
        yards.append(
            Yard(
                code=code,
                zone=row["position"].strip(),
                raw_area_m2=raw_area,
                usable_area_m2=raw_area,
            )
        )
    if not yards:
        raise ValueError("No yards with numeric capacity were found")
    return yards, skipped


def load_distances(path: Path) -> Dict[Tuple[str, str], float]:
    """Return distance[(yard_code, process_code)] in metres."""

    distances: Dict[Tuple[str, str], float] = {}
    for row_number, row in enumerate(read_csv(path), start=2):
        key = (row["yard_code"].strip(), row["process_code"].strip())
        if key in distances:
            raise ValueError(f"Duplicate yard/process distance at row {row_number}: {key}")
        distances[key] = parse_positive_float(
            row["l2_distance_m"], f"distance row {row_number}"
        )
    return distances




def load_problem(schedule_path, nodes_path, distances_path, roads_path):
    blocks = load_blocks(schedule_path)
    nodes = load_nodes(nodes_path)
    distances = load_distances(distances_path)
    roads = load_roads(roads_path)

    return blocks, nodes, distances, roads