#!/bin/sh
# Starts a virtual display viewable at http://localhost:7900/vnc.html (unless --headless), then runs pytest.
set -e

case " $* " in
  *" --headless "*) ;;
  *)
    Xvfb :99 -screen 0 1280x900x24 -nolisten tcp &
    for _ in $(seq 100); do [ -e /tmp/.X11-unix/X99 ] && break; sleep 0.1; done
    [ -e /tmp/.X11-unix/X99 ] || { echo "Xvfb did not start within 10 s" >&2; exit 1; }
    x11vnc -display :99 -forever -shared -nopw -localhost -quiet >/dev/null 2>&1 &
    websockify --web /usr/share/novnc 7900 localhost:5900 >/dev/null 2>&1 &
    echo "Browser view: http://localhost:7900/vnc.html"
    ;;
esac

exec uv run --no-sync pytest "$@"
