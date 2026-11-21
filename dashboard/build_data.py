"""Rebuild dashboard data from the MILP result and its source dimensions."""
import csv
import json
import re
import math
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def rows(name):
    with (ROOT / 'raw-data' / name).open(encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))
slot_config = json.loads((ROOT / 'dashboard/slots.json').read_text())
slots = []
for slot in slot_config:
    path = ROOT / slot['path']
    slots.append(dict(**slot, result=json.loads(path.read_text()) if path.exists() else None))
result = next((s['result'] for s in slots if s['result'] is not None), None)
if result is None:
    raise ValueError('최소 한 개 슬롯의 결과 파일이 필요합니다.')
nodes = []
for r in rows('적치장 노드 정보.csv'):
    lat, lon = map(float, r['GPS'].split(','))
    def numeric(text):
        return [float(v) for v in re.findall(r"[0-9.]+", text.replace(',', ''))]
    widths, depths, areas = numeric(r['width']), numeric(r['depth']), numeric(r['area(m^2)'])
    area = areas[0] if areas else 0
    aspect = max(widths) / max(depths) if widths and depths else 1
    width = math.sqrt(area * aspect) if area else 12
    depth = area / width if area else 12
    nodes.append(dict(code=r['code'], kind=r['object'], lat=lat, lon=lon,
                      width=width, depth=depth, area=area,
                      original_width=r['width'], original_depth=r['depth']))

blocks = {r['block_code']: dict(length=float(r['length_m']), width=float(r['width_m']),
          height=float(r['height_m']), start=r['inbound_date'], end=r['outbound_date']) for r in rows('block_schedule.csv')}
roads = [dict(source=r['from_node'], target=r['to_node'], distance=float(r['road_distance_m']),
              time=float(r['travel_time_min']), both=r['is_bidirectional'].lower() == 'true') for r in rows('virtual_road_edges.csv')]
scenario = json.loads((ROOT / 'scenarios/milp.json').read_text())
output = ROOT / 'dashboard/assets/data.json'
output.write_text(json.dumps(dict(slots=slots, nodes=nodes, blocks=blocks, roads=roads,
                                 spacing_factor=scenario['spacing_factor']), ensure_ascii=False, separators=(',', ':')))
print(f'Built {output.relative_to(ROOT)} ({output.stat().st_size:,} bytes)')
