"""Check the persisted layout against source geometry, not a visual impression."""
import copy
import json
import math
import unittest

from build_data import ROOT, conflicts, rows, separate_nodes


class LayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / 'dashboard/assets/data.json').read_text())
        cls.nodes = cls.data['nodes']
        cls.gap = cls.data['layout']['minimum_gap_m']

    def test_every_facility_has_required_clearance(self):
        self.assertGreaterEqual(self.gap, 24)
        for i, a in enumerate(self.nodes):
            for b in self.nodes[i + 1:]:
                self.assertFalse(conflicts(a, b, self.gap), (a['code'], b['code']))

    def test_footprints_preserve_source_area_and_gps(self):
        source = {r['code']: r for r in rows('적치장 노드 정보.csv')}
        self.assertEqual(len(source), len(self.nodes))
        for n in self.nodes:
            lat, lon = map(float, source[n['code']]['GPS'].split(','))
            self.assertEqual((n['lat'], n['lon']), (lat, lon))
            if n['area']:
                self.assertAlmostEqual(n['width'] * n['depth'], n['area'])
            self.assertAlmostEqual(n['x'] - n['original_x'], n['offset_x'])
            self.assertAlmostEqual(n['y'] - n['original_y'], n['offset_y'])

    def test_layout_is_reproducible(self):
        rebuilt = copy.deepcopy(self.nodes)
        for n in rebuilt:
            n.update(x=n['original_x'], y=n['original_y'])
        separate_nodes(rebuilt, self.gap)
        self.assertEqual(rebuilt, self.nodes)

    def test_report_matches_persisted_positions(self):
        report = json.loads((ROOT / 'dashboard/assets/layout.json').read_text())
        self.assertEqual(report['corrected_overlaps'], 0)
        original = [dict(n, x=n['original_x'], y=n['original_y']) for n in self.nodes]
        expected_pairs = sum(conflicts(a, b) for i, a in enumerate(original) for b in original[i + 1:])
        self.assertEqual(report['original_overlaps'], expected_pairs)
        positions = {n['code']: n for n in report['nodes']}
        for n in self.nodes:
            self.assertEqual((positions[n['code']]['x'], positions[n['code']]['y']), (n['x'], n['y']))
        self.assertEqual(report['moved_nodes'], sum(math.hypot(n['offset_x'], n['offset_y']) > 1e-6 for n in self.nodes))

    def test_optimization_result_is_unchanged(self):
        source = json.loads((ROOT / 'runs/milp/result.json').read_text())
        milp = next(slot['result'] for slot in self.data['slots'] if slot['id'] == 'milp')
        self.assertEqual(source, milp)


if __name__ == '__main__':
    unittest.main()
