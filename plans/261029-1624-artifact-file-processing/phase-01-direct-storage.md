---
title: "Phase 1: Direct Storage Transport and Publication"
status: completed
priority: P1
effort: 6d
dependsOn: []
---

# Phase 1: Direct Storage Transport and Publication

## Objective

Replace object-byte proxying with one caller-selected inline/direct-object upload subsystem, direct object downloads, atomic publication, provider-safe cleanup, and reachable signed endpoints. This phase is the transport prerequisite for ordinary callers, Python processing, and ZIP export.

## Baseline Evidence And Consumers

- `file_data` already stores exclusive inline `bytea` or object keys; current classification still requires UTF-8/no-NUL in `storage::inline` (`services/letfs/src/storage/mod.rs:44`) and is called during upload (`services/letfs/src/fs/uploads.rs:177`). Remove classification from storage choice; do not weaken the separate text-edit string contract.
- Current defaults are `MAX_FILE_BYTES=104857600`, `MAX_OUTSTANDING_STORAGE=16`, and `INLINE_LIMIT_BYTES=262144` with a 1 MiB inline ceiling (`services/letfs/src/config.rs:115`, `services/letfs/src/config.rs:119`). Preserve the max-file default and expose the effective inline limit through an existing suitable metadata/config response.
- `App` owns a dynamic store (`services/letfs/src/http/mod.rs:15`), while `storage::build` returns `Arc<dyn ObjectStore>` (`services/letfs/src/storage/mod.rs:6`). Update all current consumers together: `services/letfs/src/main.rs:43`, `services/letfs/tests/integration.rs:192`, and `services/letfs/src/storage/provider_smoke.rs:10`.
- The current API has full-body object upload and content delivery handlers (`services/letfs/src/http/mod.rs:180`, `services/letfs/src/http/mod.rs:348`, `services/letfs/src/http/mod.rs:469`). Remove the object-body receiver/relay; retain bounded inline bytes and metadata/redirect surfaces.
- Upload rows currently require `candidate_key`; expiration/abort assumes a string key. The transport migration must make inline sessions keyless and update every cleanup/read caller explicitly rather than substituting fake keys.
- Current object client timeouts are 120 seconds (`services/letfs/src/storage/mod.rs:17`), and cleanup retries use fixed fifteen-minute assumptions (`services/letfs/src/fs/maintenance.rs:104`). Direct caller transfers are not bounded by the old proxy timeout.
- Test scripts currently accept integration `empty|all` only (`scripts/test-integration.sh:7`), and workflow selectors do not cover direct storage (`scripts/test-workflow.sh:5`). Add selectors before listing them as runnable.
- Test storage is addressed internally as `http://issuer:8333` (`deploy/compose.test.yaml:18`), while the published-port assertion permits only Envoy (`scripts/verify-foundation.sh:56`). Add the narrow configured storage exposure required by actual browser/test callers; do not broadly publish internal services.

## Transport And Publication Contract

