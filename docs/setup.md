# Setup and commands

Use [the credential example](../.env.example) when creating the root dotenv file. Keep all local credentials together in that private, Git-ignored file with mode `0600`; preserve existing values when adding credentials. Service endpoints, model settings and limits remain in the shared YAML.

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

## Cloud operator CLIs

Use the official [Grafana gcx](https://grafana.com/docs/grafana/latest/ai-tools/grafana-cli/gcx/installation/) and [Langfuse CLI](https://langfuse.com/docs/api-and-data-platform/features/cli). These are host operator tools, not runtime dependencies. `grafanactl` is deprecated.

```sh
gcx login openlet --cloud --oauth
langfuse api projects list
```

Grafana opens a browser for sign-in and stack selection, storing its login through native CLI credential storage. Langfuse has no browser login command: configure `LANGFUSE_BASE_URL`, `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` using the project's API Keys page and regional URL. Use its native `--env` option to load the root credential file and keep the CLI URL aligned with `langfuse.base_url` in YAML. CLI sign-in does not replace Alloy's runtime Cloud access-policy token with `metrics:write`, `logs:write` and `traces:write` scopes; see [observability](observability.md).

Existing Clerk and Cloudflare CLIs can inspect authentication with `clerk whoami --json` and `cf auth whoami`. Clerk can retrieve development credentials with `clerk env pull`, using explicit application/instance selection and its `--file` option to target the root credential file. Preserve existing values when updating credentials; YAML continues to use secret references.

Cloudflare CLI OAuth does not supply the S3 credentials required by LetFS. Configure bucket-scoped R2 access keys and CORS for the actual browser origin; presigned uploads need access to the returned `ETag` header.
