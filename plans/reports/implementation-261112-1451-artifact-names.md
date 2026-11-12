# Semantic artifact names

Restored artifact file/directory naming from existing AI titles, as requested on 2026-11-12. No archived handwritten code or tests were copied. Source names, README.md names, node IDs, parent IDs and S3 object keys remain unchanged.

## Behavior and boundaries

- Ingest allocates deterministic sibling names from semantic titles, preserves file extensions and numeric section prefixes, and reserves candidates before allocating collision suffixes. A per-name suffix cursor avoids rescanning previously allocated suffixes. Unicode slugs are bounded by UTF-8 bytes.
- Directory titles come from their README metadata. Generated inline Markdown links/images and README children references are rewritten using one old-path/new-path map; external and unknown destinations are retained. Query strings/fragments are preserved and new URL paths are percent-encoded.
- Internal EnrichedArtifact adds optional name. Directory updates carry node ID/name without file metadata. LetFS validates names/current source ancestry, then batches names, text, metadata, quota and stage in one transaction. No per-artifact SQL/RPC, extra model calls, S3 transfers, workflow, receipt table or dependency was introduced.
- Migration 0002 replaces the immediate partial unique index with native UNIQUE(storage_id,parent_id,name) DEFERRABLE INITIALLY IMMEDIATE. Only CommitEnrichment defers it, allowing name exchanges while still rejecting duplicate final names. Comments at both the migration and SET explain why. Other mutations still enforce uniqueness immediately.
- CommitEnrichment adds one constant PostgreSQL SET statement/round trip. It uses the existing short source-row lock. Names/timestamps share a single nodes UPDATE; no workspace/storage locking or temporary rename protocol was added.
- Indexing already rereads input after enrichment and therefore receives final paths. Current source version/stage guards preserve replay behavior.

## Verification

- make check test passed: Go formatting/vet/tests, Ruff, Buf, TypeScript and shell syntax; 19 Python tests. Upstream LangSmith emits Python 3.14 deprecation warnings, without failures.
- New focused Python coverage verifies nested directory/section naming, stable collision allocation, UTF-8 limits/fallback, relative links including query/fragment/angle destinations, preserved external links, all Markdown bodies and README children. The async test verifies exactly the existing model-call count.
- Existing PostgreSQL invariant suite passed against an isolated PostgreSQL 18 container with both migrations: ordinary duplicates fail immediately; exchanged names succeed; final duplicates fail at commit and roll back text/quota/stage; directory rename preserves descendant IDs; successful replay is a no-op.
- Native pg_dump backups were taken before schema changes. Migration down/up passed in the isolated test database. No existing application database was accessed or migrated.
- Existing API E2E suite passed 4/4 in 45.6 seconds on fresh Compose resources. XLSX exercised real CPU/IO workers, published revenue-report/revenue-report.csv, checked rewritten README links, readonly enforcement, hybrid search and unchanged source downloads. The model provider remains the suite's boundary fixture.
- One final suffix-allocation optimization was applied after the full E2E run; focused Python tests and Ruff were rerun for that change.
- Test resources were torn down. Local evidence/backups remain ignored under .local/artifact-rename/ and .local/e2e/.

## Limits and rollout

Apply the migration before running the new LetFS build; normal deploy already backs up and migrates with writers stopped. Existing ready artifacts keep their names; no backfill or automatic reprocessing was added. Rewriting targets exporter-generated inline links/images, not a general Markdown migration engine. No production load benchmark, paid-provider quality test or production migration/deployment was performed.

The root README and separate Leta plan changes predated this task and were left untouched. The user subsequently requested a focused commit; no push or deployment was requested.
