"""Shared objective settings and result provenance for fair planner comparisons."""
import hashlib
import json
from pathlib import Path
from unicodedata import normalize


def objective_parameters(config, capacity):
    overrides = config.get('yard_overrides', {})
    return {
        'spacing_factor': config['spacing_factor'],
        'max_utilization': config['max_utilization'],
        'yard_rate': {y: overrides.get(y, {}).get('yard_rate', config['default_yard_rate']) for y in capacity},
        'tier_by_yard': {y: overrides.get(y, {}).get('tier', config['default_tier']) for y in capacity},
        'threshold_by_tier': {int(k): v for k, v in config['threshold_by_tier'].items()},
        'congestion_rate': {int(k): v for k, v in config['congestion_rate'].items()},
    }


def environment_fingerprint(data_dir: Path, config: dict) -> str:
    digest = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(',', ':')).encode())
    for name in ('block_schedule.csv', '적치장 노드 정보.csv', 'virtual_road_edges.csv', 'yard_process_distances.csv'):
        matches = [p for p in data_dir.iterdir() if normalize('NFC', p.name) == name]
        if len(matches) != 1:
            raise ValueError(f'expected exactly one {name}')
        digest.update(name.encode())
        digest.update(matches[0].read_bytes())
    return digest.hexdigest()


def save_metrics(result_path: Path, metrics: dict):
    report = dict(metrics, schema_version=1,
                  result_sha256=hashlib.sha256(result_path.read_bytes()).hexdigest())
    result_path.with_name('metrics.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    return report