- [x] Client and Python worker explicitly choose `inline` or `object`. letfs enforces the inline byte limit, maximum file size, authorization, scope, lifecycle, protocol bounds, and quota; it does not UTF-8/NUL sniff, reclassify, fall back, or read back object bytes to relocate them.
- [x] Inline accepts arbitrary bounded bytes into existing `bytea`. Do not label arbitrary bytes `text/plain`. Preserve revision-conditional text-edit APIs as validated strings. Inline sessions have no S3 key/multipart ID; cleanup, abort, expiry, serialization, and schema constraints handle null object fields intentionally.
- [x] Object prepare persists the UUIDv7 upload/session before capability issuance. Key format is `objects/<quota-bucket-id>/<upload-id>`. Same idempotency key and parameters returns the same session/result; changed parameters conflicts. Do not add a generic response-replay table.
- [x] Size chooses single PUT versus native multipart within `object` mode. Keep the existing 100 MiB default maximum; thresholds/part sizing remain validated operational config.
- [x] Single PUT signs `If-None-Match: *`, exact size, and `Content-MD5` using installed `object_store 0.14.2` signing APIs. Browsers provide Content-Length automatically; the contract must not require JavaScript to set the forbidden header manually. MD5 is transfer-integrity evidence only.
- [x] Native multipart persists provider upload ID, signs bounded batches of part numbers with expected size/checksum, accepts ordered ETag receipts, freezes completion intent, and lets only letfs complete/abort. Remote create/complete/abort and reconciliation occur outside DB locks. Add scoped signed ListParts only if pinned-provider resume requires it; no per-part ledger or custom assembly.
- [x] Lost single-PUT/multipart replies reconcile the persisted unique session/key and frozen intent. Conditional conflict, temporary 404, one DELETE, or one HEAD 404 is not automatic success/absence. Pinned R2 and SeaweedFS must prove conditional/checksum/size/replay semantics; no unchecked fallback.
- [x] Completion verifies provider object evidence outside the transaction, then uses the existing bucket -> filesystem -> upload/operation lock order to recheck destination, overwrite revision, liveness, actual size, and hard commit-time quota. It saves publication and terminal result once; retry returns the saved result.
- [x] Overwrite keeps the old file live until publication. The winning transaction installs the fresh immutable key and queues the old key. Phase 2 extends this same transaction with child invalidation and processing intent; no placeholder artifact module, callback or extension abstraction is needed now. A rejected quota/revision/liveness commit exposes no candidate and queues cleanup.
- [x] Ordinary multi-file upload uses independent sessions, bounded client concurrency, per-file results/retry, and bounded metadata batches/set-based DB work. One failed file does not roll back siblings. Do not add quota reservations or a batch all-or-nothing transaction.
- [x] Object download authorization returns a presigned GET descriptor or redirect; no object byte relay through Envoy/Workspace/letfs. Inline download returns bounded bytes. Descriptor/renewal pins logical revision/content, preserves safe attachment headers and Range, and proposes five-minute GET URLs. Issuance/renewal reauthorize; issued URLs remain bearer capabilities until expiry.

## Cleanup, Configuration, And Compatibility

- [x] Reuse `maintenance` and `object_deletions`. Protect keys referenced by `file_data`, active uploads, processing/output owners, copy operations, and exports. Retain ambiguous-write evidence until all issued write URL expiries plus documented transfer grace and remote outcomes reconcile.
- [x] Abort terminal multipart through the SDK; configure provider-native incomplete-multipart lifecycle. Never age-expire ordinary `objects/` and never infer liveness from S3 listing.
- [x] Separate internal control endpoint from caller-reachable signing endpoint where needed. Sign the exact host/path requested; never rewrite a signed hostname. Configure private buckets, least privilege, TLS outside local mode, exact-origin CORS for PUT/GET/HEAD and signed headers, and exposed ETag/range metadata.
- [x] Remove the existing full-file object receiver rather than maintaining a second transport. Update public/internal OpenAPI and all callers coherently, including removal of the impossible backend-hashed SHA-256 receipt guarantee for direct S3. Preserve node revision semantics and document MD5's narrower meaning.
- [x] Extend config generators, `.env.example`, Compose/Testcontainers, provider smoke, and App construction. Add another standard S3 SDK only if a concrete pinned-`object_store` gap is established. Custom SigV4, Redis, a gateway, notifications, and upload workflows remain outside scope regardless.

## Files

Create the next migration at execution time, currently expected as `services/letfs/migrations/0007_direct_storage.sql`. It owns nullable/keyless inline sessions, transfer mode, expected/provider evidence, multipart identity/intent, issued-capability expiry, destination/processor ownership, and terminal result. No later phase may reuse `0007`.

Modify:

| Files | Change |
|---|---|
| `services/letfs/src/config.rs`, `.env.example`, `scripts/configure.py`, `scripts/configure-test.py` | Validate transport/signing endpoints, TTLs, thresholds, parts, concurrency, grace; expose effective inline limit. |
| `services/letfs/src/storage/mod.rs`, `services/letfs/src/storage/provider_smoke.rs` | Return dynamic store plus concrete signer/native multipart control; provider contract checks. |
| `services/letfs/src/main.rs`, `services/letfs/tests/integration.rs` | Adapt the other storage-builder consumers and test harness. |
| `services/letfs/src/fs/uploads.rs`, `services/letfs/src/fs/maintenance.rs`, `services/letfs/src/fs/deletion.rs` | Shared prepare/transfer/complete, keyless inline lifecycle, publication, abort/reconciliation, GC evidence. |
| `services/letfs/src/http/mod.rs` | Bounded inline routes, session/part/complete/status routes, GET descriptor/redirect; remove object body relay. |
| `services/workspace/internal/http/files.go`, `services/workspace/internal/http/server_test.go` | Keep authorization/metadata facade; forward bounded inline and descriptors only. |
| `contracts/internal/openapi.yaml`, `contracts/public/openapi.yaml` | Intentional transport contract replacement, inline bytes, direct object descriptors, checksum/revision semantics. |
| `deploy/compose.yaml`, `deploy/compose.test.yaml`, `scripts/verify-foundation.sh` | Reachable signer host, narrow storage publication, CORS/lifecycle, no broad exposure. |
| `scripts/test-integration.sh`, `Makefile`, `tests/e2e/storage_test.go` | Add `direct-storage`/storage E2E routing before use; preserve comprehensive `all` and unknown-selector failure. |

