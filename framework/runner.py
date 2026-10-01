"""Drives natural-language goals through jev-ultrafast and keeps a compact record of every step."""

import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from jev_ultrafast import Agent

SECRET_FIELD = re.compile("password", re.IGNORECASE)
INTERACTIVE = {"click", "fill", "select"}


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
    def avg_decision_ms(self):
        return round(sum(self.decision_ms) / len(self.decision_ms)) if self.decision_ms else 0

    def to_dict(self):
        return {**asdict(self), "actions": len(self.steps), "avg_decision_ms": self.avg_decision_ms}


def start_goal(url, goal, *, max_actions, record_dir=None):
    """Opens url in a new tab and runs the goal. Returns the result and the open agent; the caller closes it."""
    agent = Agent(url, goal, record_dir=record_dir)
    return _drive(agent, goal, max_actions), agent


def continue_goal(agent, goal, *, max_actions, record_dir=None):
    """Runs the next goal in the same tab: the page (filled fields included) carries over, the history does not.

    The decision model stops after typing into the last field of a form, so submitting it is a separate goal,
    which only works if the form keeps its values.
    """
    agent.state.update(
        goal=goal, plan=[goal], plan_index=0, history=[], decisions=[], text_calls=[],
        decision=None, status="ready", started_at=None, elapsed_ms=0, record=bool(record_dir),
    )  # fmt: skip
    agent.pending_text = None
    agent.record_dir = Path(record_dir) if record_dir else None
    if agent.record_dir:
        agent.record_dir.mkdir(parents=True, exist_ok=True)
    agent.state["page"] = agent.browser.observe(screenshot=agent.screenshots)
    return _drive(agent, goal, max_actions)


def _drive(agent, goal, max_actions):
    _wait_for_controls(agent)
    status, error = "error", None
    try:
        for state in agent.run():
            if len(state["history"]) >= max_actions and state["status"] not in {"done", "blocked"}:
                status = "budget"
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


def _wait_for_controls(agent, timeout=5):
    """A client-rendered page can be observed before it renders; on an empty page the model answers DONE."""
    deadline = time.monotonic() + timeout
    while not any(a["kind"] in INTERACTIVE for a in agent.state["page"]["actions"]) and time.monotonic() < deadline:
        time.sleep(0.1)
        agent.state["page"] = agent.browser.observe(screenshot=agent.screenshots)


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
