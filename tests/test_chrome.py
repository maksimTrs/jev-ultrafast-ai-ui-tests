"""Offline checks of framework/chrome.py."""

import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from framework import chrome


def test_busy_cdp_port_fails_before_launch(monkeypatch):
    with socket.socket() as listener:
        listener.bind((chrome.CDP_HOST, 0))
        listener.listen()
        monkeypatch.setattr(chrome, "CDP_PORT", listener.getsockname()[1])
        with pytest.raises(RuntimeError, match="already in use"):
            chrome.Chrome(headless=True)


def test_harness_daemon_is_never_the_users():
    # ensure_daemon() reuses any live daemon of this name, whichever browser it holds.
    env = {**os.environ, "BU_NAME": "default", "CHROME_CDP_PORT": "9444"}
    name = subprocess.run(
        [sys.executable, "-c", "import os, framework; print(os.environ['BU_NAME'])"],
        cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip

    assert name == "jev-tests-9444"


def test_failed_start_leaves_no_chrome(monkeypatch, tmp_path):
    # A Chrome left running keeps its CDP port, and every later run stops at the busy port check.
    with socket.socket() as free:
        free.bind((chrome.CDP_HOST, 0))
        port = free.getsockname()[1]
    monkeypatch.setattr(chrome, "CDP_PORT", port)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(chrome, "restart_daemon", lambda name: None)  # keep the session's daemon alive

    def daemon_fails():
        raise RuntimeError("daemon did not start")

    monkeypatch.setattr(chrome, "ensure_daemon", daemon_fails)

    with pytest.raises(RuntimeError, match="daemon did not start"):
        chrome.Chrome(headless=True)

    with socket.socket() as probe:
        assert probe.connect_ex((chrome.CDP_HOST, port)) != 0, "Chrome still serves CDP"
    assert not list(tmp_path.iterdir()), "temp profile left behind"
