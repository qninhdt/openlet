# Leta persistence implementation

User accepted all phase-1 findings and necessary benchmarks on 2026-11-09. Scope is findings 1–8 plus the structural cleanup discussed in the audit; phases 2–7 remain separate work.

## Contract

Remove unused read APIs and write-on-read, avoid graph overfetch and deletion-only pause reads, deduplicate self-target admission, and remove unused graph insert results. Validate rejected schedules before the API reservation transaction commits while keeping the saved request timestamp authoritative for relative schedules. Move domain errors out of persistence and separate schedule validation from SDK compilation. Preserve API/schema, ownership, root-first locks, atomic graph creation, checkpoint publication and durable workflow names/payloads. No dependency, migration or deployment. Commit and push were authorized separately after verification.

## Execution

- [x] Add focused regressions for rejected schedules and active read/mark-read boundaries.
- [x] Update Store, metadata/graph callers, inbox helpers and affected tests together.
- [x] Separate domain error ownership and schedule validation/compilation; assess extraction after cleanup.
- [x] Compare before/after Store operations on owned PostgreSQL; interleave implementations, validate actual rows and report limitations.
- [x] Run focused checks, Leta lint/unit/integration/replay, cross-service acceptance as required; review diff and stop owned resources.

Benchmark compares metadata reads, pause, self-target schedule changes, fixed transaction overhead and graph creation at small/medium/larger sizes. It times awaited Store operations including SQL transactions, not HTTP/model latency. At least five alternating rounds per variant, same process/pool/migrations/data shape; report median/range and cursor calls separately. Keep a change only with preserved behavior; do not infer production throughput from local serial measurements.

The measured run also includes a local ASGI box-schedule listing request with real SQL and fake external authorization. Results and final verification are recorded in [the implementation report](../reports/refactor-261109-leta-persistence.md).

Validation admission differs from the initial pre-validation sketch: a synchronous validator runs under the reservation transaction and uses its saved timestamp. This rolls back rejected inserts without changing completed-retry behavior when the current schedule has since changed. No remote work runs under that transaction. Existing compiler and domain validators retain their responsibilities; SQL no longer constructs native schedules just to validate a patch.

After cleanup, keep the existing Store boundary for this batch. Moving the remaining schedule methods mechanically would require shared transaction/admission helpers or forwarding. The concrete boundary changes here are domain error ownership and validation versus native compilation; no repository hierarchy or mixins are added.

Rollback is the source diff for this implementation, preserving existing plan/audit records and unrelated work; never reset live data. Existing pending reservations are not bulk-deleted because unknown Temporal outcomes need reconciliation.
