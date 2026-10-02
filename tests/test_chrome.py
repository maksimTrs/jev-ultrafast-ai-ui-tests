"""Offline checks of framework/chrome.py."""

import socket

import pytest

from framework import chrome


def test_busy_cdp_port_fails_before_launch(monkeypatch):
    with socket.socket() as listener:
        listener.bind((chrome.CDP_HOST, 0))
        listener.listen()
        monkeypatch.setattr(chrome, "CDP_PORT", listener.getsockname()[1])
        with pytest.raises(RuntimeError, match="already in use"):
            chrome.Chrome(headless=True)
