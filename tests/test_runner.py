"""Offline checks of framework/runner.py: no models."""

from typing import ClassVar

import pytest
from jev_ultrafast import Agent

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
