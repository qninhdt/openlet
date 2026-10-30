---
title: Verify processing across Rust Temporal and Python
date: 2026-10-30
summary: Four real format E2E journeys and replay pass after container environment and shutdown fixes.
---

# Verify processing across Rust Temporal and Python

## What happened

Recovered the active processing phase after compaction. Python parser tests and the image existed, but the recorded E2E had failed before the worker started: YAML split unquoted tmpfs options into separate mount entries.

Real container execution then exposed missing HOME and USER in the intentionally minimal child environment. Docling and PyTorch need them even for a non-root container UID without a passwd entry. The child now uses its job scratch as HOME and a fixed non-secret USER; credentials remain excluded.

SDK cancellation tests also reproduced terminal abort on worker shutdown. Only an explicit cancellation request now invokes terminal abort; worker shutdown remains retryable. Child termination and scratch cleanup still apply.

## Verification

Twelve Python tests passed, including real PDF/DOCX/PPTX/XLSX parsing and shutdown/cancellation regressions. All four formats passed the real Compose E2E. Their captured histories replayed successfully with exactly one Python activity each. Native verification passed; post-E2E contract validation checked 511 DTOs. Existing unchanged Rust processing integration evidence covers five real-dependency artifact tests.

All test/debug containers and foreground test sessions finished. Processing evidence is in plans/reports/implementation-261030-processing.md. Phase checklists now show three of five phases done.

## Next steps

ZIP export remains Phase 4. Phase 5 still owns broader failure/restart, processing/export-aware backup/restore, external coordinated R2 recovery and independent release review. Local backup now stops/checks the Python worker, but its full drill was not run in this checkpoint. No commit or deployment was performed.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
