# Production patterns and Openlet adaptations

Research date: 2026-10-29, Asia/Saigon. Scope: implementation patterns for a backend-only cloud file MVP. Primary documentation and pinned upstream code were inspected; no Openlet runtime, benchmark or provider compatibility was tested. This synthesis supersedes earlier implementation recommendations, including the discarded plan's shared-content model and SDK spike.

## Outcome

Reuse Envoy/Clerk authentication capabilities, PostgreSQL transactions/recursive queries, native Temporal SDKs and S3 operations. Use established metadata/object separation and parent/name trees. Openlet-specific decisions remain explicit: workspace-to-generic-bucket mapping, inline text, commit-time hard quota, ID visibility, recursive-copy semantics and retry-safe storage publication. An upstream pattern is not proof that Openlet's assembly is correct.

## Evidence and selected adaptation

| Question | Primary evidence | Selected use / limits |
|---|---|---|
| Gateway identity | [Envoy JWT filter](https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/jwt_authn_filter.html) provides JWT/JWKS and claim headers | Configure Envoy; strip spoofed headers and verify actual pinned configuration. No gateway application. |
| Internal ID in JWT | [Clerk session customization](https://clerk.com/docs/guides/sessions/customize-session-tokens), [metadata](https://clerk.com/docs/guides/users/extending) | Backend-owned internal UUID claim, then token refresh. No per-request mapping lookup. |
| Shared collaborative storage | [ownCloud Spaces API](https://owncloud.dev/apis/http/graph/spaces/) separates spaces, roles and storage capabilities | Unified workspace, members and quota mapping. No wholesale ownCloud sharing/Graph stack. |
| Metadata vs object bytes | [Nextcloud primary storage](https://docs.nextcloud.com/server/latest/admin_manual/configuration_files/primary_storage.html) keeps tree metadata in DB and content by object identifier | Same separation, adding inline text. DB/object backup must preserve their relationship. |
| Parent/name tree | [JuiceFS relational edge](https://github.com/juicedata/juicefs/blob/6aed45dfaa23e9f2b7e8d84e8756ff62d1449505/pkg/meta/sql.go#L66-L72) and [PostgreSQL recursion](https://www.postgresql.org/docs/current/queries-with.html) | Canonical adjacency list, indexed recursive path query. No depth-independent performance claim. |
| Stable IDs | [Nextcloud cache ID contract](https://github.com/nextcloud/server/blob/b63fed182ee4c1b712373b92a9e37c51a78d258a/lib/public/Files/Cache/ICache.php#L125-L135) | Rename/move retain node IDs; paths are locators, not entity identity. |
| Trash/restore | [Nextcloud trash move](https://github.com/nextcloud/server/blob/b63fed182ee4c1b712373b92a9e37c51a78d258a/apps/files_trashbin/lib/Trashbin.php#L275-L385), [restore](https://github.com/nextcloud/server/blob/b63fed182ee4c1b712373b92a9e37c51a78d258a/apps/files_trashbin/lib/Trashbin.php#L533-L621) | Detached root/original location. Openlet intentionally rejects conflicts rather than automatic renaming, counts trash and omits age purge. |
| Recursive copy | [Nextcloud recursive stream copy](https://github.com/nextcloud/server/blob/b63fed182ee4c1b712373b92a9e37c51a78d258a/lib/private/Files/Storage/Common.php#L218-L240), [JuiceFS detached clone](https://github.com/juicedata/juicefs/blob/6aed45dfaa23e9f2b7e8d84e8756ff62d1449505/pkg/meta/base.go#L3425-L3481) | Recursive, coherent per-file copies with detached destination publication. This assembly is an adaptation, not an upstream snapshot guarantee. No shared chunks/refcount. |
| Atomic accounting | [PostgreSQL row locks](https://www.postgresql.org/docs/current/explicit-locking.html), [UPDATE RETURNING](https://www.postgresql.org/docs/current/sql-update.html) | Usage and file publication in one transaction. Hard cap/no reservations is Openlet policy, not universal cloud-drive behavior. |
| Object lifecycle | [S3 CopyObject](https://docs.aws.amazon.com/AmazonS3/latest/API/API_CopyObject.html), [DeleteObjects](https://docs.aws.amazon.com/AmazonS3/latest/API/API_DeleteObjects.html), [multipart lifecycle](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html) | Independent immutable keys and durable delayed cleanup. Inspect per-key/copy errors, track versions and unfinished multipart; no DB/S3 atomicity claim. |
| Delayed deletion | [JuiceFS deletion bookkeeping](https://github.com/juicedata/juicefs/blob/6aed45dfaa23e9f2b7e8d84e8756ff62d1449505/pkg/meta/sql.go#L3872-L3905) | Concrete letfs cleanup rows and retries, without adopting its chunk/reference-count model. |
| Temporal persistence | [Official persistence](https://docs.temporal.io/temporal-service/persistence) supports PostgreSQL and SQL visibility | One server/shared PG instance, isolated DBs/credentials; no Elasticsearch/Redis requirement. |
| Native Rust execution | [Rust SDK guide](https://docs.temporal.io/develop/rust), [official GA release](https://github.com/temporalio/sdk-rust/releases/tag/v1.0.0) | Native worker inside letfs. No maturity-based claim beyond official GA; test real used operations when implemented. |
| Activity retries | [Temporal activity failure handling](https://docs.temporal.io/encyclopedia/detecting-activity-failures) | At-least-once attempts require durable idempotency/state guards; Temporal does not replace transactions. |

## Alternatives deliberately not selected

- Materialized path is not the canonical model: it complicates descendant rewrites on move without measured need. Stable IDs/path API do not require it.
- Shared content/refcounts, dedup and source-retention manifests are unnecessary for the selected independent-copy/non-snapshot contract.
- A researcher proposed all-Go orchestration calling Rust HTTP; the selected design keeps native worker ownership in letfs, with service-level HTTP coordination and no direct cross-language Temporal contract.
- A researcher proposed snapshot-manifest copy; it adds source retention machinery for a guarantee the selected MVP does not offer. Instead explicitly document dynamic recursive traversal and failure outcomes.
- Redis has no current owner after profile caching was removed. PostgreSQL/Clerk/Envoy/Temporal already own the actual needs.
- Application leases, signed workflow IDs, gateway code, generic dispatch/idempotency/capability frameworks and standalone SDK experiments have no accepted requirement.

## Openlet-owned design decisions

The schemas, workspace/bucket mapping, role matrix, short filesystem mutation lock, hard logical quota, one-shot upload state, deadline/grace cleanup, workflow catalogue and directory publication are Openlet adaptations. Their correctness must be proven by the [test matrix](../../docs/testing.md), particularly source changes, stale attempts, concurrent quota admission and crash-after-commit. No upstream source proves that entire combination.

Recursive copy deliberately has no whole-tree source snapshot: concurrent additions/unobserved removals can be omitted. Each copied file is one revision, IDs are not duplicated, and the destination publishes once only after completion/quota admission. A future snapshot requirement needs an explicit design decision; do not silently add a global mutation epoch or retention framework.

## Next steps and unresolved questions

Execute the [new plan](../261029-1220-openlet-backend-mvp/plan.md). Pin supported versions, verify Envoy configuration and build real provisioning first; cover domain recovery in its owning phase. Select deployment S3 provider/credentials before provider acceptance. Exact configurable limits and image patches are implementation choices, not new product entitlements. No unresolved product question is assumed; external-provider/runtime compatibility is not yet verified.
