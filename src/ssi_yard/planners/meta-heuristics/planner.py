"""Time-bounded SA and tabu search from the same feasible greedy solution."""
import math
import random
import statistics
from time import perf_counter

from .problem import EPS, Problem, State


class GreedyConstructionError(ValueError):
    """A bounded greedy construction failed; this is not an infeasibility proof."""


def plan(blocks, candidates, *, capacity, max_utilization, spacing_factor, movement_cost,
         yard_rate, tier_by_yard, threshold_by_tier, congestion_rate,
         algorithm='tabu', time_limit=5.0, max_iterations=1_000_000, seed=42):
    """MILP-compatible assignment/cost return value with optional search controls."""
    if algorithm not in {'greedy', 'sa', 'tabu'}:
        raise ValueError('algorithm must be greedy, sa or tabu')
    problem = Problem(blocks=blocks, candidates=candidates, capacity=capacity,
                      max_utilization=max_utilization, spacing_factor=spacing_factor,
                      movement_cost=movement_cost, yard_rate=yard_rate, tier_by_yard=tier_by_yard,
                      threshold_by_tier=threshold_by_tier, congestion_rate=congestion_rate)
    initial = greedy(problem)
    result = initial if algorithm == 'greedy' else search(
        problem, initial, algorithm=algorithm, time_limit=time_limit,
        max_iterations=max_iterations, seed=seed)
    return problem.assignment_dict(result['assignment']), result['cost']


def greedy(problem):
    started = perf_counter()
    p = problem
    orders = [
        sorted(range(p.n), key=lambda i: (p.starts[i], len(p.candidates[i]), -p.areas[i], p.codes[i])),
        sorted(range(p.n), key=lambda i: (len(p.candidates[i]), -p.areas[i] * (p.ends[i] - p.starts[i]), p.starts[i], p.codes[i])),
        sorted(range(p.n), key=lambda i: (-p.areas[i], len(p.candidates[i]), p.starts[i], p.codes[i])),
    ]
    failed_code = None
    for attempt, order in enumerate(orders, 1):
        state = State(p)
        for i in order:
            best_yard, best_delta = None, math.inf
            for yard in p.candidates[i]:
                # Insertion congestion is nonnegative, so base cost is a valid pruning bound.
                if p.costs[i][yard] >= best_delta:
                    break
                delta = state.insertion_delta(i, yard)
                if delta is not None and delta < best_delta:
                    best_yard, best_delta = yard, delta
            if best_yard is None:
                failed_code = p.codes[i]
                break
            state.add(i, best_yard)
            state.cost += best_delta
        else:
            state.assert_feasible()
            state.cost = state.recompute()
            return {'assignment': tuple(state.assignment), 'cost': state.cost,
                    'seconds': perf_counter() - started, 'attempts': attempt}
    raise GreedyConstructionError(f'{failed_code}: 3개 그리디 순서로 초기해 구축 실패. 문제의 불가능성을 의미하지 않습니다.')


def _proposal(state, rng, focus):
    p = state.p
    i = rng.choice(focus) if focus and rng.random() < .7 else rng.randrange(p.n)
    source = state.assignment[i]
    options = p.candidates[i]
    if len(options) < 2:
        return None
    # Usually explore the nearest-cost alternatives; retain broad diversification.
    pool = options[:min(4, len(options))] if rng.random() < .85 else options
    target = rng.choice(pool)
    if target == source:
        target = options[(options.index(target) + 1) % len(options)]
    try_swap = rng.random() < .3
    if not try_swap:
        delta = state.relocate_delta(i, target)
        if delta is not None:
            return ((i, target),), delta
    # Overlapping partners are sampled directly, avoiding O(number of blocks) scans.
    day = rng.randrange(p.starts[i], p.ends[i])
    bucket = state.members.get((target, day))
    if bucket:
        # Sort small buckets so the same seed + iteration limit is reproducible.
        partners = sorted(bucket)
        for _ in range(2):
            j = rng.choice(partners)
            delta = state.swap_delta(i, j)
            if delta is not None:
                return ((i, target), (j, source)), delta
    if try_swap:
        delta = state.relocate_delta(i, target)
        if delta is not None:
            return ((i, target),), delta
    return None


