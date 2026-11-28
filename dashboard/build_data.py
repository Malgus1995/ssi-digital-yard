"""Build the local dashboard, including a reproducible, non-overlapping layout."""

import csv
import json
import math
import re
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ssi_yard.benchmark.environment import environment_fingerprint


def rows(name):
    with (ROOT / 'raw-data' / name).open(encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def numeric(text):
    return [float(value) for value in re.findall(r'[0-9.]+', text.replace(',', ''))]


def conflicts(a, b, gap=0):
    return (abs(a['x'] - b['x']) < (a['width'] + b['width']) / 2 + gap - 1e-7
            and abs(a['y'] - b['y']) < (a['depth'] + b['depth']) / 2 + gap - 1e-7)


def separate_nodes(nodes, gap):
    """Place exact-size rectangles at the nearest available candidate boundary.

    Yards take priority. Candidates include positions outside all placed bounds,
    ensuring termination and a checked separation invariant, without random jitter.
    """
    placed = []
    order = sorted(nodes, key=lambda n: (n['kind'] != '적치장', -n['area'], n['code']))
    for node in order:
        if any(conflicts(node, other, gap) for other in placed):
            xs, ys = {node['original_x']}, {node['original_y']}
            for other in placed:
                dx = (node['width'] + other['width']) / 2 + gap
                dy = (node['depth'] + other['depth']) / 2 + gap
                xs.update((other['x'] - dx, other['x'] + dx))
                ys.update((other['y'] - dy, other['y'] + dy))
            candidates = sorted(((x - node['original_x']) ** 2 + (y - node['original_y']) ** 2, x, y)
                                for x in xs for y in ys)
            for _, x, y in candidates:
                candidate = dict(node, x=x, y=y)
                if not any(conflicts(candidate, other, gap) for other in placed):
                    node.update(x=x, y=y)
                    break
            else:
                raise ValueError(f"시설 좌표를 분리할 수 없습니다: {node['code']}")
        node['offset_x'] = node['x'] - node['original_x']
        node['offset_y'] = node['y'] - node['original_y']
        placed.append(node)
    if any(conflicts(a, b, gap) for i, a in enumerate(nodes) for b in nodes[i + 1:]):
        raise ValueError('시설 최소 간격 검증 실패')


def build():
    config = json.loads((ROOT / 'scenarios/dashboard_layout.json').read_text())
    scenario = json.loads((ROOT / 'scenarios/milp.json').read_text())
    fingerprint = environment_fingerprint(ROOT / 'raw-data', scenario)
    slots = []
    for slot in json.loads((ROOT / 'dashboard/slots.json').read_text()):
        path = ROOT / slot['path']
        raw = path.read_bytes() if path.exists() else None
        result = json.loads(raw) if raw else None
        metrics = None
        status = '실행 정보 없음'
        metrics_path = path.with_name('metrics.json')
        if raw and metrics_path.exists():
            try:
                report = json.loads(metrics_path.read_text())
                if not isinstance(report, dict):
                    raise ValueError('metrics must be an object')
                if report.get('result_sha256') != hashlib.sha256(raw).hexdigest():
                    status = '결과 변경 · 실행 정보 불일치'
                elif report.get('problem_fingerprint') != fingerprint:
                    status = '현재 환경과 다른 실행'
                elif not math.isclose(report['cost']['total'], result['total_cost'], rel_tol=1e-9, abs_tol=1e-4):
                    status = '결과 비용과 실행 정보 불일치'
                else:
                    metrics = report
                    status = '현재 환경 · 결과 검증됨'
            except (ValueError, TypeError, KeyError):
                status = '실행 정보 형식 오류'
        slots.append(dict(**slot, result=result, metrics=metrics, metrics_status=status))
    if not any(slot['result'] is not None for slot in slots):
        raise ValueError('최소 한 개 슬롯의 결과 파일이 필요합니다.')

    nodes = []
    for row in rows('적치장 노드 정보.csv'):
        lat, lon = map(float, row['GPS'].split(','))
        widths, depths, areas = numeric(row['width']), numeric(row['depth']), numeric(row['area(m^2)'])
        area = areas[0] if areas else 0
        aspect = max(widths) / max(depths) if widths and depths else 1
        width = math.sqrt(area * aspect) if area else 12
        depth = area / width if area else 12
        x = (lon - config['origin_lon']) * 111320 * math.cos(math.radians(config['origin_lat']))
        y = -(lat - config['origin_lat']) * 111320
        nodes.append(dict(code=row['code'], zone=row['code'].split('-')[0].lower(),
                          original_zone=row['position'], kind=row['object'], lat=lat, lon=lon,
                          width=width, depth=depth, area=area, x=x, y=y, original_x=x, original_y=y,
                          original_width=row['width'], original_depth=row['depth']))

    original_pairs = [[a['code'], b['code']] for i, a in enumerate(nodes) for b in nodes[i + 1:]
                      if conflicts(a, b)]
    separate_nodes(nodes, config['minimum_gap_m'])
    layout = dict(minimum_gap_m=config['minimum_gap_m'], original_overlaps=len(original_pairs),
                  corrected_overlaps=0,
                  moved_nodes=sum(math.hypot(n['offset_x'], n['offset_y']) > 1e-6 for n in nodes),
                  original_overlap_pairs=original_pairs,
                  coordinate_system='local metres; x east, y south; display layout, not surveyed GPS')
    blocks = {r['block_code']: dict(length=float(r['length_m']), width=float(r['width_m']),
              height=float(r['height_m']), start=r['inbound_date'], end=r['outbound_date'])
              for r in rows('block_schedule.csv')}
    roads = [dict(source=r['from_node'], target=r['to_node'], distance=float(r['road_distance_m']),
                  time=float(r['travel_time_min']), both=r['is_bidirectional'].lower() == 'true')
             for r in rows('virtual_road_edges.csv')]
    output = ROOT / 'dashboard/assets/data.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.tmp')
    temporary.write_text(json.dumps(dict(slots=slots, nodes=nodes, blocks=blocks, roads=roads, layout=layout,
                                     spacing_factor=scenario['spacing_factor'],
                                     environment={'problem_fingerprint': fingerprint}),
                                 ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    temporary.replace(output)
    report = dict(**layout, nodes=[{key: n[key] for key in
                  ('code', 'lat', 'lon', 'original_x', 'original_y', 'x', 'y', 'width', 'depth', 'area',
                   'offset_x', 'offset_y')} for n in nodes])
    (output.parent / 'layout.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Built {output.relative_to(ROOT)} ({output.stat().st_size:,} bytes)')
    print(f"Layout: {len(original_pairs)} overlapping pairs → 0; minimum gap {config['minimum_gap_m']} m; "
          f"{layout['moved_nodes']} facilities adjusted, GPS and areas preserved")


if __name__ == '__main__':
    build()
