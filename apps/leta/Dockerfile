FROM ghcr.io/astral-sh/uv:0.13.7-python3.14-trixie-slim@sha256:e80c05a310400cfc90af00b5b7271ef9ad24816e3265e1162af8a678e1aad099 AS builder
ARG TARGETARCH
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
RUN python3 -c 'import hashlib, os, urllib.request; \
    arch = os.environ["TARGETARCH"]; \
    meta = {"amd64": ("x86_64", "ad487c23744ae5de5dbdf5a81d4e6fac05fdfbe74f02379f9e498cf2070a9ef8"), "arm64": ("arm64", "55f65caa1ee94d4b66f1bdf7091df3bdf72578cf8d44a817b2d6cd6f96af8b02")}[arch]; \
    data = urllib.request.urlopen(f"https://github.com/pressly/goose/releases/download/v3.27.0/goose_linux_{meta[0]}").read(); \
    assert hashlib.sha256(data).hexdigest() == meta[1], "goose sha256 mismatch"; \
    open("/tmp/goose", "wb").write(data); \
    os.chmod("/tmp/goose", 0o755)'
COPY pyproject.toml uv.lock ./
COPY packages/sdk-python/pyproject.toml packages/sdk-python/pyproject.toml
COPY packages/env/pyproject.toml packages/env/pyproject.toml
COPY apps/letfs-ingest/pyproject.toml apps/letfs-ingest/pyproject.toml
COPY apps/leta/pyproject.toml apps/leta/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --package leta --no-install-workspace
COPY packages/sdk-python packages/sdk-python
COPY apps/leta/src apps/leta/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --package leta

FROM python:3.14-slim-trixie@sha256:22eafb370920ad8b429e0aec3fff433e0669968519f5d60469d83729c138b28b
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --uid 10002 --create-home leta
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /tmp/goose /usr/local/bin/goose
COPY packages/contracts/file-types.json packages/contracts/file-types.json
COPY apps/leta/migrations /migrations
USER leta
ENTRYPOINT ["/app/.venv/bin/python"]
CMD ["-m", "leta.api"]
