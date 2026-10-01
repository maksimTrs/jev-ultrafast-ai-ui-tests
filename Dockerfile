FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /bin/

# chromium + a virtual display (xvfb) streamed to the host browser through noVNC; git for the jev-ultrafast pin.
RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium xvfb x11vnc novnc websockify git \
    && rm -rf /var/lib/apt/lists/*

ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Dependencies before code: editing tests does not reinstall them.
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen

COPY framework framework
COPY tests tests
COPY --chmod=755 docker/entrypoint.sh /entrypoint.sh

# Chromium runs as root in the container, which requires --no-sandbox.
ENV CHROME_PATH=/usr/bin/chromium CHROME_EXTRA_ARGS=--no-sandbox DISPLAY=:99 RUN_MODE=docker
EXPOSE 7900
ENTRYPOINT ["/entrypoint.sh"]
CMD ["-m", "live"]
