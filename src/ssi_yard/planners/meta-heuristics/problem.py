"""Compact daily loads and exact O(stay length) relocate/swap deltas."""
import math
from collections import defaultdict

EPS = 1e-7


class Problem:
    def __init__(self, *, blocks, candidates, capacity, movement_cost, spacing_factor,
                 max_utilization, yard_rate, tier_by_yard, threshold_by_tier, congestion_rate):
        if not math.isfinite(spacing_factor) or spacing_factor < 1:
            raise ValueError('spacing_factor must be finite and >= 1')
        if not math.isfinite(max_utilization) or not 0 < max_utilization <= 1:
            raise ValueError('max_utilization must be in (0, 1]')
        required = {c for c, b in blocks.items() if b.requires_yard}
        if set(candidates) != required:
            raise ValueError('candidates must contain exactly the blocks requiring storage')
        self.codes = tuple(candidates)
        self.yards = tuple(capacity)
        self.n = len(self.codes)
        self.yard_index = {y: i for i, y in enumerate(self.yards)}
        for y in self.yards:
            tier = tier_by_yard[y]
            values = (capacity[y], yard_rate[y], threshold_by_tier[tier], congestion_rate[tier])
            if not all(math.isfinite(v) and v >= 0 for v in values) or capacity[y] <= 0:
                raise ValueError(f'{y}: invalid capacity/objective parameters')
        self.limits = tuple(capacity[y] * max_utilization for y in self.yards)
        self.thresholds = tuple(capacity[y] * threshold_by_tier[tier_by_yard[y]] for y in self.yards)
        self.rates = tuple(congestion_rate[tier_by_yard[y]] / 1000 for y in self.yards)
        origin = min((blocks[c].inbound_date.toordinal() for c in self.codes), default=0)
        self.starts = tuple(blocks[c].inbound_date.toordinal() - origin for c in self.codes)
        self.ends = tuple(blocks[c].outbound_date.toordinal() - origin for c in self.codes)
        self.days = max(self.ends, default=0)
        self.areas = tuple(spacing_factor * blocks[c].length_m * blocks[c].width_m for c in self.codes)
        if any(not math.isfinite(a) or a <= 0 for a in self.areas):
            raise ValueError('block areas must be finite and positive')
        self.costs = []
        self.candidates = []
        for i, c in enumerate(self.codes):
            costs = {}
            for y in candidates[c]:
                j = self.yard_index[y]
                movement = movement_cost[c, y]
                if not math.isfinite(movement) or movement < 0:
                    raise ValueError(f'{c}/{y}: invalid movement cost')
                costs[j] = movement + (self.ends[i] - self.starts[i]) * self.areas[i] * yard_rate[y]
            if not costs:
                raise ValueError(f'{c}: no candidate yards')
            self.costs.append(costs)
            self.candidates.append(tuple(sorted(costs, key=lambda y: (costs[y], y))))
        self.lower_bound = math.fsum(min(costs.values()) for costs in self.costs)

    def assignment_dict(self, assignment):
        return {c: self.yards[assignment[i]] for i, c in enumerate(self.codes)}


class State:
    def __init__(self, problem, assignment=None):
        self.p = p = problem
        self.assignment = [-1] * p.n
        self.loads = [[0.0] * p.days for _ in p.yards]
        self.members = defaultdict(set)
        self.cost = 0.0
        if assignment is not None:
            if len(assignment) != p.n:
                raise ValueError('assignment length mismatch')
            for i, yard in enumerate(assignment):
                if yard not in p.costs[i]:
                    raise ValueError(f'{p.codes[i]}: not a candidate')
                self.add(i, yard)
            self.cost = self.recompute()
            self.assert_feasible()

    def add(self, i, yard):
        p = self.p
        self.assignment[i] = yard
        for day in range(p.starts[i], p.ends[i]):
            self.loads[yard][day] += p.areas[i]
            self.members[yard, day].add(i)

    def recompute(self):
        p = self.p
        base = math.fsum(p.costs[i][y] for i, y in enumerate(self.assignment) if y >= 0)
        return base + math.fsum(p.rates[y] * max(0.0, load - p.thresholds[y])
                               for y, loads in enumerate(self.loads) for load in loads)

    def assert_feasible(self):
        for y, loads in enumerate(self.loads):
            if any(load > self.p.limits[y] + EPS or load < -EPS for load in loads):
                raise ValueError(f'{self.p.yards[y]}: capacity violation')

    def insertion_delta(self, i, target):
        p = self.p
        area, loads, threshold, rate = p.areas[i], self.loads[target], p.thresholds[target], p.rates[target]
        delta = p.costs[i][target]
        for day in range(p.starts[i], p.ends[i]):
            old = loads[day]
            if old + area > p.limits[target] + EPS:
                return None
            delta += rate * (max(0.0, old + area - threshold) - max(0.0, old - threshold))
        return delta

    def relocate_delta(self, i, target):
        p = self.p
        source = self.assignment[i]
        if target == source or target not in p.costs[i]:
            return None
        delta = p.costs[i][target] - p.costs[i][source]
        area, a, b = p.areas[i], self.loads[source], self.loads[target]
        ta, tb, ra, rb = p.thresholds[source], p.thresholds[target], p.rates[source], p.rates[target]
        for day in range(p.starts[i], p.ends[i]):
            av, bv = a[day], b[day]
            if bv + area > p.limits[target] + EPS:
                return None
            delta += ra * (max(0.0, av - area - ta) - max(0.0, av - ta))
            delta += rb * (max(0.0, bv + area - tb) - max(0.0, bv - tb))
        return delta

    def swap_delta(self, i, j):
        p = self.p
        source, target = self.assignment[i], self.assignment[j]
        if i == j or source == target or target not in p.costs[i] or source not in p.costs[j]:
            return None
        delta = p.costs[i][target] - p.costs[i][source] + p.costs[j][source] - p.costs[j][target]
        a, b = self.loads[source], self.loads[target]
        ta, tb, ra, rb = p.thresholds[source], p.thresholds[target], p.rates[source], p.rates[target]
        si, ei, sj, ej = p.starts[i], p.ends[i], p.starts[j], p.ends[j]
        # Both changes are evaluated simultaneously, including their non-overlapping days.
        for day in range(min(si, sj), max(ei, ej)):
            net = (p.areas[j] if sj <= day < ej else 0.0) - (p.areas[i] if si <= day < ei else 0.0)
            if not net:
                continue
            av, bv = a[day], b[day]
            if av + net > p.limits[source] + EPS or bv - net > p.limits[target] + EPS:
                return None
            delta += ra * (max(0.0, av + net - ta) - max(0.0, av - ta))
            delta += rb * (max(0.0, bv - net - tb) - max(0.0, bv - tb))
        return delta

    def apply(self, changes, delta):
        p = self.p
        # Validate deltas before calling; apply simultaneous changes without intermediate checks.
        for i, target in changes:
            source = self.assignment[i]
            area = p.areas[i]
            for day in range(p.starts[i], p.ends[i]):
                self.loads[source][day] -= area
                self.loads[target][day] += area
                self.members[source, day].discard(i)
                self.members[target, day].add(i)
            self.assignment[i] = target
        self.cost += delta
