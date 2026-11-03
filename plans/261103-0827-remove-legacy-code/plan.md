---
title: "Remove dead and legacy code; review the complete backend"
status: complete
branch: dev
---

# Outcome

Remove verified unreachable code, unused compatibility options and obsolete migration scaffolding across current application code, contracts, tests, tooling and documentation. Review first-party Go/Python/TypeScript source using ponytail-review: correctness, security, concurrency, tests, cost and unnecessary code. Preserve accepted filesystem/authorization behavior, existing user changes and historical records. No database changes, dependency upgrades, product features, commit or deployment.

## Scope and evidence

The worktree contains the completed, uncommitted Go/SpiceDB migration. Current architecture is in `docs/`; prior acceptance is in `plans/261102-1059-go-grpc-filesystem-authorization/reports/acceptance.md`. Public clients use direct letfs HTTP/native gRPC. Workspace storage-action delegation and service-user impersonation are obsolete.

## Tasks

- [x] Read instructions, ponytail-review, current entry points/callers and existing checks.
- [x] Analyze all four Go modules and Python source; inspect reachable contracts, lifecycle and transport boundaries. Verify candidates before deletion.
- [x] Remove obsolete proxy/delegation/generated-gateway scaffolding; update affected callers, tests, codegen and docs together.
- [x] Fix concrete review findings and obsolete dependency API usage without speculative redesign.
- [x] Run focused checks, then affected integration, API and replay checks.
- [x] Review final scoped changes; record findings, fixes, evidence and material limits.

## Acceptance

No verified dead production function or obsolete first-party compatibility branch remains in inspected configurations. Current behaviors retain meaningful tests against their real owner. Codegen is reproducible; build, check, unit and affected integration/API gates pass. Static analysis failures are distinguished from application findings. Retain protobuf safety reservations, SDK integrations, supported file formats and historical plans: names alone do not establish dead code.

Report: [review and results](../reports/review-261103-0827-remove-legacy-code.md).