## Implementation Steps

1. Back up, allocate the next migration number, and migrate upload state without creating fake inline keys. Update every nullable-key consumer in the same change.
2. Change storage construction to provide both dynamic I/O and typed signing/multipart capability; update all three consumers.
3. Implement idempotent prepare for caller-selected modes, single PUT and native multipart, frozen completion, reconciliation, abort, and key evidence.
4. Replace object HTTP receivers/relays with direct capabilities and descriptors; keep bounded inline paths and text-edit contracts separate.
5. Implement provider verification outside locks and atomic publication/overwrite/quota/result within the existing lock order. Phase 2 modifies this transaction directly when adding artifacts. Batch ordinary prepare metadata and keep file results independent.
6. Extend maintenance, endpoint/CORS configuration, provider lifecycle, config generators, contracts, callers, and focused tests. Remove proxy-120s assumptions from storage cleanup and docs work queued for Phase 5.

## Focused Acceptance

| Area | Required cases |
|---|---|
| Inline | Empty/binary/NUL/invalid-UTF8 bytes within limit; limit exceeded; no fake object key; content type safe; text edit still rejects non-string content. |
| Single PUT | Browser-compatible request, exact size/MD5/conditional headers, header removal/change, retry/412 reconciliation, late PUT, quota/revision refusal. |
| Multipart | Part bounds/order/checksum/retry, bounded signing, frozen intent, lost complete response, concurrent complete/abort, worker death, native abort/lifecycle. |
| Publication | Old bytes visible until commit, fresh overwrite key, independent multi-file results, no reservation, set-based query bounds, saved idempotent result. |
| Download | Object descriptor/307 without relay, inline bytes, Range resume across URL renewal, overwrite revision mismatch, safe filename headers, expiry bearer semantics. |
| Infrastructure | Actual browser/Python-reachable signed host, exact CORS, narrow local storage port allowance, private/internal endpoints, R2 and SeaweedFS enforcement. |

Existing gates are `make fmt`, `make verify`, and `make test-integration SERVICE=letfs TEST=all`. The baseline integration script accepts only empty/`all`; `make test-integration SERVICE=letfs TEST=direct-storage` is planned and must not be claimed until added. No runtime checks ran during planning.

## Todo

- [x] Migrate upload/session state and keyless inline lifecycle.
- [x] Implement shared caller-selected inline/single/multipart prepare-transfer-complete.
- [x] Implement atomic publication, direct downloads, and proxy receiver removal.
- [x] Extend reconciliation, cleanup, endpoint/CORS configuration, and all consumers.
- [x] Update contracts and add focused direct-storage/provider/browser tests.

## Risks And Rollback

Implementation evidence: [Direct storage implementation](../reports/implementation-261030-direct-storage.md). The official AWS signer was required because the pinned object_store signer rejects Content-Length signing; no custom signing algorithm was introduced. Focused and full local gates plus real R2/browser checks passed. Broader processing/export recovery remains Phase 5 work.

Provider conditional/checksum/signing behavior and browser CORS are high-likelihood/high-impact integration risks; pinned R2 and SeaweedFS gates prevent silent fallback. Rollback closes new admission, waits for issued capabilities and ambiguous writes, aborts multipart, drains candidate cleanup, and preserves old visible keys until sessions are terminal. Reverting the migration before reconciliation could orphan writable capabilities, so retain evidence and old-schema read/delete compatibility through the drain.
