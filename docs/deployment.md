# Openlet deployment

A successful push CI run on `main` starts the Release workflow. It tests the
backend images, publishes them to GHCR, and deploys by digest to the VPS. Once
the public API responds through the tunnel, the workflow builds and deploys
the frontend Worker and checks the public site and API proxy. Use **Run
workflow** on `main` to retry a release after CI succeeds.

GitHub environment `openlet` allows deployments from `main` and holds the VPS SSH
secrets. Repository configuration supplies the Cloudflare account ID, Workers
deployment token and Clerk publishable key. The VPS keeps its private runtime
configuration under `/opt/openlet`. Releases live under `releases/<commit>` and
`current` points to the latest successful backend deployment.

The VPS uses `infra/compose.vps.yaml` for the tunnel, restart policies and
memory limits. Routine deploys reuse Openlet's Docker volumes and take a
database backup before updating an existing stack. Frontend deployment uses
`apps/web/wrangler.jsonc`.

## Initial manual deployment

API: <https://openlet-api.qninhdt.com>, a Cloudflare Tunnel to the VPS gateway.
The backend API requires Clerk JWTs. Database, workflow, vector, cache and LLM
ports stay inside Docker; the gateway binds only `127.0.0.1:8080` on the host.

Backend: `qninh@103.173.227.135`, Docker Compose project `openlet` with
`leta,observability` profiles. The deployment lives under `/opt/openlet`:

- `current` points to `releases/20261118-identity`; prior releases are retained.
- `.env`, `openlet.yaml` and `tunnel.token` are private runtime configuration.
- `compose` supplies the exact release files, project, profiles and paths.
- `backups` contains the database backups taken before initialization/migrations.

This deployment builds the current workspace, including its uncommitted changes,
and transfers the five application images over SSH. `image-lock.yaml` pins their
content IDs with `pull_policy: never`; dependency images use registry digests.
It also records per-service memory limits, CPU ingest concurrency and persistent
restart policies. Preserve that lock and the images for recovery. Application
binaries and dependency layers are built locally. The ingest images use COPY-only source/SDK
overlays on their retained production bases; no models or packages are downloaded
for those overlays. Existing unrelated applications/proxy configuration are retained.

Production object storage uses the dedicated private R2 bucket
`openlet-production` with bucket-scoped object credentials. The bucket uses a configured CORS policy.
Existing development objects are separate from the new database and its object garbage collector. Database,
SpiceDB, Redis, Qdrant and internal LLM gateway secrets were generated separately
for this deployment. Supplied Clerk and upstream provider credentials are reused.

```sh
ssh qninh@103.173.227.135 '/opt/openlet/compose ps -a'
ssh qninh@103.173.227.135 '/opt/openlet/compose logs --tail 100 platform letfs ingest-cpu ingest-io leta-api leta-worker'
```

For a future release, retain the previous release directory/image lock and use
the existing `scripts/deploy.sh` with the matching private configuration. The
runtime profiles must remain consistent.

For a manual database backup, which intentionally stops writers:

```sh
ssh qninh@103.173.227.135 'cd /opt/openlet/current && sudo env COMPOSE_PROJECT_NAME=openlet COMPOSE_PROFILES=leta,observability OPENLET_CONFIG=/opt/openlet/openlet.yaml OPENLET_GENERATED=/opt/openlet/current/.local/generated OPENLET_BACKUPS=/opt/openlet/backups COMPOSE_FILE=/opt/openlet/current/infra/compose.yaml:/opt/openlet/current/.local/generated/compose.runtime.yaml:/opt/openlet/current/image-lock.yaml scripts/backup.sh /opt/openlet/backups/manual-$(date -u +%Y%m%dT%H%M%SZ)'
```

After the backup, `/opt/openlet/compose up -d --wait` starts services again. Image
rollback requires compatible schemas; otherwise follow `docs/operations.md` and
restore into an empty target. Keep backups off-host and pair database recovery
with object retention and vector recovery; this deployment does not establish a
complete disaster recovery policy.

The supplied Clerk tenant uses development keys. Switching authentication to a
Clerk production instance requires its keys, domain setup and matching `openlet`
JWT template, followed by backend configuration. The VPS is shared and has 8 GB RAM; CPU parsing is limited to one activity with two threads.
Load capacity and host-reboot recovery require separate verification.

Backend verification: authenticated onboarding, workspace/folder creation,
text and signed R2 image uploads, previews and image processing to `ready`.
Isolated test workspaces, accounts and objects were removed afterward.
Unauthenticated requests and forged identity headers return 401 through the API
hostname. API responses use `no-store`. Offline Docling PDF model initialization
passes inside the VPS CPU image. Migration jobs exit successfully and services
with readiness checks are healthy. Existing unrelated services retain their uptime.

The November 18 release passed Go unit tests, Leta tests (81 passed, 23 skipped),
isolated Platform/LetFS SQL tests, all three application migration chains,
frontend build and Worker proxy tests. Production browser checks cover Clerk
sign-in/onboarding, workspace/agent provisioning, settings persistence, processing,
SSE, chat width and attachment albums/downloads on desktop and mobile. Attachment
and message layout checks use fixture messages; no real model turn was sent.

Frontend: <https://openlet.qninhdt.com>, Cloudflare Worker `openlet-web`, version
`2454060b-b7db-4420-99e1-378a5383d807`. The Vite SPA uses `apps/web/worker.js`
and `worker.config.json` with static assets and same-origin `/v1` streaming proxy.
The prior Worker version is `ef970241-3923-4aa9-bc80-4ffabc1589fe`.
Render configuration with both `COMPOSE_PROFILES=leta,observability`; validate the
rendered service environments before starting the stack. The verified pre-release
PostgreSQL backup is `/opt/openlet/backups/pre-deploy-20261118-chat-ui`.

Clerk shares a development tenant with local development. Production now sets
`auth.clerk.user_id_metadata_key: openlet_production_user_id`; onboarding updates
that metadata field and Envoy reads `public_metadata.openlet_production_user_id`.
Local development retains the default `openlet_user_id`. The JWT template includes
the full `user.public_metadata` object. Existing production accounts were backfilled
from their database IDs without changing their local identity or other metadata.
Use a distinct metadata key for each deployment sharing a tenant, and backfill
existing accounts before changing the gateway claim. Fresh JWTs pick up the field.
This fixes `owner user not found` when a local login previously overwrote the shared
ID. No database ID, ownership or schema migration is required.

Empty workspaces use the normal Agent shell with an empty sidebar and content area.
The existing `+` menu opens the full agent creation dialog; no creation form is
shown automatically. Legacy entry redirects clear inherited/default query parameters.
This update passed five local empty-workspace browser checks (including mobile,
creation-dialog access, navigation and invalid-agent URLs), two existing-agent
regression checks, frontend/e2e typechecks and the production frontend build.
Production verification for this update is read-only; no test workspace, agent
or message is created. The archived deployment-test agent and its conversation
were removed after the earlier test workspace cleanup.

The image IDs and validation are recorded in `/opt/openlet/current/deployment.json`.
These checks do not establish peak load, all document formats or a real production
LLM turn.
