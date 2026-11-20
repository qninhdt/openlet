FROM golang:1.27.4@sha256:08bcb99a38f85a265f9a93d1d3323e2440eec333380f3ea26ee0dec9264bb41c AS migrations
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    GOBIN=/out CGO_ENABLED=0 go install -tags='no_clickhouse no_mysql no_mssql no_sqlite3 no_vertica no_ydb no_libsql' github.com/pressly/goose/v3/cmd/goose@v3.27.0

FROM ghcr.io/astral-sh/uv:0.13.7-python3.14-trixie-slim@sha256:e80c05a310400cfc90af00b5b7271ef9ad24816e3265e1162af8a678e1aad099
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages/sdk-python/pyproject.toml packages/sdk-python/pyproject.toml
COPY apps/letfs-ingest/pyproject.toml apps/letfs-ingest/pyproject.toml
COPY apps/leta/pyproject.toml apps/leta/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --package leta --no-install-workspace
COPY packages/sdk-python packages/sdk-python
COPY packages/contracts/file-types.json packages/contracts/file-types.json
COPY apps/leta/src apps/leta/src
COPY apps/leta/migrations /migrations
COPY --from=migrations /out/goose /usr/local/bin/goose
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --package leta && useradd --uid 10002 --create-home leta
USER leta
ENTRYPOINT ["/app/.venv/bin/python"]
CMD ["-m", "leta.api"]
