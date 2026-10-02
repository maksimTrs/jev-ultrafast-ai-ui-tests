# Port plan: Windows → macOS (Apple Silicon)

Handoff for a future session on a Mac. The project currently runs only on Windows 11 with an NVIDIA
GPU (locally and in Docker Desktop + WSL2). Goal: a **macOS-only** build — remove the Windows/NVIDIA logic, no hybrid.

Decided by the owner:
- local mode: native Chrome, decision server and Ollama on the Mac;
- Docker mode: tests + Chromium + decision server in containers (CPU), **Ollama native on the Mac** (Metal),
  reached from the containers at `host.docker.internal`. Docker on a Mac has no GPU access at all (neither NVIDIA nor Metal).

## Known blockers (found in the code on Windows, not yet seen on a Mac)

1. `framework/chrome.py` `KNOWN_PATHS` has only Windows/Linux paths → `Chrome not found; set CHROME_PATH`.
2. `services/decision/pyproject.toml` takes torch only from the CUDA index (`pytorch-cu126`); `services/decision/uv.lock`
   has torch wheels only for `win_amd64` and `manylinux` → `uv run --project services/decision ...` fails on macOS.
3. `compose.yaml` reserves an NVIDIA GPU for `decision` and `ollama` → those services cannot start on a Mac.

## Windows/NVIDIA logic to remove or replace

| Where | What | Action |
|---|---|---|
| `framework/chrome.py` `KNOWN_PATHS` | Windows Chrome paths | replace with `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`; Docker keeps `CHROME_PATH=/usr/bin/chromium` from the Dockerfile |
| `framework/chrome.py` `_stop_daemon` | `PermissionError` retry (Windows port-file race) | run the suite 3× without it; remove if no error. browser-harness has a separate `darwin` branch in `admin.py` |
| `.env.example` | commented Windows `CHROME_PATH` example | macOS example |
| `services/decision/pyproject.toml` | `[tool.uv.sources]` torch → `pytorch-cu126` index | drop the custom index: torch from PyPI (macOS arm64 wheels, MPS). **Verify** that PyPI's `linux/aarch64` wheel used in the Docker image is CPU-only and small; if it pulls CUDA packages, use `https://download.pytorch.org/whl/cpu` with `marker = "sys_platform == 'linux'"` |
| `services/decision/uv.lock` | Windows/Linux CUDA wheels | `uv lock --project services/decision` after the change |
| `services/decision/Dockerfile` | `gcc libc6-dev` for Triton (CUDA torch on Linux) | check whether the CPU torch still needs it (decision server must not answer HTTP 400); remove if not |
| `compose.yaml` | `x-gpu` anchor, `<<: *gpu`, `ollama`, `ollama-init`, volume `ollama-models` | remove; `tests` env `TEXT_MODEL_BASE_URL: http://host.docker.internal:11434/v1`; `tests` depends only on `decision` |
| `README.md` | Windows/WSL2/NVIDIA wording, results table "Local (Windows)", Triton note, Windows race pitfall, model locations table (Ollama volume) | rewrite for macOS; re-measure the results table |

## Must verify on the Mac

- [ ] laya picks MPS by itself (`laya.load(..., device=None)`; laya has MPS handling in `laya/agent.py`). Measure ms per decision.
- [ ] Ollama native: `ollama pull gemma4:e4b`; reasoning-off still honoured (`{"effort": "none"}` → ~0.2 s per field,
      not seconds). Tested only with Ollama 0.35.0.
- [ ] Containers reach the host Ollama at `host.docker.internal:11434`. If the Mac's Ollama listens only on
      `127.0.0.1` and the request fails, set `OLLAMA_HOST=0.0.0.0` for the Ollama app (Ollama FAQ: `launchctl setenv`).
- [ ] Docker Desktop memory limit is enough for Chromium + the decision server (raise it in Docker Desktop settings if not).
- [ ] Chrome's leaked-password dialog stays off with the profile prefs on macOS (`PROFILE_PREFS` in `chrome.py`).
- [ ] The two-blank-tabs fix holds (startup tab closed, agent tab brought to front).

## Steps (each with its check)

1. **Local Chrome** — `KNOWN_PATHS` for macOS, `.env.example`.
   Check: `uv sync && uv run pytest -m "not live"` → all passed.
2. **Decision server** — torch from PyPI, re-lock.
   Check: `uv run --project services/decision python services/decision/serve.py`; `curl http://127.0.0.1:8791/` → `{"ok": true, ...}`.
3. **Local live run** — `ollama pull gemma4:e4b`, `cp .env.example .env`, `uv run --env-file .env pytest`.
   Check: all passed, 3 runs in a row; then remove the `PermissionError` retry and repeat 3×.
4. **Docker** — `compose.yaml` without GPU/Ollama services, decision Dockerfile.
   Check: `docker compose run --rm --service-ports tests` → all live passed; browser visible at `http://localhost:7900/vnc.html`;
   `./reports/report.html` on the host.
5. **Docs** — README: requirements, commands, results table with Mac numbers, pitfalls, model locations.
   Check: no "Windows", "WSL", "NVIDIA", "cu126" left in the repo unless historical (`grep -ri`).
