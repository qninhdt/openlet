FROM python:3.13.18-slim-bookworm@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f AS build
RUN pip install --no-cache-dir uv==0.10.7
WORKDIR /app
COPY services/letfs/processor/ ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-editable
RUN --mount=type=cache,target=/root/.cache/huggingface .venv/bin/python prefetch-models.py /models

FROM python:3.13.18-slim-bookworm@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY --from=build /models /models
ENV DOCLING_MODELS_PATH=/models HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1
USER 65532:65532
ENTRYPOINT ["/app/.venv/bin/python", "-m", "openlet_processor.worker"]
