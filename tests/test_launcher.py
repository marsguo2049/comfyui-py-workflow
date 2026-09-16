"""Repeated desktop launches must reuse a verified workbench, not another app."""
import importlib.util
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


@pytest.mark.parametrize('matching', [True, False])
def test_launcher_reuses_only_its_own_service(monkeypatch, matching):
    path = Path(__file__).resolve().parents[1] / 'scripts/launch.py'
    spec = importlib.util.spec_from_file_location('workbench_launcher', path)
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)

    class Handler(BaseHTTPRequestHandler):
        server_version = 'CPWComfyUIWorkbench/0.6' if matching else 'OtherWorkbench/1'
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'<title>ComfyUI Workbench</title>')
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    opened, started = [], []
    monkeypatch.setattr(launcher.webbrowser, 'open', lambda url: opened.append(url) or True)
    def run(command, **kwargs):
        started.append(command)
        return type('Result', (), {'returncode': 2})()
    monkeypatch.setattr(launcher.subprocess, 'run', run)
    try:
        result = launcher.main(['--port', str(server.server_port)])
        assert result == (0 if matching else 2)
        assert len(started) == (0 if matching else 1)
        assert opened == ([f'http://127.0.0.1:{server.server_port}/#batch'] if matching else [])
        opened.clear()
        if matching:
            assert launcher.main(['--port', str(server.server_port), '--no-browser']) == 0
            assert opened == [] and started == []
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
