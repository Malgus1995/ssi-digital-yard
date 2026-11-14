import csv
from datetime import date
from pathlib import Path
from unicodedata import normalize

from ssi_yard.domain import Baseline, Block, Node, Road, Scenario


def _rows(directory: Path, name: str):
    matches = [path for path in directory.iterdir() if normalize("NFC", path.name) == name]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {name} in {directory}")
    with matches[0].open(encoding="utf-8-sig", newline="") as source:
        yield from csv.DictReader(source)


def _unique(records, key):
    indexed = {}
    for record in records:
        identifier = key(record)
        if identifier in indexed:
            raise ValueError(f"duplicate key {identifier}")
        indexed[identifier] = record
    return indexed


def _node(row):
    lat, lon = map(float, row["GPS"].split(","))
    return Node(row["code"], row["position"], row["object"], lat, lon,
                float(row["area(m^2)"].replace(",", "")) if row["area(m^2)"].strip() not in {"", "첨부참조"} else None)


def _block(row):
    return Block(
        row["block_code"], row["inbound_factory"], row["outbound_factory"],
        date.fromisoformat(row["inbound_date"]), date.fromisoformat(row["outbound_date"]),
        float(row["length_m"]), float(row["width_m"]), float(row["height_m"]),
    )


def _road(row):
    return Road(row["road_id"], row["from_node"], row["to_node"],
                float(row["road_distance_m"]), float(row["travel_time_min"]),
                {"true": True, "false": False}[row["is_bidirectional"].lower()])


def _baseline(row):
    return Baseline(row["yard_code"], row["process_code"], float(row["l2_distance_m"]),
                    float(row["baseline_travel_time_min"]))


def load_scenario(directory: Path) -> Scenario:
    nodes = _unique(map(_node, _rows(directory, "적치장 노드 정보.csv")), lambda node: node.code)
    blocks = _unique(map(_block, _rows(directory, "block_schedule.csv")), lambda block: block.code)
    roads = _unique(map(_road, _rows(directory, "virtual_road_edges.csv")), lambda road: road.code)
    baselines = _unique(map(_baseline, _rows(directory, "yard_process_distances.csv")),
                        lambda item: (item.yard, item.factory))
    yards = {code for code, node in nodes.items() if node.kind == "적치장"}
    factories = nodes.keys() - yards
    for block in blocks.values():
        if {block.inbound_factory, block.outbound_factory} - factories:
            raise ValueError(f"{block.code}: unknown factory")
        if block.outbound_date < block.inbound_date or min(block.length_m, block.width_m, block.height_m) <= 0:
            raise ValueError(f"{block.code}: invalid schedule or dimensions")
    for road in roads.values():
        if {road.source, road.target} - nodes.keys() or min(road.distance_m, road.duration_min) < 0:
            raise ValueError(f"{road.code}: invalid road")
    for yard, factory in baselines:
        if yard not in yards or factory not in factories:
            raise ValueError(f"invalid baseline endpoints {yard}, {factory}")
    return Scenario(tuple(blocks.values()), nodes, tuple(roads.values()), baselines)