def search(problem, initial, *, algorithm='sa', time_limit=5.0, max_iterations=1_000_000,
           seed=42, neighborhood_size=48, tabu_tenure=17, initial_temperature=None):
    if algorithm not in {'sa', 'tabu'}:
        raise ValueError('algorithm must be sa or tabu')
    if not math.isfinite(time_limit) or time_limit < 0 or max_iterations < 0:
        raise ValueError('time_limit and max_iterations must be nonnegative')
    if neighborhood_size < 1 or tabu_tenure < 1:
        raise ValueError('neighborhood_size and tabu_tenure must be positive')
    if initial_temperature is not None and (not math.isfinite(initial_temperature) or initial_temperature <= 0):
        raise ValueError('initial_temperature must be finite and positive')
    started = perf_counter()
    state = State(problem, initial['assignment'])
    best_assignment, best_cost = tuple(state.assignment), state.cost
    rng = random.Random(seed)
    p = problem
    focus = [i for i, y in enumerate(state.assignment) if y != p.candidates[i][0]]
    gaps = [p.costs[i][p.candidates[i][1]] - p.costs[i][p.candidates[i][0]]
            for i in range(0, p.n, max(1, p.n // 256)) if len(p.candidates[i]) > 1]
    temperature = initial_temperature or max(1e-3, statistics.median(gaps) / 8 if gaps else 1)
    history = [{'iteration': 0, 'seconds': 0.0, 'current_cost': state.cost, 'best_cost': best_cost}]
    tabu = {}
    accepted = improvements = evaluated = iteration = 0
    last_record = started
    deadline = started + time_limit
    while p.n and iteration < max_iterations and perf_counter() < deadline and best_cost > p.lower_bound + EPS:
        # Cooling depends on iteration, not CPU timing: fixed seed + iteration
        # limit must produce the same trajectory when the deadline does not bind.
        progress = iteration / max(1, max_iterations)
        move = None
        for _ in range(1 if algorithm == 'sa' else neighborhood_size):
            # The budget also applies inside a tabu neighborhood, not just between iterations.
            if perf_counter() >= deadline:
                break
            proposal = _proposal(state, rng, focus)
            evaluated += 1
            if proposal is None:
                continue
            changes, delta = proposal
            if algorithm == 'tabu':
                forbidden = any(tabu.get((i, target), 0) > iteration for i, target in changes)
                aspiration = state.cost + delta < best_cost - EPS
                if forbidden and not aspiration:
                    continue
            if move is None or delta < move[1]:
                move = proposal
        iteration += 1
        if move is not None:
            changes, delta = move
            current_temp = temperature * (1e-4 ** min(1.0, progress))
            accept = algorithm == 'tabu' or delta <= 0 or rng.random() < math.exp(-delta / max(1e-12, current_temp))
            if accept:
                if algorithm == 'tabu':
                    expiry = iteration + tabu_tenure + rng.randrange(max(1, tabu_tenure // 3))
                    for i, _ in changes:
                        tabu[i, state.assignment[i]] = expiry
                state.apply(changes, delta)
                accepted += 1
                if state.cost < best_cost - EPS:
                    best_cost, best_assignment = state.cost, tuple(state.assignment)
                    improvements += 1
        now = perf_counter()
        if now - last_record >= .1:
            history.append({'iteration': iteration, 'seconds': now - started,
                            'current_cost': state.cost, 'best_cost': best_cost})
            last_record = now
        if algorithm == 'tabu' and iteration % 256 == 0:
            tabu = {key: expiry for key, expiry in tabu.items() if expiry > iteration}
    best = State(p, best_assignment)
    seconds = perf_counter() - started
    history.append({'iteration': iteration, 'seconds': seconds,
                    'current_cost': state.cost, 'best_cost': best.cost})
    return {'assignment': best_assignment, 'cost': best.cost, 'seconds': seconds,
            'iterations': iteration, 'evaluated_neighbors': evaluated, 'accepted_moves': accepted,
            'improvements': improvements, 'initial_temperature': temperature if algorithm == 'sa' else None,
            'stop_reason': 'relaxed_lower_bound' if best.cost <= p.lower_bound + EPS else
                           'iteration_limit' if iteration >= max_iterations else 'time_limit',
            'history': history}
