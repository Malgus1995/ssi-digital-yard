"""Build and serve the yard dashboard using only the Python standard library."""

import argparse
import errno
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from build_data import ROOT, build
from jobs import JobManager


class DashboardHandler(SimpleHTTPRequestHandler):
    def json_response(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/api/runs':
            self.json_response(200, {'available': True, 'job': self.server.jobs.status()})
        else:
            super().do_GET()

    def do_POST(self):
        # Same-origin loopback actions only; never accept arbitrary executable paths.
        allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        host = self.headers.get('Host', '')
        origin = self.headers.get('Origin')
        if host not in allowed or (origin and origin != 'http://' + host):
            self.json_response(403, {'error': '로컬 대시보드에서만 실행할 수 있습니다.'})
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 8192 or self.headers.get_content_type() != 'application/json':
                raise ValueError('JSON 요청이 필요합니다.')
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError('JSON 객체가 필요합니다.')
            if self.path == '/api/runs':
                job = self.server.jobs.start(payload)
                self.json_response(202, {'job': job})
            elif self.path.startswith('/api/runs/') and self.path.endswith('/cancel'):
                identifier = self.path.split('/')[3]
                self.json_response(200, {'job': self.server.jobs.cancel(identifier)})
            else:
                self.json_response(404, {'error': 'API를 찾을 수 없습니다.'})
        except RuntimeError as error:
            self.json_response(409, {'error': str(error)})
        except (ValueError, TypeError) as error:
            self.json_response(400, {'error': str(error)})

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()


def main():
    parser = argparse.ArgumentParser(description='MILP 대시보드 데이터를 생성하고 로컬 웹 서버를 시작합니다.')
    parser.add_argument('--port', type=int, default=8080, help='로컬 포트 (기본값: 8080)')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('포트는 1~65535 범위여야 합니다.')
    build()
    handler = partial(DashboardHandler, directory=str(ROOT / 'dashboard'))
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), handler)
    except OSError as error:
        hint = '\n다른 포트를 지정하세요: --port 8081' if error.errno == errno.EADDRINUSE else ''
        parser.exit(1, f'서버 시작 실패: {error}{hint}\n')
    print(f'\n대시보드: http://127.0.0.1:{args.port}\n종료: Ctrl+C\n', flush=True)
    with server:
        server.jobs = JobManager(ROOT, build)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print('\n대시보드 서버를 종료했습니다.')
        finally:
            server.jobs.close()


if __name__ == '__main__':
    main()
