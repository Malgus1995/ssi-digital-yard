"""End-to-end contract test on small real CSV inputs, without OR-Tools."""
import contextlib
import csv
import importlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
run = importlib.import_module('ssi_yard.planners.meta-heuristics.run')


class CLITests(unittest.TestCase):
    def test_all_methods_and_best_write_milp_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def write(name, headers, values):
                with (root / name).open('w', encoding='utf-8', newline='') as stream:
                    writer = csv.writer(stream); writer.writerow(headers); writer.writerows(values)
            write('적치장 노드 정보.csv', ['code', 'position', 'object', 'GPS', 'area(m^2)'], [
                ('f', 'test', '도장공장', '34.87,128.69', ''), ('g', 'test', '의장공장', '34.88,128.70', ''),
                ('x', 'test', '적치장', '34.87,128.70', '20'), ('y', 'test', '적치장', '34.88,128.69', '30')])
            write('block_schedule.csv', ['block_code', 'inbound_factory', 'outbound_factory', 'inbound_date', 'outbound_date', 'length_m', 'width_m', 'height_m'], [
                ('a', 'f', 'g', '2026-01-01', '2026-01-03', 3, 2, 1),
                ('b', 'f', 'g', '2026-01-02', '2026-01-04', 2, 2, 1),
                ('direct', 'f', 'g', '2026-01-01', '2026-01-01', 1, 1, 1)])
            write('virtual_road_edges.csv', ['road_id', 'from_node', 'to_node', 'road_distance_m', 'travel_time_min', 'is_bidirectional'], [
                ('r1', 'f', 'x', 10, 1, 'true'), ('r2', 'x', 'g', 20, 1, 'true'),
                ('r3', 'f', 'y', 20, 1, 'true'), ('r4', 'y', 'g', 30, 1, 'true')])
            write('yard_process_distances.csv', ['yard_code', 'process_code', 'l2_distance_m', 'baseline_travel_time_min'], [])
            config = dict(spacing_factor=1.15, max_utilization=.95, movement_rate_per_m=1,
                          default_yard_rate=.001, default_tier=1,
                          threshold_by_tier={'1': .5}, congestion_rate={'1': 2}, yard_overrides={})
            config_path = root / 'config.json'; config_path.write_text(json.dumps(config))
            output = root / 'output'
            with contextlib.redirect_stdout(io.StringIO()):
                run.main(['--data-dir', str(root), '--config', str(config_path), '--output-dir', str(output),
                          '--baseline', str(root / 'missing.json'), '--time-limit', '0'])
            best = json.loads((output / 'result.json').read_text())
            comparison = json.loads((output / 'comparison.json').read_text())
            self.assertEqual(set(best), {'assignment', 'daily_moves', 'total_cost'})
            self.assertEqual(set(best['assignment']), {'a', 'b'})
            self.assertEqual(sum(len(m) for m in best['daily_moves'].values()), 5)
            for method in ('greedy', 'sa', 'tabu'):
                result = json.loads((output / method / 'result.json').read_text())
                metrics = json.loads((output / method / 'metrics.json').read_text())
                self.assertEqual(set(result), set(best))
                self.assertTrue(metrics['feasibility']['valid'])
                self.assertEqual(metrics['cost']['total'], result['total_cost'])
                self.assertEqual(metrics['problem_fingerprint'], comparison['problem_fingerprint'])
            self.assertEqual(best['total_cost'], min(m['total_cost'] for m in comparison['methods'].values()))


if __name__ == '__main__':
    unittest.main()
