"""Local subprocess jobs. Each batch shares an immutable input snapshot."""
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
import fcntl
from datetime import datetime, timezone
from pathlib import Path

TERMINAL = {'succeeded', 'failed', 'no_solution', 'cancelled', 'interrupted'}


def atomic_copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.publishing')
    shutil.copyfile(source, temporary)
    os.replace(temporary, target)


class JobManager:
    @staticmethod
    def _restore(path):
        job = json.loads(path.read_text())
        if job['status'] not in TERMINAL:
            alive = False
            if job.get('owner_pid'):
                try:
                    os.kill(job['owner_pid'], 0)
                    alive = True
                except ProcessLookupError:
                    pass
            if not alive:
                job['status'] = 'interrupted'
                for task in job['tasks'].values():
                    if task['status'] not in TERMINAL:
                        task['status'] = 'interrupted'
        return job

    def __init__(self, root, rebuild):
        self.root = Path(root)
        self.rebuild = rebuild
        self.lock = threading.RLock()
        self.publish_lock = threading.Lock()
        self.job = None
        self.processes = {}
        self.worker = None
        self.launch_lock = None
        history = sorted((self.root / 'runs/dashboard-jobs').glob('*/job.json'))
        if history:
            try:
                self.job = self._restore(max(history, key=lambda p: p.stat().st_mtime_ns))
            except (ValueError, KeyError):
                self.job = None

    @staticmethod
    def settings(payload):
        target = payload.get('target', 'both')
        if target not in {'both', 'milp', 'meta'}:
            raise ValueError('target은 both, milp, meta 중 하나여야 합니다.')
        result = {'target': target}
        for key, default, low, high in [('milp_seconds', 300, 1, 3600), ('meta_seconds', 5, .1, 120)]:
            value = payload.get(key, default)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f'{key}: {low}~{high} 범위의 숫자가 필요합니다.')
            result[key] = value
        seed = payload.get('seed', 42)
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**31 - 1:
            raise ValueError('seed는 0~2147483647 정수여야 합니다.')
        result['seed'] = seed
        return result

    def _persist(self):
        path = self.root / self.job['directory'] / 'job.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.job, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, path)

    def status(self):
        with self.lock:
            if self.worker is None or not self.worker.is_alive():
                history = list((self.root / 'runs/dashboard-jobs').glob('*/job.json'))
                if history:
                    latest = max(history, key=lambda p: p.stat().st_mtime_ns)
                    stored = self._restore(latest)
                    if self.job is None or stored['id'] != self.job['id'] or stored.get('owner_pid') != os.getpid():
                        self.job = stored
            if not self.job:
                return None
            if self.worker is None and self.job.get('owner_pid') and self.job['status'] not in TERMINAL:
                path = self.root / self.job['directory'] / 'job.json'
                self.job = self._restore(path)
            job = json.loads(json.dumps(self.job))
        for name, task in job['tasks'].items():
            path = self.root / job['directory'] / (name + '.log')
            if path.exists():
                with path.open('rb') as stream:
                    stream.seek(max(0, path.stat().st_size - 8000))
                    task['log'] = stream.read().decode('utf-8', errors='replace')
            task['elapsed_seconds'] = round((task.get('finished_at') or time.time()) - task['started_at'], 1)
        return job

    def start(self, payload):
        settings = self.settings(payload)
        with self.lock:
            self.status()
            if (self.worker and self.worker.is_alive()) or (self.job and self.job['status'] not in TERMINAL):
                raise RuntimeError('실행 중인 작업이 있습니다. 완료를 기다리거나 중지하세요.')
            lock_path = self.root / 'runs/dashboard-jobs/.launch.lock'
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_file = lock_path.open('a+')
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                lock_file.close()
                raise RuntimeError('다른 터미널 또는 대시보드에서 알고리즘이 실행 중입니다.')
            self.launch_lock = lock_file
            identifier = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8]
            self.job = {'id': identifier, 'directory': 'runs/dashboard-jobs/' + identifier,
                        'status': 'running', 'settings': settings, 'tasks': {}, 'cancel_requested': False,
                        'created_at': datetime.now(timezone.utc).isoformat(), 'published': [], 'revision': 0,
                        'owner_pid': os.getpid()}
            self._persist()
            self.worker = threading.Thread(target=self._run, daemon=True)
            self.worker.start()
            return self.status()

    def cancel(self, identifier):
        with self.lock:
            if not self.job or self.job['id'] != identifier:
                raise ValueError('작업을 찾을 수 없습니다.')
            if self.job['status'] not in TERMINAL:
                self.job['cancel_requested'] = True
                (self.root / self.job['directory'] / 'CANCEL').touch()
                self._persist()
            return self.status()

    def _run(self):
        files = []
        try:
            directory = self.root / self.job['directory']
            snapshot = directory / 'input'
            shutil.copytree(self.root / 'raw-data', snapshot / 'raw-data')
            shutil.copyfile(self.root / 'scenarios/milp.json', snapshot / 'config.json')
            # Meta's optional legacy comparison must never read/write the live MILP output.
            baseline = snapshot / 'baseline/result.json'
            if (self.root / 'runs/milp/result.json').exists():
                atomic_copy(self.root / 'runs/milp/result.json', baseline)
            python = self.root / '.venv/bin/python'
            python = str(python) if python.exists() else sys.executable
            settings = self.job['settings']
            names = ['milp', 'meta'] if settings['target'] == 'both' else [settings['target']]
            for name in names:
                with self.lock:
                    if self.job['cancel_requested']:
                        break
                    output = directory / name
                    common = ['--data-dir', str(snapshot / 'raw-data'), '--config', str(snapshot / 'config.json')]
                    command = ([python, '-u', str(self.root / 'main.py'), *common,
                                '--time-limit', str(settings['milp_seconds']), '--solver-log', '--output', str(output / 'result.json')]
                               if name == 'milp' else
                               [python, '-u', str(self.root / 'run_meta.py'), *common, '--algorithm', 'all',
                                '--time-limit', str(settings['meta_seconds']), '--seed', str(settings['seed']),
                                '--baseline', str(baseline), '--output-dir', str(output)])
                    log = (directory / (name + '.log')).open('w', encoding='utf-8')
                    files.append(log)
                    self.processes[name] = subprocess.Popen(command, cwd=self.root, stdout=log, stderr=subprocess.STDOUT,
                                                            start_new_session=True)
                    self.job['tasks'][name] = {'status': 'running', 'started_at': time.time()}
                    self._persist()
            pending = set(self.processes)
            while pending:
                with self.lock:
                    if (directory / 'CANCEL').exists():
                        self.job['cancel_requested'] = True
                    cancelled = self.job['cancel_requested']
                if cancelled:
                    self._terminate()
                for name in list(pending):
                    process = self.processes[name]
                    if process.poll() is None:
                        continue
                    pending.remove(name)
                    with self.lock:
                        task = self.job['tasks'][name]
                        task.update(exit_code=process.returncode, finished_at=time.time())
                        task['status'] = 'cancelled' if cancelled else 'failed' if process.returncode else 'verifying'
                        self._persist()
                    if not cancelled and process.returncode == 0:
                        try:
                            self._publish(name, directory / name)
                        except Exception as error:
                            with self.lock:
                                task.update(status='failed', error=str(error))
                    with self.lock:
                        self._persist()
                time.sleep(.2)
            with self.lock:
                statuses = [t['status'] for t in self.job['tasks'].values()]
                self.job['status'] = ('cancelled' if self.job['cancel_requested'] else
                                      'failed' if any(s == 'failed' for s in statuses) else
                                      'no_solution' if any(s == 'no_solution' for s in statuses) else 'succeeded')
                self._persist()
        except Exception as error:
            self._terminate()
            with self.lock:
                self.job.update(status='failed', error=str(error))
                for task in self.job['tasks'].values():
                    if task['status'] not in TERMINAL:
                        task.update(status='failed', finished_at=time.time())
                self._persist()
        finally:
            for log in files:
                log.close()
            self.processes = {}
            if self.launch_lock:
                fcntl.flock(self.launch_lock.fileno(), fcntl.LOCK_UN)
                self.launch_lock.close()
                self.launch_lock = None

    def _publish(self, name, source):
        if not (source / 'result.json').exists():
            with self.lock:
                self.job['tasks'][name].update(status='no_solution', error='시간 내 가능해를 얻지 못했습니다. 이전 결과를 유지합니다.')
            return
        from ssi_yard.benchmark.environment import environment_fingerprint
        import hashlib
        config = json.loads((self.root / 'scenarios/milp.json').read_text())
        fingerprint = environment_fingerprint(self.root / 'raw-data', config)
        bundles = [source] if name == 'milp' else [source, *(source / m for m in ('greedy', 'sa', 'tabu'))]
        for bundle in bundles:
            result = json.loads((bundle / 'result.json').read_text())
            metrics = json.loads((bundle / 'metrics.json').read_text())
            if (metrics.get('result_sha256') != hashlib.sha256((bundle / 'result.json').read_bytes()).hexdigest()
                    or metrics.get('problem_fingerprint') != fingerprint
                    or metrics.get('feasibility', {}).get('valid') is not True
                    or not math.isclose(result['total_cost'], metrics['cost']['total'], rel_tol=1e-9, abs_tol=1e-4)):
                raise ValueError('결과/환경/제약 검증 정보가 일치하지 않습니다. 원본 결과를 유지합니다.')
        with self.publish_lock:
            with self.lock:
                if self.job['cancel_requested']:
                    self.job['tasks'][name]['status'] = 'cancelled'
                    return
            target = self.root / ('runs/milp' if name == 'milp' else 'runs/meta-heuristics')
            # Back up canonical bundles so a failed rebuild can roll back publication.
            changes = []
            for bundle in bundles:
                destination = target if bundle == source else target / bundle.name
                for filename in ('result.json', 'metrics.json'):
                    changes.append((bundle / filename, destination / filename))
            if (source / 'comparison.json').exists():
                changes.append((source / 'comparison.json', target / 'comparison.json'))
            backups = []
            for _, destination in changes:
                backup = source.parent / 'previous' / name / destination.relative_to(target)
                if destination.exists():
                    atomic_copy(destination, backup)
                    backups.append((destination, backup))
                else:
                    backups.append((destination, None))
            try:
                for original, destination in changes:
                    atomic_copy(original, destination)
                self.rebuild()
            except Exception:
                for destination, backup in backups:
                    if backup:
                        atomic_copy(backup, destination)
                    else:
                        destination.unlink(missing_ok=True)
                raise
            with self.lock:
                self.job['tasks'][name]['status'] = 'succeeded'
                self.job['published'].append(name)
                self.job['revision'] += 1

    def _terminate(self):
        for process in list(self.processes.values()):
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        for process in list(self.processes.values()):
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()

    def close(self):
        with self.lock:
            if self.worker and self.worker.is_alive() and self.job and self.job['status'] not in TERMINAL:
                self.job['cancel_requested'] = True
        if self.worker:
            self.worker.join(timeout=6)
