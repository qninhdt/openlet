# Operations and recovery

Use [base Compose](../infra/compose.yaml), the generated private environment override and an immutable image lock. Keep service/database/control ports private. Normal local gateway is loopback; production edge HTTPS, DNS and VPS provisioning are configured when deploying the actual host.

Go processes expose native gRPC health, not HTTP readiness endpoints. Python worker running state is not proof of pipeline readiness: API E2E verifies both activities. Inspect `docker compose ps` and native logs. JSON logs and optional OTLP traces/metrics use common YAML settings; signed URL queries are removed from transfer spans/errors.

Set `telemetry.otlp_endpoint` in the shared YAML to an OTLP/gRPC collector URL, for example `http://otel-collector:4317`, then regenerate config and restart the processes. `null` disables export; no collector is needed to run the system. The same sample ratio controls Envoy and application root traces; child spans follow their parent. Metrics include native gRPC, pgx pool, Go/Python runtime, provider calls, Temporal and bounded ingest stage durations. Logs remain JSON stdout with service identity and trace/span correlation when context is available.

Collector failure may drop telemetry but does not fail business requests. Exporters use bounded native queues/timeouts. Standard `OTEL_RESOURCE_ATTRIBUTES` can supply release metadata such as `service.version`; config rendering passes it into application containers and Envoy. Envoy reports its native SDK version; Go development builds without version metadata report `dev`. The optional `observability` profile runs Alloy; Grafana Cloud supplies metrics, traces, logs and dashboards. See [Cloud observability and prompt operations](observability.md). See the [telemetry design and verification scope](../plans/261111-1727-platform-letfs-rewrite/telemetry.md).

The six scripts in [scripts/](../scripts/) own config rendering, bootstrap, E2E, deploy, backup and restore. [Makefile](../Makefile) exposes their native entry points. Never invoke archived recovery/initialization scripts against the rewritten system.

## Deploy

The manual [release workflow](../.github/workflows/release.yaml) requires successful default-branch CI for its commit. It builds once, runs E2E, pushes those exact images, records immutable digest references and transfers a bundle to `/opt/openlet/releases/<sha>` using native SSH/SCP. Configure the production GitHub environment's DEPLOY_HOST, DEPLOY_USER, DEPLOY_SSH_KEY and verified DEPLOY_KNOWN_HOSTS. The VPS needs Docker Compose, Python/uv, registry pull access, `/opt/openlet/openlet.yaml` and private `/opt/openlet/.env`.

Deploy pulls before stopping ingress/writers, backs up PostgreSQL, runs native initialization/migrations and starts services with bounded health waits. It preserves data volumes. There is no source build on the VPS or automatic destructive rollback. Retain the previous bundle/image lock. Roll back images only if schema-compatible; otherwise restore an appropriate backup into an empty target first.

## PostgreSQL backup and restore

Set COMPOSE_FILE and COMPOSE_PROJECT_NAME explicitly for the target deployment. Include the base file, its generated override and matching image lock. OPENLET_CONFIG/OPENLET_GENERATED/OPENLET_BACKUPS must point at that deployment's files.

```sh
scripts/backup.sh /private/backups/new-snapshot
scripts/restore.sh /private/backups/new-snapshot
```

Backup stops ingress, enabled apps/workers (including Leta), Temporal and SpiceDB, catalogs non-template domain databases and owners, then writes native custom-format dumps and checksums. Writers remain stopped. The Leta database includes its domain and native LangGraph checkpoint tables; Redis is disposable cache/events and is not backed up. Canonical SpiceDB data is included; there is no graph reconstruction from SQL grants.

Restore requires target databases/roles already initialized from matching configuration, with no application tables. Initialize that new target with `docker compose run --rm databases` and wait for its successful exit; do not run migration jobs. Restore refuses a nonempty target, takes a pre-restore backup, uses pg_restore with original roles and repairs native SpiceDB transaction IDs. Keep writers stopped until data/config/image compatibility has been checked, then start the matching deployment.

These scripts back up PostgreSQL only. S3 object retention/versioning/off-host backup belongs to the selected provider and must match the restore point. Qdrant is derived data; its operational snapshot/reindex procedure must be verified before claiming complete production recovery. A PostgreSQL restore alone is not a full-system recovery. Store backups off the VPS.

## Maintenance

Native Platform/LetFS Schedules prune expired receipts/invitations/uploads, recover pending durable work and collect unreferenced objects/index points. Trash remains charged until purged and is not silently aged out. Configure native provider handling for incomplete multipart uploads and object versions. Changing an embedding vector space requires a new collection and an explicit migration/reindex decision; no automatic historical configuration framework exists.
