# Direct storage implementation evidence

Plan: [Direct Storage, Artifact Processing, and ZIP Export](../261029-1624-artifact-file-processing/plan.md), Phase 1. Date: 2026-10-30.

## Delivered

Caller-selected bounded binary inline storage and direct conditional PUT/native multipart now share persisted upload identity, idempotent completion, atomic revision/quota publication, abort, expiration and cleanup evidence. Object downloads issue a no-store 307 to private storage, with pinned content, safe attachment headers and Range. Workspace handles authorization and bounded inline/metadata only.

Migration `0007_direct_storage.sql` refuses active legacy uploads and supports keyless inline sessions. A fresh immutable object key belongs to each object upload. No upload/download workflow, quota reservation, physical staging copy or object readback hash was added.

`object_store 0.14.2` explicitly excludes Content-Length from signed headers. The official `aws-sigv4` signer fills that concrete gap for PUT; existing object_store code still owns GET signing and provider operations. Browsers supply Content-Length automatically.

The test issuer exposes only loopback S3 port 8333 and joins the outbound network because Docker did not install the port mapping for a container attached exclusively to the internal network. Production internal services gain no new public port. Restore isolation resets both issuer and Envoy mappings.

## Verification

- `make verify`: passed, including Go/Rust unit tests, vet, clippy, formatter, three configure tests, schema/reference validation and shell syntax. Its concurrent E2E run initially had no captured DTOs; the subsequent standalone contract check validated **1,334 actual response DTOs**.
- `make test-integration SERVICE=letfs TEST=all`: **7 passed** using Testcontainers, real PostgreSQL, SeaweedFS, Temporal and Chromium. Covers arbitrary/empty inline bytes, boundary validation, stable retry after lower limits, revision/quota publication, immutable keys, multipart part bounds/frozen intent, complete/abort race, native abort, cleanup evidence and direct content/Range renewal.
- `make test-e2e TEST=all`: passed through real Envoy and both service facades, including filesystem, identity, storage, lifecycle, worker/server restart, database isolation, node accounting and narrow port checks.
- New multipart E2E injects loss of the successful native completion reply after SeaweedFS commits. Reconciliation returns one saved publication and exact original bytes. PostgreSQL confirms one upload-row read when signing either one or three parts.
- Real private R2 smoke plus Chromium: passed, including removed/altered signed headers, wrong size/MD5, exactly one winner for concurrent conditional PUT, replay rejection, multipart evidence/bytes, signed GET/Range/attachment, private access and configured-origin CORS.

Local evidence: `.local/direct-storage-verify.log`, `direct-storage-integration-all.log`, `direct-storage-e2e-all.log`, `direct-storage-r2-smoke.log` and `direct-storage-clippy.log`. Test stacks and browser origin servers were stopped by their owners.

## Review and remaining gates

Scoped simplification completed earlier. Inline review checked session ownership, lock order, unknown remote outcomes, immutable keys, bounded signing, caller contracts and cleanup. A lost multipart-create database acknowledgment must not abort a possibly persisted winning remote upload; only a positively identified competing upload is aborted. Unknown creates rely on provider-native incomplete-multipart lifecycle.

There is no Git HEAD; comparison uses the private pre-change source archive. Independent final review is still required before release. Phases 2–5 remain unfinished. Coordinated R2 object-plus-five-database recovery and the processing/export-aware backup drain are **NOT RUN / not implemented yet**. Existing development R2-backed application databases were not migrated. Issued URLs remain bearer capabilities until expiry.
