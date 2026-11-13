# Setup and commands

Use Docker Compose v2 with YAML `!reset` support, Go 1.27.4, Python 3.14/uv 0.13.7 and pnpm 12.18.0. All Python roles use 3.14. Locked dependencies and image digests are committed.

Copy [the complete configuration example](../infra/config/openlet.example.yaml) to `.local/openlet.yaml`. Supply its secret references through a private `.env` or process environment. YAML stores `${ENV_VARIABLE}` scalars, never resolved secret values. Replace Clerk, model and production S3 endpoints with real deployment values.

```sh
pnpm install --frozen-lockfile
make tools generate
make check test
make up OPENLET_CONFIG="$PWD/.local/openlet.yaml" ENV_FILE="$PWD/.env"
make logs
make down
```

`make configure` renders native Envoy/Temporal/Alloy files and a private Compose environment override under `.local/generated`. Runtime services mount the same source YAML. Rendered outputs may contain credentials: keep their private parent directory, do not commit or publish them. Configure/bootstrap tooling does not install CPU parser dependencies.

The [base Compose](../infra/compose.yaml) owns core dependencies and applications. [Test Compose](../infra/compose.test.yaml) adds RustFS and WireMock. The example S3 hostname is the test container address; normal deployment supplies its S3 provider separately. Local gateway binds loopback; configure HTTPS at the edge when preparing the actual VPS.

Startup takes a full PostgreSQL dump before database/schema initialization, then uses native Goose, SpiceDB and Temporal migration jobs. Use new databases; these baselines do not import or upgrade legacy data. `make up` stops writers before initialization. `make down` preserves persistent volumes.

For isolated API E2E:

```sh
scripts/e2e.sh api
```

The script creates its own ephemeral test credentials, renders [test YAML](../e2e/openlet.test.yaml), builds/starts one private stack, runs Playwright and saves reports/logs under `.local/e2e/results` before teardown. It never reads the developer's dotenv or old databases. See [testing](testing.md).

CPU images prepare OCR/model assets at build time. For host development use the native ingest model command documented by `uv run --package letfs-ingest --extra cpu python -m letfs_ingest.models --help`; model paths and limits come from the YAML. IO needs no Docling/OCR models.

Enable the rewritten agent service with `export COMPOSE_PROFILES=leta` before `make up`. The profile adds Redis, the backed-up Goose/native-checkpoint migration job and Leta API/worker. Configure the Leta model catalog and Langfuse keys/approved prompt labels first; cold prompt resolution has no local fallback. Add `observability` to the same profile list for Alloy and Cloud export; follow [observability setup](observability.md). Keep the profile list consistent for configure, backup, restore and deploy. Leta integration status is tracked in the [execution record](../plans/261111-2010-leta-rewrite/execution.md).
