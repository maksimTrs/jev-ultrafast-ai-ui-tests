"""Drives natural-language goals through jev-ultrafast and keeps a compact record of every step."""

import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from jev_ultrafast import Agent
from jev_ultrafast.browser import StalePage

SECRET_FIELD = re.compile("password", re.IGNORECASE)
INTERACTIVE = {"click", "fill", "select"}
# The agent stops instead of taking a less likely step: P(operation) × P(target). A sure target alone is not enough,
# the model may still doubt whether to click at all. On saucedemo every intended step scores 0.77 or higher;
# an ambiguous goal ("Add a T-shirt" with two T-shirts for sale) tops out at 0.11.
MIN_PROBABILITY = 0.5
# Agent.state of the pinned jev-ultrafast: continue_goal resets each key by hand and _tick mirrors its tick.
STATE_KEYS = {
    "browser", "goal", "page", "decision", "history", "status", "plan", "plan_index",
    "decisions", "text_calls", "elapsed_ms", "started_at", "record",
}  # fmt: skip


@dataclass
class RunResult:
    goal: str
    status: str  # done | blocked | budget | error — the agent's view, never the test verdict
    elapsed_ms: int
    steps: list
    decision_ms: list
    final_url: str
    error: str | None = None

    @property
    def outcome(self):
        """The status with the agent's error, if any: the assertion message for a failed check."""
        return f"{self.status}: {self.error}" if self.error else self.status

    @property
    def avg_decision_ms(self):
        return round(sum(self.decision_ms) / len(self.decision_ms)) if self.decision_ms else 0

    def to_dict(self):
        return {**asdict(self), "actions": len(self.steps), "avg_decision_ms": self.avg_decision_ms}


def start_goal(url, goal, *, max_actions, record_dir=None):
    """Opens url in a new tab and runs the goal. Returns the result and the open agent; the caller closes it."""
    agent = Agent(url, goal, record_dir=record_dir)
    # jev opens its tab in the background: bring it forward so a headed run shows the test,
    # and so headless Chrome paints it (a background tab may never render a screenshot).
    try:
        agent.browser.call("Page.bringToFront")
    except BaseException:
        agent.close()  # the caller never gets this agent, so nothing else would close its tab
        raise
    return _drive(agent, goal, max_actions), agent


def continue_goal(agent, goal, *, max_actions, record_dir=None):
    """Runs the next goal in the same tab: the page (filled fields included) carries over, the history does not.

    The decision model stops after typing into the last field of a form, so submitting it is a separate goal,
    which only works if the form keeps its values.
    """
    if set(agent.state) != STATE_KEYS:
        raise RuntimeError("jev_ultrafast Agent.state changed; review continue_goal and _tick before re-pinning")
    agent.state.update(
        goal=goal, plan=[goal], plan_index=0, history=[], decisions=[], text_calls=[],
        decision=None, status="ready", started_at=None, elapsed_ms=0, record=bool(record_dir),
    )  # fmt: skip
    agent.pending_text = None
    agent.record_dir = Path(record_dir) if record_dir else None
    if agent.record_dir:
        agent.record_dir.mkdir(parents=True, exist_ok=True)
    return _drive(agent, goal, max_actions)


def _drive(agent, goal, max_actions):
    status, error = "error", None
    try:
        _wait_for_controls(agent)
        while agent.state["status"] not in {"done", "blocked"}:
            if len(agent.state["history"]) >= max_actions:
                status = "budget"
                break
            if stop := _tick(agent):
                status, error = "blocked", stop
                break
        else:
            status = agent.state["status"]
    except Exception as exc:  # the agent's own failures are a result to report, not a test crash
        error = f"{type(exc).__name__}: {exc}{_last_decision(agent.state)}"
    state = agent.state
    return RunResult(
        goal=goal,
        status=status,
        elapsed_ms=state["elapsed_ms"],
        steps=[_step(h) for h in state["history"]],
        decision_ms=[d["latency_ms"] for d in state["decisions"]],
        final_url=state["page"]["url"],
        error=error,
    )


def _tick(agent):
    """Agent.command("tick") with a confidence check between the decision and the action.

    Returns why the run stops when the chosen action is below MIN_PROBABILITY (it is not executed), else None.
    DONE and BLOCKED are not checked: they end the run, and the test's assertion is the verdict.
    The StalePage recovery mirrors tick in jev_ultrafast/agent.py.
    """
    state = agent.state
    steps = len(state["history"])
    try:
        agent.command("predict")
        decision = state["decision"]
        probability = _probability(decision)
        if decision["choice"] not in {"DONE", "BLOCKED"} and probability < MIN_PROBABILITY:
            state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
            return f"probability {probability:.3f} below {MIN_PROBABILITY}{_last_decision(state)}"
        agent.command("act", {"fingerprint": state["page"]["fingerprint"]})
    except StalePage:
        state["decision"] = None
        state["status"] = "ready"
        state["page"] = agent.browser.observe(screenshot=agent.screenshots)
        state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
    if len(state["history"]) > steps:  # upstream records the target's probability; the report shows the checked one
        state["history"][-1]["probability"] = probability
    return None


def _probability(decision):
    """How likely the whole step is: its operation times its target. Scroll, wait, DONE and BLOCKED have no target."""
    probability = decision["operation_probabilities"][decision["operation"]]
    if decision["target"] is not None:
        probability *= decision["target_probabilities"][decision["target"]]
    return probability


def _wait_for_controls(agent, timeout=5):
    """Observes the page afresh: the previous goal may have left it mid-navigation.

    A client-rendered page can be observed before it renders; on an empty page the model answers DONE.
    """
    deadline = time.monotonic() + timeout
    while True:
        agent.state["page"] = agent.browser.observe(screenshot=agent.screenshots)
        if any(a["kind"] in INTERACTIVE for a in agent.state["page"]["actions"]) or time.monotonic() >= deadline:
            return
        time.sleep(0.1)


def _last_decision(state):
    """The decision that was being executed: failed steps never reach the history."""
    if not state["decisions"]:
        return ""
    decision = state["decisions"][-1]
    labels = {a["id"]: a["label"] for a in state["page"]["actions"]}
    return f" (last decision: {decision['operation']} '{labels.get(decision['choice'], decision['choice'])}')"


def _step(entry):
    text = entry["text"]
    if text is not None and SECRET_FIELD.search(entry["action"]):
        text = "*" * len(text)
    return {
        "step": entry["step"],
        "operation": entry["operation"],
        "action": entry["action"],
        "text": text,
        "probability": round(entry["probability"], 3),
        "decision_ms": entry["latency_ms"],
        "text_ms": entry["text_latency_ms"],
        "page_changed": entry["page_changed"],
    }
