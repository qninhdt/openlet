---
title: Scope blob and indexing options
status: completed
---

# Scope file options

Move the immutable filesystem restriction to scopes as `allow_blob_files`, and add
independent `allow_indexing`. Both default true. Remove `inline_text_only` from
runtime contracts, schema, clients and current docs. No persistent database changes,
compatibility layer, new workflow/activity, mutable-policy API or unrelated fixes.

- [x] Replace filesystem configuration with immutable scope creation options in SQL,
  domain, gRPC, Temporal DTOs and Go/Python SDKs. Creation retries reject mismatches.
- [x] Enforce blob restrictions in uploads, processor outputs and cross-scope copy;
  preserve restricted inline UTF-8 validation and text routing.
- [x] Skip indexing for disabled scopes without disabling parsing/enrichment; fence
  direct indexing, dispatch/reconciliation and index backfill.
- [x] Update focused isolation/retry/processing/transport/client tests, regenerate
  contracts and update owning documentation. Remove obsolete migration and symbols.
- [x] Run focused integration/workflow tests and affected checks; review final diff.

Acceptance: two scopes in the same filesystem may have different options; defaults
retain existing behavior; forbidden blob/index work cannot cross entry paths; no
executable old configuration remains. Test databases are fresh and disposable.

## Verification

- Passed the two focused PostgreSQL/SpiceDB scope-option regressions and twelve
  Python SDK tests. They cover same-filesystem isolation, default values, creation
  retry conflicts, restricted uploads/copy/output, retained enrichment, direct
  index fencing, dispatch/backfill exclusion and provider-free empty search.
- Passed `pnpm contracts:check`, `pnpm check`, `pnpm build`, `pnpm test` and
  `pnpm check:e2e`. Passed LetFS and Workspace `test:workflow` commands.
- Passed `go test -race -tags integration ./...` in `apps/letfs`, including
  filesystem, Temporal, gRPC and HTTP suites. Native integration includes replay.
- Independent simplification review found no concrete defect or useful reduction.
  Legacy-symbol scan, changed-document links and `git diff --check` passed.
- Initial code generation lacked Go on PATH; rerunning with the repository's
  documented `/usr/local/go/bin` toolchain succeeded. A formatter command initially
  used root-relative paths from a service directory; it was rerun from the root.
- Test-owned processes and containers were cleaned up. Browser/API E2E was not
  rerun; no persistent database migration/reset, commit, push or deployment ran.
