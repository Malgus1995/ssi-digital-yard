"""Persist daily yard states and scheduled movement events for the local viewer."""
from __future__ import annotations
import argparse
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from .cost import read_csv


def write_snapshots(output_dir: Path, nodes_path: Path) -> Path:
    blocks = read_csv(output_dir / 'optimized_assignments.csv')
    utilization = read_csv(output_dir / 'daily_yard_utilization.csv')
    if not blocks:
        raise ValueError('No assignments available')
    nodes = []
    for row in read_csv(nodes_path):
        try:
            lat, lon = map(float, row['GPS'].split(','))
        except (ValueError, KeyError):
            lat = lon = None
        nodes.append(dict(code=row['code'], kind=row['object'], zone=row['position'], lat=lat, lon=lon))
    arrivals, departures, loads = defaultdict(list), defaultdict(list), defaultdict(list)
    for block in blocks:
        arrivals[block['inbound_date']].append(block)
        departures[block['outbound_date']].append(block)
    for row in utilization:
        loads[row['date']].append(row)
    start = min(date.fromisoformat(b['inbound_date']) for b in blocks)
    end = max(date.fromisoformat(b['outbound_date']) for b in blocks)
    target = output_dir / 'snapshots'
    target.mkdir(exist_ok=True)
    active, dates = {}, []
    day = start
    while day <= end:
        key = day.isoformat()
        incoming, outgoing = arrivals[key], departures[key]
        for block in incoming:
            if block['inbound_date'] < block['outbound_date']:
                active[block['block_code']] = block
        for block in outgoing:
            active.pop(block['block_code'], None)
        movements = []
        for kind, items in [('inbound', incoming), ('outbound', outgoing)]:
            for block in items:
                yard = block['assigned_yard']
                if not yard:
                    continue
                movements.append(dict(block_code=block['block_code'], kind=kind,
                    source=block['inbound_factory'] if kind == 'inbound' else yard,
                    target=yard if kind == 'inbound' else block['outbound_factory'], yard=yard))
        snapshot = dict(date=key, active_blocks=list(active.values()), movements=movements,
                        yards=loads[key], inbound_count=len(incoming), outbound_count=len(outgoing))
        (target / f'{key}.json').write_text(json.dumps(snapshot, ensure_ascii=False), encoding='utf-8')
        dates.append(key)
        day += timedelta(days=1)
    (target / 'index.json').write_text(json.dumps(dict(dates=dates, nodes=nodes, block_count=len(blocks),
        occupancy='inbound_date <= day < outbound_date', movement_basis='scheduled dates; no intraday order'), ensure_ascii=False), encoding='utf-8')
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--nodes', type=Path, required=True)
    args = parser.parse_args()
    print(write_snapshots(args.output_dir, args.nodes))
