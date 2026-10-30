> Historical report. Implementation recommendations are superseded by the [2026-10-29 researched plan](../261029-1220-openlet-backend-mvp/plan.md); not current architecture authority.

# Openlet specification and plan validation

Date: 2026-10-29, Asia/Ho_Chi_Minh. Scope: documentation/specification only. No application implementation or runtime validation.


## Accepted contract

The user accepted manually shared invitation links, no Viewer trash access, and within-filesystem copy/move. The delivery is the technical specification and ordered implementation plan; no new product interview was needed. Existing stack/quota/Temporal decisions are preserved.

The user subsequently rejected a custom gateway and questioned application leases. The final specification uses an existing Envoy gateway through configuration, and removes the application lease subsystem. No custom gateway code was written.

## Evidence and checks

- Workspace contained an empty README, an unfinished plan scaffold and the tree research report; no application modules existed.
- Read the existing scaffold, tree research, complete compact handoff, development rules and planning instructions before authoring.
- Temporal SDK research uses primary documentation and pinned source/release tags. Native Rust is documented; real Go/Rust compatibility is deliberately phase-1 work.
- Envoy's official [JWT filter documentation](https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/jwt_authn_filter) documents remote JWKS and claim-to-header support. Exact stable image/configuration validation is phase-1 work; the `latest` docs are not an image version pin.
- `ak plan validate plans/261029-1036-openlet-backend-mvp --json` passed after final edits, returning `valid: true` and no errors.
- Final documentation checks read 15 files and passed local links, fences, size limits, scaffold cleanup, sequential dependencies, unchecked implementation status and absence of stale custom-gateway/lease contracts. New implementation paths and Make targets are explicitly planned, not claimed to exist.
- The plan is indexed and pinned through the live AgentKit CLI. Its live help states files own titles/status/content and reindex never writes plan files; the index table was reconciled in the file accordingly.
- No live task-management surface was available. All six phase checklists remain unchecked; no implementation phase is marked complete.

## Independent review and adjudication

Four review lenses examined the draft: security, failure modes, assumptions and scope/contracts. They returned 17 initial findings, including overlapping ownership/status concerns. Findings are design defects, not discovered runtime vulnerabilities. Routine technical repairs stay within the authorized specification scope; no accepted product decision was reversed.

| Concern | Final disposition |
|---|---|
| Content loses bucket attribution after deletion | Added immutable content bucket ownership and retained bucket/upload cleanup tombstones. |
| Request fingerprints absent from durable operation schema | Added caller/action/scope/key uniqueness and canonical request fingerprints in every owner DB. |
| Status lacks caller binding before first activity | Require committed first-activity admission before 202; timeout uses same-key retry. |
| Closed workflow before admission cannot safely retry | Explicit running-conflict and closed-run reuse policy, with durable recheck and tests. |
| Local admin authority may be stale after waiting | Re-read actor membership/role under the workspace lock. |
| ID/cwd access could escape subtree mounts | MVP mounts explicitly expose whole filesystem roots; subtree configurations are rejected. |
| Invitation response caching may retain secrets | Require no-store responses and token redaction in logs/tracing. |
| Multi-database backups lack a consistent cut | Specify a maintenance window with admission stopped and workers/Temporal quiesced. |
| Upload takeover/cleanup races | Removed takeover/resume instead of adding leases: one CAS-claimed transfer per upload, immutable key, terminal-state checks and retained cleanup evidence. |
| Cleanup guesses whether a copy is abandoned | No expiry lease. Use durable staging/discarding/published states; recover only after confirmed workflow closure, never silence/NotFound. |
| Downloads overlap object reclamation | No per-read lease. Enforce a request deadline shorter than object GC grace; no direct object URLs bypass metadata checks. |
| Temporal queue treated as caller authentication | Explicit private/authenticated trusted backend control plane. Custom per-activity signing was rejected as unnecessary for this MVP trust model; independently trusted workers require revisiting isolation. |
| Rust compatibility gate permits ambiguous partial results | Mandatory boundary matrix; retain a reproducer and resolve architecture before proceeding after an incompatible result. |
| Overwrite uses two precondition protocols | If-Match at upload initialization, persisted/rechecked at finalize. |
| Undefined administrative limit service | Removed the unowned internal Workspace administration endpoint. Initial limit comes from configured Workspace policy. |
| Member cap has no default | Unlimited default; configurable Workspace policy, no billing entitlement implementation. |
| Usage/invite-list routes lack explicit owner | Assigned both routes and focused role/pagination checks to phase 2. |
| Custom Go gateway was unrequested | Removed gateway application/module work; use Envoy native routing/JWT/header configuration. |

Reviewers verified several early fixes before the final user-requested simplification. The final no-lease/Envoy design has a controller consistency review, not a claimed independent runtime or security certification.

## Whole-plan consistency sweep

Read `plan.md`, all six phase files and all five current docs. Check links, scaffold placeholders, fences, phase dependency order, accepted product decisions and stale custom-gateway/lease references. Reconcile implementation ownership and tests with the final contracts. The SDK report is evidence; architecture/API/data/workflow documents own the current direction.

Risk boundaries remain explicit: commit-time quota can reject a completed transfer; filesystem-wide copy fences can fail on unrelated edits; a failed byte transfer restarts with a new upload; downloads have a bounded lifetime; unknown Temporal status delays abandoned-copy cleanup; physical GC can lag logical deletion. These are stated trade-offs, not hidden incomplete features.

## Remaining verification

No Go/Rust build, migration, query plan, Compose runtime, Clerk call, S3 operation, workflow replay or benchmark was run. These checks require the implementation delivered by the plan. No current SDK/server compatibility matrix or latency claim is asserted.

No unresolved product question blocks phase 1. Pin/test exact dependency versions and gateway configuration there; actual external credentials are needed only for live integration checks.
