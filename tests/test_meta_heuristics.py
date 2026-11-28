import importlib
import itertools
import json
import math
import random
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
meta = importlib.import_module('ssi_yard.planners.meta-heuristics')
planner = importlib.import_module('ssi_yard.planners.meta-heuristics.planner')
from ssi_yard.benchmark.environment import save_metrics
from ssi_yard.benchmark.evaluation import evaluate_assignment
from ssi_yard.benchmark.results import create_daily_moves, save_result
from ssi_yard.domain import Block


def fixture():
    origin = date(2026, 1, 1)
    blocks = {
        'a': Block('a', 'factory1', 'factory2', origin, origin + timedelta(days=3), 3, 2, 1),
        'b': Block('b', 'factory1', 'factory2', origin + timedelta(days=1), origin + timedelta(days=4), 2, 2, 1),
        'c': Block('c', 'factory1', 'factory2', origin + timedelta(days=3), origin + timedelta(days=5), 3, 1, 1),
        'direct': Block('direct', 'factory1', 'factory2', origin, origin, 1, 1, 1),
    }
    return dict(blocks=blocks, candidates={c: ['x', 'y', 'z'] for c in ('a', 'b', 'c')},
                capacity={'x': 12., 'y': 14., 'z': 20.}, movement_cost={
                    (c, y): float(v) for c, vals in [('a', (1, 5, 9)), ('b', (2, 4, 8)), ('c', (3, 2, 10))]
                    for y, v in zip(('x', 'y', 'z'), vals)},
                spacing_factor=1.15, max_utilization=.95,
                yard_rate={'x': .1, 'y': .3, 'z': .05}, tier_by_yard={'x': 1, 'y': 2, 'z': 3},
                threshold_by_tier={1: .25, 2: .35, 3: .5}, congestion_rate={1: 20., 2: 50., 3: 100.})


