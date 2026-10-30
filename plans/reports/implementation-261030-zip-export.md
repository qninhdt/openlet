# ZIP export implementation evidence

Plan: [Direct Storage, Artifact Processing, and ZIP Export](../261029-1624-artifact-file-processing/plan.md), Phase 4. Date: 2026-10-30.

## Delivered

Workspace authorizes selection, status and download; letfs binds each export to its
actor/filesystem/request key. One Rust `ExportArchive` workflow schedules one
`ArchiveActivities::export_archive` activity. `async_zip 0.0.19` streams ZIP64
through a 64 KiB pipe and bounded native S3 multipart parts. Object input streams;
inline input reads in batches of at most 64 entries / 1 MiB. No archive manifest,
per-file activity, whole-archive buffer, quota charge or node tree is added.

Normal exports stop at files and retain originals only. Explicit artifact exports
start at the source's children. Selected roots, empty directories, overlap
deduplication, deterministic UTF-8 name suffixes and extraction-safe paths are
implemented. Publication rechecks source identity/tree and locks the operation so
maintenance cannot race a failed operation back to success.

Migration `0010_zip_exports.sql` adds only attempt-owned temporary keys, native
multipart identity, deadlines and result expiry/size; prior phases used 0007–0009.
Config bounds admission, tree/input/output size, runtime and retention. Existing
maintenance aborts abandoned multipart and preserves live export objects. Logical
retention defaults to 24 hours; direct GET expiry is limited by remaining retention.

The development R2 account was checked against its configured S3 endpoint. Readback
confirmed an eight-day expiry only for `exports/`, longer than maximum seven-day
application retention plus runtime. The existing seven-day multipart-abort rule
was preserved. No expiry applies to `objects/`. Private before/after rule evidence
is under `.local/provider/r2-lifecycle-*-export.json`; elapsed-time deletion itself
has not been observed.

## Verification

- `make test-integration SERVICE=letfs TEST=zip-export`: **4 passed**, real
  Testcontainers PostgreSQL/SeaweedFS/Temporal. Covers mixed storage, ZIP64 parsing,
  multi-part archive, original/artifact trees, empty roots, collisions,
  Range/expiry/accounting, changed/stale inputs, bounded output, abandoned multipart
  abort, live-key protection, expired cleanup and publication racing a failed state.
- `make test-e2e TEST=zip-export`: passed normal and real Docling-artifact exports,
  direct GET/Range, idempotency and exact original bytes. Go `archive/zip` validates
  Rust-produced output independently. The additional query test passed: 1/65
  inline files use 1/2 content queries and exactly 3 tree enumerations each.
- `make test-workflow TEST=export-archive`: passed against the actual history,
  asserting exactly one scheduled activity and native SDK deterministic replay.
- `make verify`: passed after the ZIP implementation, including Clippy, formatter,
  unit suites and **396 captured response DTOs**. Phase 5 later changes require
  their own final verification.

Logs: `.local/zip-integration-final.log`, `zip-e2e-query.log`, `zip-replay.log`,
`zip-verify.log`. The first E2E assertion omitted the required empty `images/`
directory; its expectation was corrected to the accepted fixture/tree contract.
The initial replay assertion used an unqualified activity name; the actual Rust
SDK macro registers `ArchiveActivities::export_archive`.

## Review and remaining gates

Inline review traced scope/lifecycle, lock order, original-only traversal,
immutable captured keys, bounded streaming, multipart ambiguity and cleanup. It
fixed publication/maintenance serialization and bounded export reconciliation to
30 seconds inside the existing maintenance budget. Comprehensive recovery,
backup/restore and independent release review remain Phase 5 work. Coordinated R2
object-plus-five-database recovery remains **NOT RUN**.
