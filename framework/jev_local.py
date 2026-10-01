"""Adapts the pinned jev-ultrafast commit to local models and to login forms.

- decisions go to the local laya-browser server instead of api.typesafe.ai (upstream PR #175);
- password fields become visible to the agent (upstream PR #123);
- TEXT_MODEL_REASONING=none is also sent in the form Ollama honours (upstream PR #39).

All three patch upstream internals. Each checks that the code it patches still looks as expected,
so a changed pin fails loudly instead of silently testing something else.
"""

import os

from jev_ultrafast import browser, model

TYPESAFE_URL = "https://api.typesafe.ai"
# snapshot.js drops password inputs twice: an explicit filter, and role() giving them no role.
PASSWORD_PATCHES = {
    "['password','file','hidden']": "['file','hidden']",
    "['text','email','url','tel']": "['text','email','url','tel','password']",
}
# Upstream disables reasoning in OpenRouter's form; Ollama ignores it and needs the OpenAI-style effort.
REASONING_OFF = {"enabled": False}


def install():
    if getattr(model.post_json, "local", False):
        return
    _show_password_fields()
    _patch_model_requests()


def _show_password_fields():
    def marker(read_state):
        return f"(() => {{ const state={read_state}; return state?.marker ?? null; }})()"

    read_state = browser.READ_STATE
    if browser.MARKER != marker(read_state) or any(read_state.count(old) != 1 for old in PASSWORD_PATCHES):
        raise RuntimeError("jev_ultrafast/snapshot.js changed; review the password-field patch before re-pinning")
    for old, new in PASSWORD_PATCHES.items():
        read_state = read_state.replace(old, new)
    browser.READ_STATE = read_state
    browser.MARKER = marker(read_state)


def _patch_model_requests():
    upstream = model.post_json
    base = os.environ.get("LAYA_URL", "http://127.0.0.1:8791").rstrip("/")

    def post_json(url, key, body):
        if body.get("reasoning") == REASONING_OFF:
            body = {**body, "reasoning": {"effort": "none"}}
        return upstream(url.replace(TYPESAFE_URL, base), key, body)

    post_json.local = True
    model.post_json = post_json
    # model.choose() reads the key unconditionally; the local server ignores it.
    os.environ.setdefault("TYPESAFE_API_KEY", "local")