class MetaHeuristicTests(unittest.TestCase):
    def setUp(self):
        self.params = fixture()
        self.p = meta.Problem(**self.params)
        self.initial = meta.greedy(self.p)

    def evaluate(self, assignment):
        return evaluate_assignment(self.p.assignment_dict(assignment), **self.params)['cost']['total']

    def test_exact_objective_and_every_feasible_delta(self):
        for assignment in itertools.product(range(3), repeat=3):
            try:
                state = meta.State(self.p, assignment)
            except ValueError:
                continue
            self.assertAlmostEqual(state.cost, self.evaluate(assignment), places=9)
            for i in range(3):
                for target in range(3):
                    delta = state.relocate_delta(i, target)
                    proposed = list(assignment); proposed[i] = target
                    if target == assignment[i]:
                        self.assertIsNone(delta); continue
                    try:
                        total = self.evaluate(proposed)
                    except ValueError:
                        self.assertIsNone(delta); continue
                    self.assertIsNotNone(delta)
                    self.assertAlmostEqual(delta, total - state.cost, places=9)
                    applied = meta.State(self.p, assignment)
                    applied.apply(((i, target),), delta)
                    self.assertAlmostEqual(applied.recompute(), total, places=9)
                    applied.assert_feasible()
                for j in range(i + 1, 3):
                    delta = state.swap_delta(i, j)
                    proposed = list(assignment); proposed[i], proposed[j] = assignment[j], assignment[i]
                    if assignment[i] == assignment[j]:
                        self.assertIsNone(delta); continue
                    try:
                        total = self.evaluate(proposed)
                    except ValueError:
                        self.assertIsNone(delta); continue
                    self.assertIsNotNone(delta)
                    self.assertAlmostEqual(delta, total - state.cost, places=9)
                    applied = meta.State(self.p, assignment)
                    applied.apply(((i, assignment[j]), (j, assignment[i])), delta)
                    self.assertAlmostEqual(applied.recompute(), total, places=9)
                    for (yard, day), members in applied.members.items():
                        expected = {k for k, y in enumerate(proposed) if y == yard and self.p.starts[k] <= day < self.p.ends[k]}
                        self.assertEqual(members, expected)

    def test_swap_can_unlock_capacity_when_relocates_cannot(self):
        params = fixture()
        origin = date(2026, 1, 1)
        params['blocks'] = {c: Block(c, 'f', 'g', origin, origin + timedelta(days=2), 5, 1, 1) for c in ('a', 'b')}
        params['candidates'] = {c: ['x', 'y'] for c in ('a', 'b')}
        params['capacity'] = {'x': 6.1, 'y': 6.1}
        params['movement_cost'] = {('a', 'x'): 10., ('a', 'y'): 1., ('b', 'x'): 1., ('b', 'y'): 10.}
        p = meta.Problem(**params); state = meta.State(p, (0, 1))
        self.assertIsNone(state.relocate_delta(0, 1)); self.assertIsNone(state.relocate_delta(1, 0))
        delta = state.swap_delta(0, 1)
        self.assertLess(delta, 0)
        state.apply(((0, 1), (1, 0)), delta); state.assert_feasible()
        for method in ('sa', 'tabu'):
            result = meta.search(p, {'assignment': (0, 1)}, algorithm=method, seed=1, time_limit=1, max_iterations=100)
            self.assertEqual(result['assignment'], (1, 0))

    def test_half_open_inventory_and_direct_moves(self):
        assignment = self.p.assignment_dict(self.initial['assignment'])
        self.assertNotIn('direct', assignment)
        moves = create_daily_moves(self.params['blocks'], assignment)
        self.assertEqual(moves['2026-01-01'][-1]['action'], '직행')
        self.assertEqual(self.p.ends[0], self.p.starts[2])
        self.assertNotIn(0, meta.State(self.p, self.initial['assignment']).members.get((self.initial['assignment'][0], 3), set()))

    def test_reproducible_seed_best_retention_and_monotone_history(self):
        for method in ('sa', 'tabu'):
            options = dict(algorithm=method, seed=7, time_limit=10, max_iterations=200)
            a, b = meta.search(self.p, self.initial, **options), meta.search(self.p, self.initial, **options)
            self.assertEqual(a['assignment'], b['assignment'])
            self.assertLessEqual(a['cost'], self.initial['cost'] + 1e-7)
            self.assertAlmostEqual(a['cost'], self.evaluate(a['assignment']))
            self.assertTrue(all(x['best_cost'] >= y['best_cost'] - 1e-7 for x, y in zip(a['history'], a['history'][1:])))

    def test_zero_budget_returns_valid_greedy(self):
        for method in ('sa', 'tabu'):
            result = meta.search(self.p, self.initial, algorithm=method, time_limit=0)
            self.assertEqual(result['iterations'], 0)
            self.assertEqual(result['assignment'], self.initial['assignment'])

    def test_iteration_limited_sa_is_independent_of_cpu_clock(self):
        results = []
        for tick in (1e-6, 1e-2):
            counter = itertools.count()
            with patch.object(planner, 'perf_counter', side_effect=lambda: next(counter) * tick):
                results.append(meta.search(self.p, self.initial, algorithm='sa', time_limit=1000,
                                           max_iterations=500, seed=17))
        for key in ('assignment', 'cost', 'accepted_moves', 'iterations', 'improvements'):
            self.assertEqual(results[0][key], results[1][key])

    def test_missing_candidates_bad_parameters_and_failed_greedy(self):
        params = fixture(); params['candidates'].pop('a')
        with self.assertRaises(ValueError): meta.Problem(**params)
        for limit in (-1, math.nan, math.inf):
            with self.assertRaises(ValueError): meta.search(self.p, self.initial, time_limit=limit)
        params = fixture(); params['capacity'] = {y: 1 for y in params['capacity']}
        with self.assertRaises(planner.GreedyConstructionError): meta.greedy(meta.Problem(**params))

    def test_greedy_failure_retries_alternative_orders(self):
        params = fixture()
        origin = date(2026, 1, 1)
        params['blocks'] = {
            'a': Block('a', 'f', 'g', origin, origin + timedelta(days=3), 3, 1, 1),
            'b': Block('b', 'f', 'g', origin + timedelta(days=1), origin + timedelta(days=2), 5, 1, 1)}
        params['candidates'] = {'a': ['x', 'y'], 'b': ['x']}
        params['capacity'] = {'x': 6.1, 'y': 6.1}
        params['movement_cost'] = {('a', 'x'): 1, ('a', 'y'): 5, ('b', 'x'): 1}
        result = meta.greedy(meta.Problem(**params))
        self.assertEqual(result['attempts'], 2)
        self.assertEqual(result['assignment'], (1, 0))

    def test_empty_waiting_inventory(self):
        params = fixture(); params['blocks'] = {'direct': params['blocks']['direct']}; params['candidates'] = {}; params['movement_cost'] = {}
        p = meta.Problem(**params); initial = meta.greedy(p)
        self.assertEqual(initial['cost'], 0)
        self.assertEqual(meta.search(p, initial)['cost'], 0)

    def test_result_has_exact_milp_schema_and_separate_metrics(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'result.json'
            assignment = self.p.assignment_dict(self.initial['assignment'])
            save_result(path, assignment, create_daily_moves(self.params['blocks'], assignment), self.initial['cost'])
            metrics = save_metrics(path, {'algorithm': 'Greedy', 'timing': {'solver_seconds': .1}})
            self.assertEqual(set(json.loads(path.read_text())), {'assignment', 'daily_moves', 'total_cost'})
            self.assertEqual(json.loads(path.with_name('metrics.json').read_text())['result_sha256'], metrics['result_sha256'])

    def test_objective_matches_original_milp_model(self):
        try:
            from ssi_yard.planners.milp import model
        except ImportError:
            self.skipTest('OR-Tools not installed; independent exhaustive evaluator tests still run')
        solver = model.create_solver()
        x = model.create_assignment_variables(solver, self.params['candidates'])
        model.add_assignment_constraints(solver, self.params['candidates'], x)
        loads = model.add_capacity_constraints(solver, self.params['blocks'], x,
                   {y: a * self.params['max_utilization'] for y, a in self.params['capacity'].items()}, self.params['spacing_factor'])
        excess = model.add_congestion_constraints(solver, loads, self.params['capacity'], self.params['tier_by_yard'], self.params['threshold_by_tier'])
        model.set_objective(solver, x, loads, excess, self.params['movement_cost'], self.params['yard_rate'], self.params['tier_by_yard'], self.params['congestion_rate'])
        self.assertEqual(solver.Solve(), solver.OPTIMAL)
        exact = min(self.evaluate(a) for a in itertools.product(range(3), repeat=3)
                    if self._feasible(a))
        self.assertAlmostEqual(exact, solver.Objective().Value(), places=8)
        from ssi_yard.planners.milp.planner import solve_assignment
        diagnostics = {}
        self.assertIsNotNone(solve_assignment(solver, x, time_limit_ms=1000, diagnostics=diagnostics))
        self.assertEqual(diagnostics['termination_status'], 'OPTIMAL')
        self.assertTrue(diagnostics['optimality_proven'])
        self.assertTrue(diagnostics['solution_verified'])
        self.assertAlmostEqual(diagnostics['best_bound'], solver.Objective().Value(), places=7)
        self.assertAlmostEqual(diagnostics['relative_gap'], 0., places=7)

    def _feasible(self, assignment):
        try: self.evaluate(assignment); return True
        except ValueError: return False


if __name__ == '__main__':
    unittest.main()
