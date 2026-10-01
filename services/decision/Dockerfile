FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /bin/

# On Linux torch routes some eager ops to Triton kernels; Triton compiles its CUDA driver shim with a C compiler.
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev && rm -rf /var/lib/apt/lists/*

ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# The CUDA torch wheel bundles its CUDA runtime; the GPU driver comes from the host.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen

COPY serve.py ./

ENV DECISION_HOST=0.0.0.0 DECISION_PORT=8791
EXPOSE 8791
CMD ["uv", "run", "--no-sync", "python", "serve.py"]
