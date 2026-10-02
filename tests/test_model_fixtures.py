"""Offline checks of the model fixtures in conftest.py: what a run says when a model server is down."""

import http.server
import socket
import threading
from pathlib import Path

CONFTEST = Path(__file__).with_name("conftest.py").read_text(encoding="utf-8")


def run_test_needing(pytester, fixture):
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile(f"def test_needs_it({fixture}): pass")
    return pytester.runpytest()


def test_unreachable_text_model_says_how_to_start_it(pytester, monkeypatch):
    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        monkeypatch.setenv("TEXT_MODEL_BASE_URL", f"http://127.0.0.1:{free.getsockname()[1]}/v1")
    monkeypatch.setenv("TEXT_MODEL", "gemma4:e4b")
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "ollama")

    result = run_test_needing(pytester, "text_model")

    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*Text model gemma4:e4b not available at http://127.0.0.1:*ollama pull gemma4:e4b*"])


class Failing(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_error(500)

    def log_message(self, *args):
        pass


def test_failing_decision_server_is_not_called_unreachable(pytester, monkeypatch):
    server = http.server.HTTPServer(("127.0.0.1", 0), Failing)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("LAYA_URL", f"http://127.0.0.1:{server.server_port}")
    try:
        result = run_test_needing(pytester, "decision_model")
    finally:
        server.shutdown()

    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*Decision server at http://127.0.0.1:* answered HTTP 500*"])
