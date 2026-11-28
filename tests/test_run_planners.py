import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_planners


class UnifiedRunnerTests(unittest.TestCase):
    def test_all_and_individual_options_use_common_job_runner(self):
        captured = []
        class FakeManager:
            def __init__(self, root, rebuild): pass
            def start(self, settings):
                captured.append(settings)
                return {'id':'test','directory':'runs/test'}
            def status(self):
                return {'id':'test','status':'succeeded','tasks':{},'published':['milp','meta']}
            def close(self): pass
        with patch.object(run_planners, 'JobManager', FakeManager), contextlib.redirect_stdout(io.StringIO()):
            for algorithm in ('all', 'milp', 'meta'):
                self.assertEqual(run_planners.main(['--algorithm',algorithm,'--milp-time-limit','30','--meta-time-limit','2','--seed','9']),0)
        self.assertEqual([x['target'] for x in captured],['both','milp','meta'])
        self.assertTrue(all(x['milp_seconds']==30 and x['meta_seconds']==2 and x['seed']==9 for x in captured))
