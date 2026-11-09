FROM golang:1.27.3-trixie@sha256:af1bfc2614ebb1dbd31af514b78740fd678850e76498762b425ecee4c5c6ea80 AS migration-tool
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 go install -tags 'no_mysql no_sqlite3 no_ydb no_mssql no_clickhouse no_libsql no_vertica' github.com/pressly/goose/v3/cmd/goose@v3.29.0

FROM python:3.14.10-slim-trixie@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS dependencies
RUN pip install --no-cache-dir uv==0.13.7
WORKDIR /app
ENV UV_LINK_MODE=copy
COPY pyproject.toml uv.lock .python-version ./
COPY apps/letfs-ingest/pyproject.toml ./apps/letfs-ingest/pyproject.toml
COPY apps/leta/pyproject.toml ./apps/leta/pyproject.toml
COPY packages/python/ ./packages/python/
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --package leta --no-install-package leta --no-install-package openlet-python

FROM dependencies AS package
COPY apps/leta/src/ ./apps/leta/src/
COPY apps/leta/migrations/ ./apps/leta/migrations/
RUN --mount=type=cache,target=/root/.cache/uv uv build --package openlet-python --wheel --out-dir /dist && uv build --package leta --wheel --out-dir /dist

FROM python:3.14.10-slim-trixie@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f
WORKDIR /app
COPY --from=dependencies /app/.venv /app/.venv
COPY --from=migration-tool /go/bin/goose /usr/local/bin/goose
RUN --mount=type=bind,from=dependencies,source=/usr/local/bin/uv,target=/usr/local/bin/uv \
    --mount=type=bind,from=package,source=/dist,target=/dist \
    uv pip install --python /app/.venv/bin/python --no-deps --no-cache /dist/*.whl
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 65532:65532
ENTRYPOINT ["/app/.venv/bin/python"]
CMD ["-m", "leta.api"]
