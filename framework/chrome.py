"""An isolated Chrome for the test session: own temp profile and CDP port, never the user's browser."""

import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from browser_harness.admin import ensure_daemon, restart_daemon
from browser_harness.helpers import cdp

from framework import CDP_PORT, HARNESS_NAME

KNOWN_PATHS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/chromium",
    "/usr/bin/google-chrome",
)
# Test passwords such as secret_sauce are in breach lists: Chrome then opens a modal "change your password"
# dialog after login (asynchronously, so tests fail at random) that swallows input to the page.
PROFILE_PREFS = {
    "credentials_enable_service": False,
    "profile": {"password_manager_enabled": False, "password_manager_leak_detection": False},
}


def chrome_path():
    if path := os.environ.get("CHROME_PATH"):
        return path
    for path in KNOWN_PATHS:
        if Path(path).exists():
            return path
    raise RuntimeError("Chrome not found; set CHROME_PATH")


class Chrome:
    def __init__(self, headless=False):
        self.profile = tempfile.mkdtemp(prefix="jev-chrome-")
        (Path(self.profile) / "Default").mkdir()
        (Path(self.profile) / "Default" / "Preferences").write_text(json.dumps(PROFILE_PREFS), encoding="utf-8")
        args = [
            chrome_path(),
            f"--remote-debugging-port={CDP_PORT}",
            f"--user-data-dir={self.profile}",
            "--no-first-run",
            "--no-default-browser-check",
            *shlex.split(os.environ.get("CHROME_EXTRA_ARGS", "")),
            *(["--headless=new"] if headless else []),
            "about:blank",
        ]
        self.process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.version = self._wait_for_cdp()
        startup_tabs = self._page_ids()
        ensure_daemon()  # the harness daemon relays every cdp() call to this browser; it opens its own tab
        for target_id in startup_tabs:  # the launch tab is unused: agents open their own
            cdp("Target.closeTarget", targetId=target_id)

    def _wait_for_cdp(self, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"Chrome exited with code {self.process.returncode} before CDP was ready")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=1) as response:
                    return json.load(response)["Browser"]
            except OSError:
                time.sleep(0.2)
        self.close()
        raise RuntimeError(f"Chrome CDP did not open on port {CDP_PORT} within {timeout}s")

    def _page_ids(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/list", timeout=5) as response:
            return [target["id"] for target in json.load(response) if target["type"] == "page"]

    def clear_origin(self, origin):
        cdp("Storage.clearDataForOrigin", origin=origin, storageTypes="all")

    def set_cookie(self, **cookie):
        cdp("Storage.setCookies", cookies=[cookie])

    def close(self):
        try:
            self._stop_daemon()
        finally:
            # A failed daemon stop must not orphan Chrome or its profile.
            self._stop_process()
            self._remove_profile()

    def _stop_daemon(self):
        """Stops the harness daemon holding this browser's CDP websocket.

        On Windows the exiting daemon deletes its port file while restart_daemon() deletes it too, which can
        raise PermissionError; a retry finds the daemon gone and the file removed.
        """
        for attempt in range(3):
            try:
                return restart_daemon(HARNESS_NAME)
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.5)

    def _stop_process(self):
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()

    def _remove_profile(self):
        # Chrome child processes can hold profile files for a moment after the browser exits.
        for _ in range(20):
            shutil.rmtree(self.profile, ignore_errors=True)
            if not Path(self.profile).exists():
                return
            time.sleep(0.25)
