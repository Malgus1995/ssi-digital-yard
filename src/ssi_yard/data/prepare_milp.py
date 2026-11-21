from functools import cache

from ssi_yard.domain import Scenario
from ssi_yard.data.road_network import RoadNetwork


def prepare_milp_inputs(
    scenario: Scenario,
    *,
    spacing_factor: float,
    max_utilization: float,
    movement_rate_per_m: float,
) -> dict:
    if spacing_factor < 1:
        raise ValueError("spacing_factor는 1 이상이어야 합니다.")
    if not 0 < max_utilization <= 1:
        raise ValueError("max_utilization은 0 초과 1 이하여야 합니다.")
    if movement_rate_per_m < 0:
        raise ValueError("운송 단가는 0 이상이어야 합니다.")

    blocks = {
        block.code: block
        for block in scenario.blocks
    }

    # 면적이 확인된 적치장을 사용한다.
    capacity = {
        code: node.area_m2
        for code, node in scenario.nodes.items()
        if node.kind == "적치장"
        and node.area_m2 is not None
        and node.area_m2 > 0
    }

    network = RoadNetwork(scenario.roads)
    fastest_route = cache(network.fastest_route)

    candidates = {}
    movement_cost = {}

    for block_code, block in blocks.items():
        if not block.requires_yard:
            continue

        candidates[block_code] = []
        block_area = spacing_factor * block.length_m * block.width_m

        for yard_code, yard_area in capacity.items():
            # 블록 하나의 면적부터 허용 용량을 넘으면 후보에서 제외한다.
            if block_area > max_utilization * yard_area:
                continue

            inbound = fastest_route(block.inbound_factory, yard_code)
            outbound = fastest_route(yard_code, block.outbound_factory)

            if inbound is None or outbound is None:
                continue

            candidates[block_code].append(yard_code)

            distance = inbound.distance_m + outbound.distance_m
            movement_cost[block_code, yard_code] = (
                distance * movement_rate_per_m
            )

        if not candidates[block_code]:
            raise ValueError(f"{block_code}: 배정 가능한 야드가 없습니다.")

    return {
        "blocks": blocks,
        "candidates": candidates,
        "capacity": capacity,
        "movement_cost": movement_cost,
    }