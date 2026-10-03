import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from experiment.snapshots import write_snapshots


def write_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class SnapshotTests(TestCase):
    def test_departures_and_same_day_visits_have_no_end_of_day_occupancy(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            base = dict(assigned_yard='Y1', inbound_factory='F1', outbound_factory='F2', inbound_date='2026-01-01')
            write_csv(root / 'optimized_assignments.csv', [
                dict(base, block_code='STAY', outbound_date='2026-01-03'),
                dict(base, block_code='SAME', outbound_date='2026-01-01')])
            write_csv(root / 'daily_yard_utilization.csv', [dict(date='2026-01-01', yard_code='Y1', utilization='0.1')])
            nodes = root / 'nodes.csv'
            write_csv(nodes, [dict(code='Y1', object='적치장', position='A', GPS='35,128')])
            target = write_snapshots(root, nodes)
            first = json.loads((target / '2026-01-01.json').read_text())
            self.assertEqual([b['block_code'] for b in first['active_blocks']], ['STAY'])
            self.assertEqual(len(first['movements']), 3)
            last = json.loads((target / '2026-01-03.json').read_text())
            self.assertEqual(last['active_blocks'], [])
            self.assertEqual(last['movements'][0]['source'], 'Y1')
            self.assertEqual(last['movements'][0]['target'], 'F2')
            self.assertEqual(len(json.loads((target / 'index.json').read_text())['dates']), 3)
