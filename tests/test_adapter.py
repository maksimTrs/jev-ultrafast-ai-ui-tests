"""Offline checks of framework/jev_local.py: a real browser, no models."""

import os
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


PRODUCT_LIST = (
    "<div><a href='#a'>Backpack</a><button>Add to cart</button></div>"
    "<div><a href='#b'>Onesie</a><button>Add to cart</button></div>"
)


def test_identical_labels_get_item_context(chrome):
    page_browser = Browser("data:text/html," + quote(PRODUCT_LIST))
    try:
        labels = [action["label"] for action in page_browser.observe(screenshot=False)["actions"]]
    finally:
        page_browser.close()
    assert {"Add to cart — Backpack", "Add to cart — Onesie"} <= set(labels), labels


# The agent only sees elements inside the window; the Onesie button is below it.
OFFSCREEN_TWIN = (
    "<div><a href='#a'>Backpack</a><button>Remove</button></div><div style='height:3000px'></div>"
    "<div><a href='#b'>Onesie</a><button>Remove</button></div>"
)


def test_visible_label_gets_item_context_when_its_twin_is_offscreen(chrome):
    page_browser = Browser("data:text/html," + quote(OFFSCREEN_TWIN))
    try:
        labels = [action["label"] for action in page_browser.observe(screenshot=False)["actions"]]
    finally:
        page_browser.close()
    assert "Remove — Backpack" in labels and "Onesie" not in labels, labels


# Repeated links to one target (footnotes, a term linked twice) are not ambiguous: either click does the same.
SAME_TARGET = "<div><h2>Intro</h2><a href='#note-1'>[1]</a></div><div><h2>History</h2><a href='#note-1'>[1]</a></div>"


def test_links_to_the_same_target_keep_their_label(chrome):
    page_browser = Browser("data:text/html," + quote(SAME_TARGET))
    try:
        labels = [action["label"] for action in page_browser.observe(screenshot=False)["actions"]]
    finally:
        page_browser.close()
    assert labels.count("[1]") == 2, labels


class Response:
    status_code, is_error = 200, False

    def json(self):
        return {}


def test_decisions_go_to_local_server(monkeypatch):
    sent = []
    monkeypatch.setattr(model.CLIENT, "post", lambda url, **_: sent.append(url) or Response())
    model.post_json("https://api.typesafe.ai/v1/systemone", "key", {})
    assert sent == [os.environ.get("LAYA_URL", "http://127.0.0.1:8791").rstrip("/") + "/v1/systemone"]


def test_disabled_reasoning_reaches_ollama(monkeypatch):
    sent = []
    monkeypatch.setattr(model.CLIENT, "post", lambda url, json, **_: sent.append(json) or Response())
    model.post_json("http://127.0.0.1:11434/v1/chat/completions", "key", {"reasoning": {"enabled": False}})
    assert sent[0]["reasoning"] == {"effort": "none"}


def test_text_requests_carry_the_session_seed(monkeypatch):
    sent = []
    monkeypatch.setattr(model.CLIENT, "post", lambda url, json, **_: sent.append(json) or Response())
    model.post_json("http://127.0.0.1:11434/v1/chat/completions", "key", {})
    assert sent == [{"seed": int(os.environ["TEXT_MODEL_SEED"])}]


def test_text_model_invents_values_the_goal_does_not_give():
    assert "Never invent" not in model.TEXT_VALUE and "invent a realistic test value" in model.TEXT_VALUE
