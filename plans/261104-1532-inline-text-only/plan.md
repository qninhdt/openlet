# Inline text only filesystems

Status: complete (implementation and local verification; deployment is outside scope).

Outcome: callers can select immutable `inline_text_only` at filesystem creation and read it back. The default remains false. Restricted filesystems accept inline UTF-8 text (including Markdown, JSON and source code), reject binary control characters and object uploads, and retain existing inline size limits.

Constraints: enforce the policy in LetFS, include processing outputs, preserve existing data/default behavior and provisioning retry identity. Copy stays within one filesystem. No UI, mutable policy or conversion of existing filesystems is requested.

## Implementation

1. Add an additive Goose migration and update disposable integration fixtures to load the migration chain. Do not apply to live databases; operators must back up before upgrading.
2. Extend protobuf, adapters and Go/Python clients. Keep false omitted from creation fingerprints so existing receipts replay.
3. Load policy with filesystem sessions; validate create/replace/output bytes and reject object upload admission. Process restricted sources as text regardless of filename.
4. Cover default/restricted provisioning, replay/conflicts, text/binary/size boundaries, unchanged failed writes, uploads, copy, processing and transport/client propagation.
5. Generate/check contracts; run focused and affected Go/Python checks; review the diff and update owning docs.

Acceptance: opted-in filesystem metadata reports true; valid text and directories work; invalid UTF-8/control bytes and S3 admissions fail without data/quota changes; processing cannot introduce binary/object payloads; ordinary filesystems retain arbitrary byte support.

Risk: the new binary requires migration 0002 before startup. Rollback to the previous binary can leave the additive column in place, but that binary cannot enforce the policy, so fence restricted-filesystem writes during rollback.

## Verification

- Passed focused UTF-8/control-byte and legacy creation-fingerprint unit checks, followed by all unit tests in LetFS, shared Go, Workspace and Account.
- Passed real PostgreSQL/SpiceDB integration for the new policy and existing provisioning/replay, node writes/quota, parsing/output publication, reprocessing, enrichment and copy. Existing object-output tests also passed with MinIO.
- Passed HTTP filesystem metadata/rejection, authenticated gRPC filesystem reads and both administration creation surfaces; composite storage deletion ran through real Temporal.
- Passed `pnpm contracts:check`, Python lint/format and all Python unit tests (22 passed, one integration-marked test deselected).
- Passed `pnpm exec turbo run check build test:workflow --filter=@openlet/letfs --filter=@openlet/workspace --filter=@openlet/account --filter=@openlet/go --concurrency=1` (11 tasks). The final optional Go argument compatibility adjustment passed client tests and the shared Go check again.
- Reviewed all payload producers: create/replace and processing outputs validate bytes; public/processing object admission is blocked; same-filesystem copy preserves validated bytes. Scoped simplifier review ran clean. Diff whitespace and affected documentation links passed.

No live database was modified; integration dependencies were disposable and cleaned up. Full Compose API E2E, external providers and deployment/migration on existing operational data were not run.
