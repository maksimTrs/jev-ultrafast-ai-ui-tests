"""Offline checks of framework/runner.py: no models."""

import time
from typing import ClassVar

import pytest
from jev_ultrafast import Agent
from jev_ultrafast.browser import StalePage

from framework import runner


@pytest.fixture
def agent(chrome):
    agent = Agent("data:text/html,<button>Go</button>", "Click Go.")
    yield agent
    agent.close()


def test_runner_knows_the_pinned_agent_state(agent):
    assert set(agent.state) == runner.STATE_KEYS


def test_continue_goal_refuses_an_unknown_agent_state(agent):
    # A key added upstream would carry the previous goal's value into the next one.
    agent.state["added_upstream"] = None

    with pytest.raises(RuntimeError, match="Agent.state changed"):
        runner.continue_goal(agent, "Click Go.", max_actions=1)


PAGE = {"url": "data:,", "fingerprint": "f", "actions": [{"id": "e1", "kind": "click", "label": "Go"}]}


class Deciding:
    """An agent on a one-button page, sure which button (0.99); CLICK at the given probability, else DONE."""

    def __init__(self, click, navigating=0):
        self.browser, self.screenshots, self.acted = self, False, 0
        self.navigating = navigating  # how many observes find the page mid-navigation
        self.operations = {"CLICK": click, "DONE": 1 - click}
        self.state = {
            "status": "ready", "started_at": time.perf_counter(), "elapsed_ms": 0,
            "decisions": [], "history": [], "page": PAGE,
        }  # fmt: skip

    def observe(self, screenshot):
        if self.navigating:
            self.navigating -= 1
            raise StalePage("Document is navigating")
        return PAGE

    def command(self, name, body=None):
        if name == "act":
            self.acted += 1
            self.state["history"].append({
                "step": self.acted, "operation": "CLICK", "action": "Go", "text": None, "probability": 0.99,
                "latency_ms": 1, "text_latency_ms": 0, "page_changed": False,
            })  # fmt: skip
            return
        decision = {
            "choice": "e1", "operation": "CLICK", "target": "1", "latency_ms": 1,
            "operation_probabilities": self.operations, "target_probabilities": {"1": 0.99},
        }  # fmt: skip
        self.state["decision"] = decision
        self.state["decisions"].append(decision)


def test_unsure_operation_stops_the_step_despite_a_sure_target():
    agent = Deciding(click=0.45)

    stop = runner._tick(agent)

    assert stop and stop.startswith("probability 0.44"), stop
    assert not agent.acted


def test_sure_step_runs_and_reports_the_checked_probability():
    agent = Deciding(click=0.9)

    assert runner._tick(agent) is None
    assert agent.acted
    assert agent.state["history"][-1]["probability"] == pytest.approx(0.9 * 0.99)


def test_action_budget_ends_the_run():
    result = runner._drive(Deciding(click=0.9), "Click Go.", max_actions=2)

    assert (result.status, len(result.steps)) == ("budget", 2), result.outcome


def test_navigating_page_is_observed_until_it_settles():
    # The previous goal may end on a click that starts a navigation.
    result = runner._drive(Deciding(click=0.9, navigating=2), "Click Go.", max_actions=1)

    assert result.status == "budget", result.outcome


def test_report_masks_what_was_typed_into_a_password_field():
    typed = {
        "step": 1, "operation": "TYPE_TEXT", "text": "secret_sauce", "probability": 0.9,
        "latency_ms": 1, "text_latency_ms": 1, "page_changed": False,
    }  # fmt: skip

    assert runner._step({**typed, "action": "Password"})["text"] == "*" * len("secret_sauce")
    assert runner._step({**typed, "action": "Username"})["text"] == "secret_sauce"


class BrokenTab:
    """An agent whose tab opened but rejects the first CDP call."""

    opened: ClassVar[list] = []

    def __init__(self, url, goal, record_dir=None):
        self.browser, self.closed = self, False
        self.opened.append(self)

    def call(self, method, **params):
        raise RuntimeError("target crashed")

    def close(self):
        self.closed = True


def test_start_goal_closes_the_tab_when_setup_fails(monkeypatch):
    monkeypatch.setattr(runner, "Agent", BrokenTab)

    with pytest.raises(RuntimeError, match="target crashed"):
        runner.start_goal("about:blank", "goal", max_actions=1)

    assert BrokenTab.opened[-1].closed
