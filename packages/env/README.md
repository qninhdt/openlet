# openlet-env

General-purpose non-production environment manager for Openlet (local development, E2E testing, and evaluation).

## Highlights

- **Zero external SaaS required**: always runs local **RustFS** (`s3.public_endpoint` + browser dev CORS) and **Local RS256 Auth + WireMock** (no Clerk dev API calls or R2 dev credentials needed).
- **Two clean modes**:
  - `mock`: 100% offline, zero `.env` needed, WireMock stubs for OpenAI/LiteLLM, Datalab, and Langfuse, low-latency SpiceDB quantization (`100ms`), fast container teardown (`5s`).
  - `live`: Local Auth + RustFS + real AI keys from `.env` (automatically falls back to `mock` when `OPENAI_API_KEY` is unset).
- **Partial HuggingFace dataset downloads**: downloads only requested workspaces (`hf download --include`) with per-workspace tracking in `datasets/.openlet-sync.json`.
- **Fast seeding & cleanup**: PostgreSQL `COPY` + C-accelerated `google-crc32c` + SpiceDB + Qdrant + RustFS, with `unseed()` and `reset()`.

## CLI

```bash
uv run openlet-env up --project dev --mode live --gateway-port 8080 --seed-workspace amensa-portfolio-review
uv run openlet-env seed --project dev --workspace amensa-portfolio-review
uv run openlet-env token --project dev --user olivia-bennett
uv run openlet-env reset --project dev
uv run openlet-env down --project dev --volumes
```
