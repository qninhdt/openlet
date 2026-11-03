FROM python:3.13.18-slim-bookworm@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f AS dependencies
RUN pip install --no-cache-dir uv==0.10.7
WORKDIR /app
ENV UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
COPY apps/letfs-ingest/pyproject.toml ./apps/letfs-ingest/pyproject.toml
COPY packages/python/ ./packages/python/
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --package letfs-ingest --no-install-package letfs-ingest --no-install-package openlet-python

FROM dependencies AS models
COPY apps/letfs-ingest/src/letfs_ingest/__init__.py ./apps/letfs-ingest/src/letfs_ingest/
COPY apps/letfs-ingest/src/letfs_ingest/parser/__init__.py apps/letfs-ingest/src/letfs_ingest/parser/models.py apps/letfs-ingest/src/letfs_ingest/parser/prefetch_models.py ./apps/letfs-ingest/src/letfs_ingest/parser/
RUN --mount=type=cache,target=/root/.cache/huggingface PYTHONPATH=/app/apps/letfs-ingest/src .venv/bin/python -m letfs_ingest.parser.prefetch_models /models

FROM dependencies AS package
COPY apps/letfs-ingest/src/ ./apps/letfs-ingest/src/
RUN --mount=type=cache,target=/root/.cache/uv uv build --package openlet-python --wheel --out-dir /dist && uv build --package letfs-ingest --wheel --out-dir /dist

FROM python:3.13.18-slim-bookworm@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=dependencies /app/.venv /app/.venv
COPY --from=models /models /models
RUN --mount=type=bind,from=dependencies,source=/usr/local/bin/uv,target=/usr/local/bin/uv \
    --mount=type=bind,from=package,source=/dist,target=/dist \
    uv pip install --python /app/.venv/bin/python --no-deps --no-cache /dist/*.whl
ENV DOCLING_MODELS_PATH=/models HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1
USER 65532:65532
ENTRYPOINT ["/app/.venv/bin/python", "-m", "letfs_ingest.worker"]
