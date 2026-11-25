FROM ghcr.io/astral-sh/uv:0.13.7-python3.14-trixie-slim@sha256:e80c05a310400cfc90af00b5b7271ef9ad24816e3265e1162af8a678e1aad099 AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
COPY packages/sdk-python/pyproject.toml packages/sdk-python/pyproject.toml
COPY packages/env/pyproject.toml packages/env/pyproject.toml
COPY apps/letfs-ingest/pyproject.toml apps/letfs-ingest/pyproject.toml
COPY apps/leta/pyproject.toml apps/leta/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --package letfs-ingest --extra cpu --no-install-workspace
COPY packages/sdk-python packages/sdk-python
COPY apps/letfs-ingest/src apps/letfs-ingest/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --package letfs-ingest --extra cpu

FROM python:3.14-slim-trixie@sha256:22eafb370920ad8b429e0aec3fff433e0669968519f5d60469d83729c138b28b
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --uid 10001 --create-home ingest
COPY --from=builder /app/.venv /app/.venv
COPY packages/contracts/file-types.json packages/contracts/file-types.json
USER ingest
ENTRYPOINT ["/app/.venv/bin/python", "-m", "letfs_ingest.worker"]
CMD ["io"]
