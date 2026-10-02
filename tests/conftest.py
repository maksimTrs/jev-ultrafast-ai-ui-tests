import base64
import json
import os
import random
import re
import urllib.request
from html import escape
from pathlib import Path

import pytest
import pytest_html
from pytest_metadata.plugin import metadata_key

from framework import jev_local
from framework.chrome import Chrome
from framework.runner import continue_goal, start_goal

jev_local.install()

SAUCEDEMO = "https://www.saucedemo.com"
ARTIFACTS = Path(__file__).resolve().parents[1] / "reports" / "artifacts"
RUNS = pytest.StashKey[list]()


def pytest_addoption(parser):
    parser.addoption("--headless", action="store_true", help="Run Chrome without a window")
    parser.addoption("--record-steps", action="store_true", help="Screenshot after every agent action")


def pytest_configure(config):
    config.stash[RUNS] = []
    headless = config.getoption("--headless")
    config.stash[metadata_key].update(
        {
            "Decision model": f"laya-browser @ {os.environ.get('LAYA_URL', 'http://127.0.0.1:8791')}",
            "Text model": f"{os.environ.get('TEXT_MODEL', '-')} @ {os.environ.get('TEXT_MODEL_BASE_URL', '-')}",
            "Mode": f"{os.environ.get('RUN_MODE', 'local')}, {'headless' if headless else 'headed'}",
        }
    )


@pytest.fixture(scope="session")
def chrome(request):
    browser = Chrome(headless=request.config.getoption("--headless"))
    request.config.stash[metadata_key]["Browser"] = browser.version
    yield browser
    browser.close()


@pytest.fixture
def site(chrome):
    """Every test starts from a clean saucedemo: no session cookie, no cart in localStorage."""
    chrome.clear_origin(SAUCEDEMO)
    return SAUCEDEMO


@pytest.fixture
def logged_in(chrome, site):
    """Precondition without the agent: saucedemo keeps its session in this cookie."""
    chrome.set_cookie(name="session-username", value="standard_user", domain="www.saucedemo.com", path="/")


@pytest.fixture(autouse=True)
def faker_seed():
    """Faker's pytest plugin seeds every test with 0: the same data in every run, which stops finding bugs.
    The plugin only reads this fixture when it is autouse. The values go into the goal, so the report shows them."""
    return random.randrange(2**32)


@pytest.fixture(scope="session")
def decision_model():
    """Without the decision server every agent fails on its first step; say so once, before any browser work."""
    url = os.environ.get("LAYA_URL", "http://127.0.0.1:8791")
    try:
        urllib.request.urlopen(url, timeout=5).close()
        return
    except OSError as exc:
        error = exc  # failing outside the except keeps the chained traceback out of the report
    pytest.fail(
        f"Decision server not reachable at {url} ({error}). Start it in another terminal: "
        "uv run --project services/decision python services/decision/serve.py",
        pytrace=False,
    )


@pytest.fixture(scope="session")
def text_model():
    """Loads the text model up front. A cold load takes 20-40 s; jev's 25 s timeout would cancel it (Ollama aborts
    a load when the client disconnects) and the load time would skew the measurements."""
    request = urllib.request.Request(
        os.environ["TEXT_MODEL_BASE_URL"].rstrip("/") + "/chat/completions",
        data=json.dumps(
            {"model": os.environ["TEXT_MODEL"], "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]}
        ).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {os.environ['TEXT_MODEL_API_KEY']}"},
    )
    urllib.request.urlopen(request, timeout=300).close()


class JevSession:
    """One test's agent: start() opens a page and runs a goal, then() runs the next goal in the same tab.

    Both return the run result and the live page, so the test asserts on the real DOM after every goal.
    """

    def __init__(self, request, site):
        self.request, self.site = request, site
        self.folder = ARTIFACTS / re.sub(r"[^\w.-]+", "_", request.node.name)
        self.record = request.config.getoption("--record-steps")
        self.agent = None
        request.node.jev_runs = []

    def start(self, path, goal, *, max_actions):
        self.close()
        result, self.agent = start_goal(self.site + path, goal, max_actions=max_actions, record_dir=self._frames())
        return self._record(result)

    def then(self, goal, *, max_actions):
        result = continue_goal(self.agent, goal, max_actions=max_actions, record_dir=self._frames())
        return self._record(result)

    def close(self):
        if self.agent:
            self.agent.close()
            self.agent = None

    def _run_folder(self):
        return self.folder / f"run-{len(self.request.node.jev_runs) + 1}"

    def _frames(self):
        return self._run_folder() / "frames" if self.record else None

    def _record(self, result):
        browser = self.agent.browser
        screenshot = browser.call("Page.captureScreenshot", format="jpeg", quality=72)["data"]
        folder = self._run_folder()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "run.json").write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        self.request.node.jev_runs.append((result, screenshot, folder))
        self.request.config.stash[RUNS].append((f"{self.request.node.name}#{len(self.request.node.jev_runs)}", result))
        return result, browser


