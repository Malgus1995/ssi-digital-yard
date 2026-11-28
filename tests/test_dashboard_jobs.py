import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'dashboard'))
sys.path.insert(0, str(ROOT / 'src'))
from jobs import JobManager

SCRIPT = '''
import sys,json,time,hashlib
from pathlib import Path
sys.path.insert(0, SRC)
from ssi_yard.benchmark.environment import environment_fingerprint,save_metrics
args=sys.argv
get=lambda key: args[args.index(key)+1]
config=json.loads(Path(get('--config')).read_text())
fingerprint=environment_fingerprint(Path(get('--data-dir')),config)
out=Path(get('--output')) if '--output' in args else Path(get('--output-dir'))/'result.json'
out.parent.mkdir(parents=True,exist_ok=True)
(out.parent/'started.txt').write_text(str(time.time()))
print('started',flush=True)
time.sleep(config.get('sleep',.3))
if config.get('no_solution'): sys.exit(0)
for folder in ([out.parent] if '--output' in args else [out.parent,*[out.parent/m for m in ('greedy','sa','tabu')]]):
 folder.mkdir(parents=True,exist_ok=True)
 path=folder/'result.json';path.write_text(json.dumps({'total_cost':1,'assignment':{},'daily_moves':{'2026-01-01':[]}}))
 save_metrics(path,{'problem_fingerprint':fingerprint,'feasibility':{'valid':True},'cost':{'total':1}})
print('finished',flush=True)
'''.replace('SRC', repr(str(ROOT / 'src')))


class JobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        (self.root/'raw-data').mkdir(); (self.root/'scenarios').mkdir()
        for name in ('block_schedule.csv','적치장 노드 정보.csv','virtual_road_edges.csv','yard_process_distances.csv'):
            (self.root/'raw-data'/name).write_text('test')
        (self.root/'scenarios/milp.json').write_text('{}')
        for name in ('main.py','run_meta.py'): (self.root/name).write_text(SCRIPT)
        self.builds = []
        self.manager = JobManager(self.root, lambda: self.builds.append(True))

    def tearDown(self):
        self.manager.close(); self.tmp.cleanup()

    def wait(self):
        end=time.monotonic()+10
        while self.manager.worker.is_alive() and time.monotonic()<end: time.sleep(.02)
        self.assertFalse(self.manager.worker.is_alive())
        return self.manager.status()

    def test_concurrent_snapshot_publication_history_and_duplicate(self):
        job=self.manager.start({'target':'both','milp_seconds':1,'meta_seconds':.1})
        with self.assertRaises(RuntimeError): self.manager.start({'target':'meta'})
        result=self.wait();self.assertEqual(result['status'],'succeeded',result)
        self.assertEqual(set(result['published']),{'milp','meta'});self.assertEqual(len(self.builds),2)
        folder=self.root/job['directory']
        starts=[float((folder/name/'started.txt').read_text()) for name in ('milp','meta')]
        self.assertLess(abs(starts[0]-starts[1]),.3)
        for path in ('runs/milp/result.json','runs/meta-heuristics/result.json','runs/meta-heuristics/sa/result.json'):
            self.assertEqual(json.loads((self.root/path).read_text())['total_cost'],1)
        self.assertIn('finished',result['tasks']['milp']['log'])
        self.assertEqual(JobManager(self.root,lambda:None).status()['id'],job['id'])

    def test_cancel_preserves_previous_output(self):
        (self.root/'scenarios/milp.json').write_text('{"sleep":3}')
        previous=self.root/'runs/milp/result.json';previous.parent.mkdir(parents=True);previous.write_text('previous')
        job=self.manager.start({'target':'both'})
        time.sleep(.15);self.manager.cancel(job['id']);result=self.wait()
        self.assertEqual(result['status'],'cancelled');self.assertEqual(previous.read_text(),'previous')
        self.assertFalse(self.builds)

    def test_no_solution_keeps_previous_result(self):
        (self.root/'scenarios/milp.json').write_text('{"no_solution":true}')
        previous=self.root/'runs/milp/result.json';previous.parent.mkdir(parents=True);previous.write_text('previous')
        self.manager.start({'target':'milp'});result=self.wait()
        self.assertEqual(result['status'],'no_solution');self.assertEqual(previous.read_text(),'previous')

    def test_rebuild_failure_rolls_back_canonical_result(self):
        previous=self.root/'runs/milp/result.json';previous.parent.mkdir(parents=True);previous.write_text('previous')
        def broken_build(): raise RuntimeError('test build failure')
        self.manager.rebuild=broken_build
        self.manager.start({'target':'milp'});result=self.wait()
        self.assertEqual(result['status'],'failed')
        self.assertEqual(previous.read_text(),'previous')
        self.assertFalse(previous.with_name('metrics.json').exists())

    def test_other_launcher_detects_and_cancels_active_job(self):
        (self.root/'scenarios/milp.json').write_text('{"sleep":3}')
        job=self.manager.start({'target':'milp'})
        time.sleep(.1)
        observer=JobManager(self.root,lambda:None)
        self.assertEqual(observer.status()['id'],job['id'])
        with self.assertRaises(RuntimeError): observer.start({'target':'meta'})
        observer.cancel(job['id'])
        self.assertEqual(self.wait()['status'],'cancelled')
        self.assertEqual(observer.status()['status'],'cancelled')

    def test_invalid_parameters(self):
        for payload in ({'target':'shell'},{'milp_seconds':0},{'meta_seconds':float('nan')},{'seed':-1},{'seed':True}):
            with self.assertRaises(ValueError): self.manager.start(payload)
