"""Independent evaluation of the exact MILP assignment objective and constraints."""
import math
from collections import defaultdict


def evaluate_assignment(assignment, *, blocks, candidates, capacity, movement_cost,
                        spacing_factor, max_utilization, yard_rate, tier_by_yard,
                        threshold_by_tier, congestion_rate):
    if set(assignment) != set(candidates):
        raise ValueError('배정 대상이 일치하지 않습니다 (누락/초과 블록).')
    loads = defaultdict(float)
    movement = 0.0
    for code, yard in assignment.items():
        if yard not in candidates[code]:
            raise ValueError(f'{code}: 후보가 아닌 적치장 {yard}')
        block = blocks[code]
        area = spacing_factor * block.length_m * block.width_m
        movement += movement_cost[code, yard]
        for day in range(block.inbound_date.toordinal(), block.outbound_date.toordinal()):
            loads[yard, day] += area
    occupancy = congestion = peak = 0.0
    for (yard, day), load in loads.items():
        limit = capacity[yard] * max_utilization
        if load > limit + max(1e-6, limit * 1e-10):
            raise ValueError(f'{yard}: 일자 {day} 용량 초과 ({load:.6f} > {limit:.6f})')
        peak = max(peak, load / capacity[yard])
        tier = tier_by_yard[yard]
        occupancy += yard_rate[yard] * load
        congestion += congestion_rate[tier] / 1000 * max(0.0, load - threshold_by_tier[tier] * capacity[yard])
    total = math.fsum((movement, occupancy, congestion))
    if not math.isfinite(total):
        raise ValueError('목적함수는 유한한 숫자여야 합니다.')
    return {'cost': {'movement': movement, 'occupancy': occupancy, 'congestion': congestion, 'total': total},
            'feasibility': {'valid': True, 'assigned_blocks': len(assignment),
                            'max_utilization': peak, 'violating_yard_days': 0}}
