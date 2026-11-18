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

The [React frontend](../apps/web/README.md) lives in `apps/web`. Run `pnpm dev` from the repository root to start Vite at `http://localhost:5173`; `pnpm build` produces `apps/web/dist`, and `pnpm preview` serves that build locally. `make check-js` includes web formatting, type checks, lint and the production build. The app includes interactive Storage and Agent previews; landing/login remain placeholders, and authentication and backend integration are not connected yet.

PDF and DOCX ingest use Datalab Convert. Set `DATALAB_API_KEY` in the private dotenv before running `make configure`. Only the parse worker receives it. Local RustFS uploads use multipart through the worker. To let Datalab fetch directly from a private S3 bucket, set `dependencies.s3.processing_download_endpoint` to an externally reachable HTTPS endpoint for that bucket. LetFS signs a short-lived GET on that hostname. Datalab images are published to S3 through LetFS artifact uploads. See the [migration plan](datalab-ingest-plan.md).

XLSX and PPTX run locally on Docling Slim. The parser image includes no local OCR models. The example allows eight parsing activities, two local Office subprocesses, and two Datalab jobs with polling paced for the Free plan. The SDK controls its initial polls and backoff. For a single worker using a Team plan, start with eight Datalab jobs and 120 requests/minute. Enrich and index default to twelve activities and sixteen model slots.

Artifact export uses Markdown from Datalab or Docling Slim with relative image links. Markdown parts follow the `split_tokens` target (4 bytes per token) and the hard text byte limit. Lists, code and tables stay intact. Large pipe tables get row-preserving CSV links. Docling Slim determines which spreadsheet values appear in its Markdown.

Enable the rewritten agent service with `export COMPOSE_PROFILES=leta` before `make up`. The profile adds Redis, the backed-up Goose/native-checkpoint migration job and Leta API/worker. Configure the Leta model catalog and Langfuse keys/approved prompt labels first; cold prompt resolution has no local fallback. Add `observability` to the same profile list for Alloy and Cloud export; follow [observability setup](observability.md). Keep the profile list consistent for configure, backup, restore and deploy. Leta integration status is tracked in the [execution record](../plans/261111-2010-leta-rewrite/execution.md).

## Cloud operator CLIs

Use the official [Grafana gcx](https://grafana.com/docs/grafana/latest/ai-tools/grafana-cli/gcx/installation/) and [Langfuse CLI](https://langfuse.com/docs/api-and-data-platform/features/cli). These are host operator tools, not runtime dependencies. `grafanactl` is deprecated.

```sh
gcx login openlet --cloud --oauth
langfuse api projects list
```

Grafana opens a browser for sign-in and stack selection, storing its login through native CLI credential storage. Langfuse has no browser login command: configure `LANGFUSE_BASE_URL`, `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` using the project's API Keys page and regional URL. Use its native `--env` option to load the root credential file and keep the CLI URL aligned with `langfuse.base_url` in YAML. CLI sign-in does not replace Alloy's runtime Cloud access-policy token with `metrics:write`, `logs:write` and `traces:write` scopes; see [observability](observability.md).

Existing Clerk and Cloudflare CLIs can inspect authentication with `clerk whoami --json` and `cf auth whoami`. Clerk can retrieve development credentials with `clerk env pull`, using explicit application/instance selection and its `--file` option to target the root credential file. Preserve existing values when updating credentials; YAML continues to use secret references.

Cloudflare CLI OAuth can manage R2 buckets and, with token-creation permission, provision LetFS credentials through `cf user tokens create`. Use a policy scoped to the target bucket with `Workers R2 Storage Bucket Item Write` (object read/write/list). Per [R2 authentication](https://developers.cloudflare.com/r2/api/tokens/#get-s3-api-credentials-from-an-api-token), the response `id` becomes the S3 access key ID and the SHA-256 hex digest of `value` becomes the secret access key. Capture the response privately and save credentials directly to the root credential file. Account token-management authorization is separate; its failure does not establish whether user token creation works. Configure CORS for the actual browser origin; presigned uploads need access to the returned `ETag` header. Allow the returned upload headers, including `Content-Type`, `If-None-Match` and `X-Amz-Checksum-Crc32c`; a valid preflight can return HTTP 204.

## Inference gateway

One internal LiteLLM Proxy owns upstream deployments, prices and transport retries.
Configure [its native YAML](../infra/config/litellm.yaml), set `OPENAI_BASE_URL`,
`OPENAI_API_KEY` and an independent `LITELLM_MASTER_KEY` in the private root `.env`.
Only the Proxy receives upstream credentials. Do not expose port 4000 publicly.
A public model group can contain several suppliers; enable only configured suppliers
and enter their actual rates in native deployment parameters when known.

Openlet `models.gateway` points to the Proxy. Langfuse Prompt Config holds task
`model`, `max_tokens` and optional `reasoning_effort`, `temperature`, `top_p`, `top_k`.
The config is flat and versioned with `leta/root`, `leta/leti` or `letfs/enrichment`.
Explicit agent `model_id` and `reasoning_effort` override task defaults; Leti inherits
its root selection when unset. Mark offered groups `model_info.access_groups: [leta]`.
Unknown deployment limits/efforts must be configured in the Proxy metadata.

Embedding model and dimensions remain in Openlet config and identify the index
space. Changing them requires a deliberate reindex; routing must not mix spaces.
`models.reranking: null` (or absent) disables reranking while retaining hybrid search.
Enrichment `output_mode` accepts `tools`, `json_schema`, `text`; Vilao uses `tools`.
Instructor validates extraction and may make two completions; Proxy transport retries
once and application SDK transport retries are disabled. These are separate from
Temporal's durable activity retries.
