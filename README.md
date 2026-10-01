# jev-ultrafast AI Framework for UI Tests

Selector-free UI tests for [saucedemo.com](https://www.saucedemo.com/): a test states a goal in natural language,
and a "System 1" decision model (one forward pass, no text generation) picks the operation and the page element.
The verdict comes from a deterministic check of the real DOM, not from the model.

Everything runs locally: no cloud TypeSafe Jev, no external LLM APIs.

> [!WARNING]
> ⚠️ **Tested only on Windows 11 + NVIDIA GPU** (locally and in Docker Desktop + WSL2). macOS is not supported yet — see [Limitations](#limitations).

## Why

### Context

In September 2026 browser-use released [jev-ultrafast](https://github.com/browser-use/jev-ultrafast), a browser agent
that does not generate actions token by token like typical LLM agents. Decisions come from a "System 1" model
(TypeSafe Jev): in a single forward pass it chooses an operation (CLICK, TYPE_TEXT, SELECT, DONE, ...) and an element
from those actually observed on the page. In effect it is a "smart if": it picks from given options instead of
composing an answer. A small LLM is involved only when text has to be typed.

Cloud Jev is waitlisted and paid, so this project uses an open alternative,
[laya-browser](https://huggingface.co/cklxx/laya-browser), fine-tuned for exactly the requests jev-ultrafast sends.

### What was done

1. Studied jev-ultrafast, browser-harness, laya and its browser fine-tune.
2. Replaced cloud Jev with a local decision server (laya-browser on GPU) and the text LLM with a local `gemma4:e4b` in Ollama.
3. Wrapped it all in a pytest framework: isolated Chrome, fixtures, independent DOM checks, an HTML report with the agent's steps.
4. Two ways to run: locally and with `docker compose` (GPU in containers, the browser visible through noVNC).
5. Ran three happy-path saucedemo scenarios. Limitations of the model, jev-ultrafast and the environment found along
   the way, and their workarounds, are documented below: they are the main practical outcome of the experiment.

### How it differs

| | Selenium / Playwright | LLM agents (browser-use etc.) | This framework |
|---|---|---|---|
| A step is defined by | selector + action in code | natural-language goal | natural-language goal |
| What the model can do | — | generate any action, including a non-existent one | only choose among observed elements |
| Time per decision | instant | text generation on every step | 25–150 ms (see results) |
| Explainability | stack trace and selector | the model's reasoning as text | probability of every decision in the report |
| Where it runs | locally | usually a cloud API | locally, page data never leaves the machine |

What makes it promising:

- **No locators.** A test describes user intent, not DOM structure, so there are no selectors to maintain.
  Expected (not measured in this experiment): such tests are more robust to markup changes and more sensitive to changes
  in visible text, since the model sees the page the way a user does.
- **Choosing instead of generating.** The model cannot invent a selector or click a non-existent button:
  every action is an element from the page snapshot, re-validated right before execution.
- **Speed and cost.** Tens of milliseconds per decision on a local GPU, no per-token billing.
- **Measurable confidence.** Every decision carries a probability, so a threshold can be applied and doubtful steps
  show up in the report.

The downsides, honestly: goals have to be phrased for the model, long scenarios have to be split into steps,
and without a confidence threshold the agent sometimes takes extra actions. For CI regression suites the classic
frameworks are still more reliable. This project is a working template and a test bed for the approach, not a replacement.

## Architecture

```
pytest ── framework/runner.py ── jev_ultrafast.Agent (observe → decide → act)
                                   ├─ decide: POST /v1/systemone  → laya-browser :8791   (services/decision, torch + CUDA)
                                   ├─ type:   POST /v1/chat/completions → Ollama :11434 (gemma4:e4b)
                                   └─ act:    CDP via browser-harness → isolated Chrome :9333 (temporary profile)
```

| Component | What it is | Why |
|---|---|---|
| [jev-ultrafast](https://github.com/browser-use/jev-ultrafast) | the agent loop: page snapshot → indexed elements → operation + target → execution | the model only chooses among observed elements and never generates selectors or code |
| [cklxx/laya-browser](https://huggingface.co/cklxx/laya-browser) | a fine-tuned [laya](https://github.com/NandhaKishorM/laya) (mmBERT, 322M) speaking Jev's `/v1/systemone` protocol | a local replacement for Jev; base laya scores ≈ 0% on browser decisions without fine-tuning |
| Ollama + `gemma4:e4b` | writes the field value when TYPE_TEXT is chosen | OpenAI-compatible API, so jev connects through env variables, no code |
| `framework/chrome.py` | a dedicated Chrome: own CDP port, temporary profile, prefs | the user's browser is never touched; see "Pitfalls" |
| `framework/jev_local.py` | three targeted patches of the pinned jev-ultrafast commit | see below |

### jev-ultrafast patches (`framework/jev_local.py`)

Upstream is pinned to commit `1231850a`. Each patch first checks that the code it changes looks as expected.
If the code changed after a re-pin, the run fails with a clear error instead of silently testing something else.

1. Decision requests go to `LAYA_URL` instead of `api.typesafe.ai`, which is hard-coded upstream (open PR #175).
2. `type=password` fields become visible to the agent: upstream hides them twice, which makes login impossible (PR #123).
3. `TEXT_MODEL_REASONING=none` is also sent as `{"effort": "none"}`. Otherwise Ollama ignores the reasoning switch
   and gemma "thinks" for up to 9 seconds per field (PR #39).

## Running locally

Requires [uv](https://docs.astral.sh/uv/), Chrome, Ollama (tested with 0.35.0; desktop app or CLI, same server)
and an NVIDIA GPU (CPU works too, but slower).

```bash
# 1. decision server: keep it running in a separate terminal
#    (own environment with torch; the first start downloads ~0.7 GB of weights)
uv run --project services/decision python services/decision/serve.py

# 2. text model
ollama pull gemma4:e4b

# 3. tests
cp .env.example .env
uv run pytest -m "not live"            # offline adapter checks, no models needed
uv run --env-file .env pytest          # everything, in a visible Chrome window
uv run --env-file .env pytest --headless --record-steps
```

If the decision server is not running, the live tests stop before opening the browser with
`Decision server not reachable at ... Start it in another terminal: ...`.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `LAYA_URL` | `http://127.0.0.1:8791` | decision server |
| `TEXT_MODEL_BASE_URL`, `TEXT_MODEL`, `TEXT_MODEL_API_KEY` | Ollama, `gemma4:e4b`, `ollama` | any OpenAI-compatible endpoint for TYPE_TEXT |
| `TEXT_MODEL_REASONING` | `none` | turns off the text model's "thinking" |
| `CHROME_PATH` | standard Chrome/Chromium locations | a custom browser binary |
| `CHROME_EXTRA_ARGS` | empty (`--no-sandbox` in Docker) | extra Chrome flags |
| `CHROME_CDP_PORT` | `9333` | CDP port of the isolated Chrome |

pytest flags: `--headless` (no window), `--record-steps` (a frame after every action; included in the report for failed tests).

## Running in Docker

```bash
docker compose run --rm --service-ports tests              # live tests, browser visible at http://localhost:7900/vnc.html
docker compose run --rm tests -m live --headless           # no display
docker compose down                                        # stop decision and ollama
```

`tests` starts `decision` and `ollama` on its own. The `ollama-init` service downloads the model into a volume once.
The report appears on the host in `./reports` (bind mount). Only noVNC is published, and only on `127.0.0.1`.
Requires an NVIDIA GPU: `compose.yaml` reserves one for `decision` and `ollama`.
The GPU is passed through Docker Desktop + WSL2: on Windows only the NVIDIA driver is needed.
Everything else is inside the containers (Ollama pinned to 0.35.0), so a host Ollama and its settings do not matter.
The first run downloads ~7 GB of weights; later runs reuse the volumes. The `decision` image is ~11 GB, ~7 GB of it torch with CUDA.

### Where the models live and how to remove everything

| What | Where | Size |
|---|---|---|
| laya-browser checkpoint (local) | Hugging Face cache: `~/.cache/huggingface/hub` | ~0.7 GB |
| `gemma4:e4b` (local) | Ollama model directory (`OLLAMA_MODELS` or the path in Ollama settings) | ~6.6 GB |
| Docker images | `ai-at-framework-decision`, `ai-at-framework-tests` | ~11 GB and ~1.7 GB |
| models in Docker | volumes `ai-at-framework_hf-cache`, `ai-at-framework_ollama-models` | ~7 GB |

```bash
docker compose down -v                                                   # containers + model volumes
docker image rm ai-at-framework-decision ai-at-framework-tests
ollama rm gemma4:e4b
```

## Writing a test

The `jev` fixture is `JevSession` from `tests/conftest.py`. `start()` opens a page and runs a goal,
`then()` runs the next goal in the same tab. Both return the run result and the live page,
and the check is a plain `assert` against the real DOM:

```python
def test_login(jev):
    result, page = jev.start("/", "Enter username standard_user and password secret_sauce, then click Login.",
                             max_actions=6)
    assert page.evaluate("location.pathname") == "/inventory.html", result.outcome  # status + agent error
```

Rules for phrasing goals (found experimentally, see below):

- one short goal per action or per form; long scenarios as a chain of `then()` calls with a check after each step;
- explicit verbs and element names as they appear on the page: "Enter ..., then click Login.", "Click Checkout.";
- submit a form as a separate goal after typing (`then("Click Continue.")`);
- set `max_actions` slightly above the minimum needed: extra steps show up in the report, and a loop stops
  with status `budget`;
- the agent's status (`done`) is not a verdict. Check the result on the page or in `localStorage`;
- prepare preconditions that the test does not verify without the agent (e.g. the `logged_in` fixture sets a cookie).

## Report

`reports/report.html` is a single self-contained file (pytest-html). The results table has columns for the agent status,
number of actions, agent time and average decision latency. Each test card shows, for every agent run:
the goal, a step table (operation, element, typed text, probability, decision and text ms) and the final screenshot.
Passwords are masked. With `--record-steps`, failed tests also get a frame after every action.
Raw data for every run is in `reports/artifacts/<test>/run-N/run.json`.

## Results (RTX 4090 Laptop)

All tests passed 3 out of 3 in every mode. Times are agent work, excluding browser start-up:

| Test | Goals | Agent actions | Local (Windows) | Docker (Linux) |
|---|---|---|---|---|
| `test_login` | 1 | 3 | 1.5–2.2 s | 0.7 s |
| `test_add_backpack_to_cart` | 1 | 2 (one unnecessary) | 0.5–1 s | 0.2 s |
| `test_full_checkout` | 6 | 15 | 4.5–6 s | 2.6 s |
| Decision model, per decision | | | 40–150 ms | 25–40 ms |

In the Linux container torch runs some operations as Triton kernels, which makes decisions 2–4× faster than on Windows.
Agent time includes decisions, typing (~150–200 ms per field with gemma's reasoning off) and waiting for the page.

### Why the text model is `gemma4:e4b`

The text model only copies a value from the goal into the field ("standard_user", "John", "12345"), so smaller models
were tried. Benchmark: jev's own `field_text()` on the five saucedemo fields, 10 rounds, reasoning off, warm model:

| Model | Disk | Correct | Median per field | Verdict |
|---|---|---|---|---|
| `gemma3:1b` | 0.8 GB | 10/50 | 185 ms | ❌ types the password into Username, "the field value" |
| `qwen3.5:2b-q4_K_M` | 1.9 GB | 40/50 | 84 ms | ❌ "Doe" into First Name, broken JSON |
| `gemma4:e2b-it-qat` | 4.3 GB | 35/50 | 95 ms | ❌ "Click Checkout", "Swag Labs" as values |
| `qwen3:4b-instruct` | 2.5 GB | 50/50 | 188 ms | ✅ live 3/3, but only with an 8K context (below) |
| `gemma4:e4b` | 6.6 GB | 50/50 | 119 ms | ✅ live 3/3 — the default |

Models under ~4B parameters confuse the fields. `qwen3:4b-instruct` works but depends on Ollama's context setting:
with a 128K context its KV cache takes 23 GB and spills to the CPU (344 ms per field), so it needs a model alias
with `PARAMETER num_ctx 8192`. gemma4 mostly uses 512-token sliding-window attention and is not affected,
which is why it stays the default: it works with any Ollama settings.

### What we learned about the model

- **Phrasing matters.** "Log in with username ... and password ..." → the model presses Login on an empty form right away.
  "Enter username ... and password ..., then click Login." → correct (probabilities 0.93–0.98).
- **Long goals fail.** Checkout as a single goal never passed: after filling in the login form the model kept typing
  into Username. This matches the laya-browser model card: 20–26% on real multi-step tasks.
  So checkout is a chain of short goals in one tab (`jev.then(...)`), with a page check after each.
- **The model does not submit a form after typing.** After the last field it answers DONE whatever the phrasing,
  so `Click Continue.` is a separate goal. That is why continuing in the same tab is needed:
  a new tab would lose the typed values.
- **Ambiguous labels.** The page has six "Add to cart" buttons with the same label. The model clicks the first one
  (which happens to be the Backpack) and then makes an extra "View details" click with probability 0.18. The test passes
  because it checks the cart, but the extra step is visible in the report. The jev loop has no confidence threshold.
- **The cart icon** has the accessible name "Cart, 1 items": "Click the shopping cart." works (0.96),
  while "Go to the cart." makes the model scroll.

## Pitfalls (already handled)

- **Chrome's leaked-password dialog.** `secret_sauce` is in breach lists, so after login Chrome asynchronously opens
  a modal "change your password" dialog. It swallows clicks on the page and tests fail at random.
  `--disable-features=PasswordLeakDetection` does not help; profile prefs do (`PROFILE_PREFS` in `chrome.py`):
  clicks worked 0/4 without them and 4/4 with them.
- **A background tab in headless mode** may never paint, and `Page.captureScreenshot` hangs: the tab is brought
  to the front before the screenshot.
- **Client-side rendering.** A page can be snapshotted before React renders it, and on an empty page the model
  answers DONE. The runner waits for interactive elements to appear.
- **Import order.** browser-harness reads `BU_NAME`/`BU_CDP_URL` at import time, so they are set
  in `framework/__init__.py`. Do not import `browser_harness` directly in tests.
- **A race on Windows** when stopping the harness daemon (`PermissionError` on the port file): the stop is retried.
- **Triton in the Linux image.** On Linux torch 2.14 routes some eager operations to Triton kernels, and on first use
  Triton builds its driver with a C compiler. Without `gcc` in the image the decision server answers HTTP 400.
- **gemma's cold load** (20–40 s) exceeds jev's 25-second timeout, and Ollama aborts a load when the client disconnects.
  So the session starts with a warm-up through a direct request with a long timeout.

## Limitations

- Tested only on Windows 11 with an NVIDIA GPU, locally and in Docker Desktop + WSL2. macOS is not supported yet:
  Chrome paths, the CUDA-only torch index and the GPU reservation in `compose.yaml` are Windows/NVIDIA-specific.
- The model acts without a confidence threshold. Flakiness on ambiguous pages is caught only by the test assertions.
- jev-ultrafast is an MVP: shadow DOM, iframes, file uploads and pop-up windows are not supported.
- Goals are written for the model, not for a human. That is the price of a 322M model deciding in tens of milliseconds.

## Next steps

- **Confidence threshold.** Stop the agent with status `blocked` when the chosen action's probability is below
  a threshold (e.g. 0.5): the 0.18 extra click in `test_add_backpack_to_cart` would become an explicit failure
  instead of a silent step.
- **Comparison with the classics.** The same three scenarios in Playwright, to compare speed and maintenance cost.
- **Negative scenarios** (`locked_out_user`, empty form fields): check whether the model recognises error messages.
- **Upstream updates.** Once PRs #175/#123/#39 are merged into jev-ultrafast, the matching patches in
  `framework/jev_local.py` can be removed.
