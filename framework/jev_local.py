"""Adapts the pinned jev-ultrafast commit to local models and to login forms.

- decisions go to the local laya-browser server instead of api.typesafe.ai (upstream PR #175);
- password fields become visible to the agent (upstream PR #123);
- TEXT_MODEL_REASONING=none is also sent in the form Ollama honours (upstream PR #39);
- identical labels (six "Add to cart" buttons) get the name of their own item (no upstream PR);
- the text model invents a value the goal does not give, with a session seed that replays it (no upstream PR).

All five patch upstream internals. Each checks that the code it patches still looks as expected,
so a changed pin fails loudly instead of silently testing something else.
"""

import os
import random

from jev_ultrafast import browser, model

TYPESAFE_URL = "https://api.typesafe.ai"
# snapshot.js drops password inputs twice: an explicit filter, and role() giving them no role.
PASSWORD_PATCHES = {
    "['password','file','hidden']": "['file','hidden']",
    "['text','email','url','tel']": "['text','email','url','tel','password']",
}
# Duplicate labels get the visible text of the first link or heading in the largest container that holds only their
# own element. saucedemo's "Add to cart" and "Remove" buttons do not name the item, so the model picked by position;
# visible text, because its accessible link names ("View details for ...") made the model pick those links instead.
# Twins are searched in the whole document: the agent only sees the window, and a lone visible "Remove" was taken
# for the button of an item below it. Links to the same target are not twins: either click does the same.
CONTEXT_PATCH = {
    "  const words=[], walker=": """  const twins=new Map();
  for (const t of document.querySelectorAll(selector)) {
    if (!safe(t) || !visible(t) || t.matches(':disabled')) continue;
    const label=name(t)||role(t);
    if (label) twins.set(label,[...(twins.get(label)||[]),t]);
  }
  for (const a of actions) {
    const e=cache.nodes.get(a.node), others=(twins.get(a.label)||[]).filter(t=>t!==e && !(t.href && t.href===e.href));
    if (a.kind==='select' || !others.length) continue;
    let scope=e;
    while (scope.parentElement && !others.some(t=>scope.parentElement.contains(t))) scope=scope.parentElement;
    const title=[...scope.querySelectorAll('a,h1,h2,h3,h4,h5,h6,[role="heading"]')].map(n=>n.innerText.trim())
      .find(t=>t && !a.label.includes(t));
    if (title) a.label+=' — '+title;
  }
  const words=[], walker=""",
}
# Upstream disables reasoning in OpenRouter's form; Ollama ignores it and needs the OpenAI-style effort.
REASONING_OFF = {"enabled": False}
# Upstream answers null when the goal has no value; "fill in the form" leaves the values to the model.
# Without the placeholder ban gemma types "John Doe" in 7 of 8 seeds.
TEXT_VALUE_PATCHES = {
    " Never invent personal information.": "",
    'If a required value is missing, return {"text": null}. Otherwise return': (
        "If the goal gives no value, invent a realistic test value for the field. Vary invented values: "
        "never use placeholders such as John, Jane, Doe, Smith, 12345 or 90210. Return"
    ),
}


def install():
    if getattr(model.post_json, "local", False):
        return
    _patch_snapshot()
    _patch_text_value()
    _patch_model_requests()


def _patch_snapshot():
    def marker(read_state):
        return f"(() => {{ const state={read_state}; return state?.marker ?? null; }})()"

    read_state, patches = browser.READ_STATE, {**PASSWORD_PATCHES, **CONTEXT_PATCH}
    if browser.MARKER != marker(read_state) or any(read_state.count(old) != 1 for old in patches):
        raise RuntimeError("jev_ultrafast/snapshot.js changed; review the snapshot patches before re-pinning")
    for old, new in patches.items():
        read_state = read_state.replace(old, new)
    browser.READ_STATE = read_state
    browser.MARKER = marker(read_state)


def _patch_text_value():
    text_value = model.TEXT_VALUE
    if any(text_value.count(old) != 1 for old in TEXT_VALUE_PATCHES):
        raise RuntimeError("jev_ultrafast TEXT_VALUE changed; review the text value patch before re-pinning")
    for old, new in TEXT_VALUE_PATCHES.items():
        text_value = text_value.replace(old, new)
    model.TEXT_VALUE = text_value


def _patch_model_requests():
    upstream = model.post_json
    base = os.environ.get("LAYA_URL", "http://127.0.0.1:8791").rstrip("/")
    # The model samples (gemma's default temperature is 1), so every session types new values;
    # the seed is in the report, and TEXT_MODEL_SEED=<seed> replays a session's values.
    seed = int(os.environ.setdefault("TEXT_MODEL_SEED", str(random.randrange(2**31))))

    def post_json(url, key, body):
        if url.endswith("/chat/completions"):
            body = {**body, "seed": seed}
        if body.get("reasoning") == REASONING_OFF:
            body = {**body, "reasoning": {"effort": "none"}}
        return upstream(url.replace(TYPESAFE_URL, base), key, body)

    post_json.local = True
    model.post_json = post_json
    # model.choose() reads the key unconditionally; the local server ignores it.
    os.environ.setdefault("TYPESAFE_API_KEY", "local")