@pytest.fixture
def jev(request, decision_model, text_model, site):
    session = JevSession(request, site)
    yield session
    session.close()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    report = (yield).get_result()
    runs = getattr(item, "jev_runs", [])
    if report.when != "call" or not runs:
        return
    results = [result for result, _, _ in runs]
    decisions = [ms for result in results for ms in result.decision_ms]
    report.jev = {
        "status": "/".join(result.status for result in results),
        "actions": sum(len(result.steps) for result in results),
        "elapsed_ms": sum(result.elapsed_ms for result in results),
        "avg_decision_ms": round(sum(decisions) / len(decisions)) if decisions else 0,
    }
    extras = getattr(report, "extras", [])
    for number, (result, screenshot, folder) in enumerate(runs, 1):
        extras.append(pytest_html.extras.html(_steps_html(number, result)))
        extras.append(pytest_html.extras.jpg(screenshot, name=f"Run {number}: final page"))
        if report.failed:
            for frame in sorted((folder / "frames").glob("*.jpg")):
                frame_b64 = base64.b64encode(frame.read_bytes()).decode()  # embedded: the report is one file
                extras.append(pytest_html.extras.jpg(frame_b64, name=f"Run {number}: after {frame.stem} ms"))
    report.extras = extras


def pytest_html_results_table_header(cells):
    cells.insert(2, "<th>Agent</th><th>Actions</th><th>Agent ms</th><th>Avg decision ms</th>")


def pytest_html_results_table_row(report, cells):
    jev = getattr(report, "jev", None)
    values = (jev["status"], jev["actions"], jev["elapsed_ms"], jev["avg_decision_ms"]) if jev else ("",) * 4
    cells.insert(2, "".join(f"<td>{escape(str(v))}</td>" for v in values))


def pytest_terminal_summary(terminalreporter, config):
    if (k := config.getoption("count", 1)) > 1:
        _pass_hat_k(terminalreporter, k)
    runs = config.stash.get(RUNS, [])
    if not runs:
        return
    terminalreporter.section("jev runs")
    terminalreporter.write_line(f"{'run':40} {'agent':8} {'actions':>7} {'agent ms':>9} {'avg decision ms':>16}")
    for name, r in runs:
        terminalreporter.write_line(
            f"{name:40} {r.status:8} {len(r.steps):>7} {r.elapsed_ms:>9} {r.avg_decision_ms:>16}"
        )


def _pass_hat_k(terminalreporter, k):
    """pass^k (τ-bench): a test counts only if all k trials passed. pytest-repeat names trials test[1-3], test[2-3]"""
    trials = {}
    for reports in terminalreporter.stats.values():
        for report in reports:
            if isinstance(report, pytest.TestReport):  # setup, call and teardown must all pass
                trials[report.nodeid] = trials.get(report.nodeid, True) and report.passed
    tests = {}
    for nodeid, passed in trials.items():
        tests.setdefault(re.sub(r"\[\d+-\d+\]$", "", nodeid), []).append(passed)
    terminalreporter.section(f"pass^{k}")
    for name, passed in tests.items():
        terminalreporter.write_line(f"{name:72} {sum(passed)}/{len(passed)}")
    reliable = sum(all(passed) for passed in tests.values())
    terminalreporter.write_line(f"pass^{k}: {reliable}/{len(tests)} tests passed all {k} trials")


def _steps_html(number, result):
    rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{escape(str(s[k] if s[k] is not None else ''))}</td>"
            for k in ("step", "operation", "action", "text", "probability", "decision_ms", "text_ms")
        )
        + "</tr>"
        for s in result.steps
    )
    error = f"<p><b>Agent error:</b> {escape(result.error)}</p>" if result.error else ""
    return (
        f"<h4>Run {number}</h4><p><b>Goal:</b> {escape(result.goal)}</p>"
        f"<p><b>Agent status:</b> {result.status} &middot; <b>final URL:</b> {escape(result.final_url)}</p>{error}"
        "<table border='1' cellpadding='4' style='border-collapse:collapse'>"
        "<tr><th>#</th><th>Operation</th><th>Element</th><th>Text</th><th>Probability</th>"
        "<th>Decision ms</th><th>Text ms</th></tr>"
        f"{rows}</table>"
    )
