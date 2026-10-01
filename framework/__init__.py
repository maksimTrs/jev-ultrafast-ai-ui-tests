"""Browser Harness reads its settings at import time, so they are fixed here, before jev_ultrafast is imported."""

import os

CDP_PORT = int(os.environ.get("CHROME_CDP_PORT", "9333"))
HARNESS_NAME = os.environ.setdefault("BU_NAME", "jev-tests")

# Tests own their browser: never attach to the user's Chrome or a remote one.
os.environ.pop("BU_CDP_WS", None)
os.environ["BU_CDP_URL"] = f"http://127.0.0.1:{CDP_PORT}"
os.environ.setdefault("BH_TELEMETRY", "0")
