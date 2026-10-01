"""Offline checks of framework/jev_local.py: a real browser, no models."""

from urllib.parse import quote

from jev_ultrafast import Browser, model

LOGIN_FORM = "<form><input aria-label='Username'><input type='password' aria-label='Password'></form>"


def test_password_field_is_observed(chrome):
    page_browser = Browser("data:text/html," + quote(LOGIN_FORM))
    try:
        labels = [action["label"] for action in page_browser.observe(screenshot=False)["actions"]]
    finally:
        page_browser.close()
    assert any("Password" in label for label in labels), labels


class Response:
    status_code, is_error = 200, False

    def json(self):
        return {}


def test_decisions_go_to_local_server(monkeypatch):
    sent = []
    monkeypatch.setattr(model.CLIENT, "post", lambda url, **_: sent.append(url) or Response())
    model.post_json("https://api.typesafe.ai/v1/systemone", "key", {})
    assert sent == ["http://127.0.0.1:8791/v1/systemone"]


def test_disabled_reasoning_reaches_ollama(monkeypatch):
    sent = []
    monkeypatch.setattr(model.CLIENT, "post", lambda url, json, **_: sent.append(json) or Response())
    model.post_json("http://127.0.0.1:11434/v1/chat/completions", "key", {"reasoning": {"enabled": False}})
    assert sent == [{"reasoning": {"effort": "none"}}]
