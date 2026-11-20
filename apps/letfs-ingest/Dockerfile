FROM ghcr.io/astral-sh/uv:0.13.7-python3.14-trixie-slim@sha256:e80c05a310400cfc90af00b5b7271ef9ad24816e3265e1162af8a678e1aad099 AS base
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
COPY packages/sdk-python/pyproject.toml packages/sdk-python/pyproject.toml
COPY apps/letfs-ingest/pyproject.toml apps/letfs-ingest/pyproject.toml
COPY apps/leta/pyproject.toml apps/leta/pyproject.toml

FROM base AS io-deps
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --package letfs-ingest --no-install-workspace
FROM base AS cpu-deps
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --package letfs-ingest --extra cpu --no-install-workspace

FROM io-deps AS io
COPY packages/sdk-python packages/sdk-python
COPY packages/contracts/file-types.json packages/contracts/file-types.json
COPY apps/letfs-ingest/src apps/letfs-ingest/src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --package letfs-ingest && useradd --uid 10001 --create-home ingest
USER ingest
ENTRYPOINT ["/app/.venv/bin/python", "-m", "letfs_ingest.worker"]
CMD ["io"]

FROM cpu-deps AS cpu
COPY packages/sdk-python packages/sdk-python
COPY packages/contracts/file-types.json packages/contracts/file-types.json
COPY apps/letfs-ingest/src apps/letfs-ingest/src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --package letfs-ingest --extra cpu && \
    useradd --uid 10001 --create-home ingest
USER ingest
ENTRYPOINT ["/app/.venv/bin/python", "-m", "letfs_ingest.worker"]
CMD ["cpu"]
