# Openlet backend deployment

API: <https://openlet-api.qninhdt.com>, a Cloudflare Tunnel to the VPS gateway.
The backend API requires Clerk JWTs. Database, workflow, vector, cache and LLM
ports stay inside Docker; the gateway binds only `127.0.0.1:8080` on the host.

Backend: `qninh@103.173.227.135`, Docker Compose project `openlet` with
`leta,observability` profiles. The deployment lives under `/opt/openlet`:

- `current` points to `releases/20261115-ui`.
- `.env`, `openlet.yaml` and `tunnel.token` are private runtime configuration.
- `compose` supplies the exact release files, project, profiles and paths.
- `backups` contains the database backups taken before initialization/migrations.

This deployment builds the current workspace, including its uncommitted changes,
and transfers the five application images over SSH. `image-lock.yaml` pins their
content IDs with `pull_policy: never`; dependency images use registry digests.
It also records per-service memory limits, CPU ingest concurrency and persistent
restart policies. Preserve that lock and the images for recovery. No image is
built on the VPS, and the existing applications/proxy configuration are retained.

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

Source validation uses `make check`. The image IDs are recorded in
`/opt/openlet/current/deployment.json`. These checks do not establish peak load,
all document formats or the full Leta agent workflow.
