# Openlet Backend MVP Security Adversary and Fact Check

## Scope and verdict

Reviewed `plan.md`, all six phase files, and `docs/{architecture,data-model,api-contracts,workflows,testing}.md` only. The design is generally explicit about identity forwarding, service authentication, authorization rechecks, hidden storage states, caller-bound operations, and recovery. Four material gaps remain; two can expose data or infrastructure cost directly.

The repository-state claims are accurate: `git rev-parse --verify HEAD` reports no committed revision, and the planned `services/`, `contracts/`, `deploy/`, `scripts/`, `tests/`, `go.work`, `Makefile`, and `.env.example` paths are absent. This matches the plan's "no application implementation" statement (`plans/261029-1220-openlet-backend-mvp/plan.md:18`) and its explicit planned-creation wording (`plans/261029-1220-openlet-backend-mvp/plan.md:39`, `plans/261029-1220-openlet-backend-mvp/phase-01-start.md:25`). No planned command or integration result was treated as existing evidence.

## Findings

### 1. High - Uncharged upload/copy objects have no abuse bound

**Evidence:** Logical quota is charged only at publication, transfers may complete before quota rejection, and physical staging is explicitly separate (`docs/architecture.md:65`). Staging is unreachable and uncharged until publication (`docs/data-model.md:42`); failed upload bytes remain uncharged until later cleanup (`plans/261029-1220-openlet-backend-mvp/phase-04-storage-and-copy.md:40`), and the accepted design has no logical reservation (`plans/261029-1220-openlet-backend-mvp/phase-04-storage-and-copy.md:57`). Configuration lists per-request limits and expiry but no bound on outstanding candidate/staging bytes or cleanup backlog (`docs/architecture.md:99`).

**Concrete failure:** An authenticated Editor can repeatedly upload maximum-size candidates or start copies that fail final quota admission. Each object is uncharged and remains until asynchronous cleanup. Per-request size/rate limits slow the attack but do not cap accumulated S3 cost or cleanup work, especially when the provider or maintenance worker is degraded.

**Smallest correction:** Add a separate operational admission bound, not logical quota reservation: cap outstanding candidate/staging/cleanup bytes and counts per workspace (including terminal objects awaiting confirmed deletion), stop streams at the bound, and reject new upload/copy admission until cleanup reduces it. Add a deterministic test proving repeated quota-finalization failure cannot grow physical outstanding storage beyond the configured cap.

### 2. High - External S3 confidentiality requirements are unspecified

**Evidence:** Production storage may use a configurable external S3-compatible endpoint (`plans/261029-1220-openlet-backend-mvp/phase-04-storage-and-copy.md:52`, `docs/architecture.md:63`). Phase 1 only says URLs and credentials are validated (`plans/261029-1220-openlet-backend-mvp/phase-01-start.md:46`), while provider tests cover put/copy/range/delete/version behavior, not transport or bucket exposure (`docs/testing.md:39`). The only explicit encrypted-transport rule is for internal HTTP crossing an untrusted network (`docs/architecture.md:49`).

**Concrete failure:** A non-local `http://` S3 endpoint exposes object bytes and provider credentials in transit. A bucket/object configuration permitting public reads can expose every stored file even though the public API and letfs authorization are correct.

**Smallest correction:** Require TLS with certificate verification for non-loopback S3 endpoints, use private objects/no public ACLs, and document the minimum bucket credential permissions. Extend the real-provider release smoke to prove anonymous reads fail and the configured client cannot perform unnecessary bucket-administration actions. Keep plaintext local endpoints limited to the explicit test/development profile.

### 3. Medium - Byte quota does not bound zero-byte metadata exhaustion

**Evidence:** The only storage quota is a logical byte counter (`docs/architecture.md:65`, `docs/data-model.md:31`). Phase 3 requires "configured bounds" but does not name a node-count invariant (`plans/261029-1220-openlet-backend-mvp/phase-03-filesystem-core.md:46`), and the configuration inventory omits per-filesystem node or outstanding-operation counts (`docs/architecture.md:99`). Empty directories and empty files therefore consume no byte quota.

**Concrete failure:** An authenticated Editor can create arbitrarily many empty nodes. This can exhaust PostgreSQL storage, inflate recursive deletion/copy work, and make workspace cleanup operationally unbounded despite the workspace remaining under byte quota.

**Smallest correction:** Define a configurable hard node-count limit per quota bucket/filesystem, maintain it transactionally with node creation/removal, and test concurrent empty-node creation at the boundary. This is a resource-safety bound, not billing or a new quota framework.

### 4. Medium - Member enrichment does not define a privacy-safe projection

**Evidence:** User owns the application profile (`docs/architecture.md:18`), Viewer can list members with a batch profile lookup (`docs/api-contracts.md:41`), and the internal contract says "bounded batch profiles" (`docs/api-contracts.md:85`). Phase 2 instead calls this a bounded "user-summary" API (`plans/261029-1220-openlet-backend-mvp/phase-02-identity-workspaces.md:59`), but no document defines which fields are safe for workspace members.

**Concrete failure:** An implementation can reuse the `/me` profile DTO for member enrichment and disclose private profile fields to every Viewer. The service boundary and role checks would all pass, so this leak is unlikely to be caught by authorization-only tests.

**Smallest correction:** Define a distinct allowlisted member-summary DTO (for example internal user ID plus explicitly public display fields), forbid verified email and other private/self-only fields, and add a contract test proving the batch response cannot serialize self-profile-only data.

## Non-findings checked

- Plain caller-bound workflow identity is an accepted design, not a missing HMAC: private authenticated HTTP and DB scope/fingerprint binding are explicit (`docs/workflows.md:67`, `docs/api-contracts.md:15`).
- Owner-local Temporal workers with HTTP coordination are consistently specified; no Go-to-Rust Temporal bridge is required (`docs/workflows.md:15`).
- Invitation tokens use 32 random bytes and store only SHA-256, so unsalted hashing is not a practical offline-guessing defect (`docs/data-model.md:25`).
- In-flight completion after membership revocation is an explicit authorization semantic, not an accidental omission (`docs/architecture.md:51`).

## Unresolved questions

- Which profile fields, if any, are intended to be visible to other workspace members? The current documents do not establish that product decision.

Status: DONE

Summary: Four evidence-backed plan gaps found: unbounded uncharged storage, missing external S3 security baseline, unbounded zero-byte metadata, and an undefined member-summary privacy boundary.

Concerns/Blockers: None. No implementation or application tests exist to review; this report does not validate future provider behavior.

## Correction verification - 2026-10-29

All four findings are now assigned and resolved at plan level. External S3 requires verified TLS, private objects and object-only credentials, with provider checks for TLS, rejected anonymous reads and credential scope (`docs/architecture.md:63`, `plans/261029-1220-openlet-backend-mvp/phase-04-storage-and-copy.md:52`, `docs/testing.md:39`). Member enrichment is an explicit allowlisted `{id,display_name,avatar_url}` DTO, excludes self-only/identity fields, validates returned membership IDs and has a contract check (`docs/api-contracts.md:87`, `plans/261029-1220-openlet-backend-mvp/phase-02-identity-workspaces.md:59`, `docs/testing.md:22`). Node exhaustion is owned by letfs through a transactional configured node-count cap under the existing filesystem lock, including empty, trash and staging nodes, with concurrent-boundary and reconciliation tests (`docs/data-model.md:32`, `docs/data-model.md:57`, `plans/261029-1220-openlet-backend-mvp/phase-03-filesystem-core.md:47`, `plans/261029-1220-openlet-backend-mvp/phase-03-filesystem-core.md:78`, `docs/testing.md:30`). Upload/copy abuse is bounded through per-bucket outstanding-operation and cleanup-backlog counts from existing rows, finite file/copy byte, node and runtime ceilings, retained ambiguous terminal evidence, and fail-closed admission when cleanup stalls (`docs/data-model.md:63`, `plans/261029-1220-openlet-backend-mvp/phase-04-storage-and-copy.md:67`, `plans/261029-1220-openlet-backend-mvp/phase-04-storage-and-copy.md:71`, `docs/testing.md:28`). This is explicitly bounded backpressure, not exact physical-byte accounting or a logical reservation ledger (`docs/data-model.md:63`, `docs/architecture.md:99`), so it preserves the accepted no-reservation scope. Remaining plan-level blockers for these four findings: none; implementation and provider verification remain future phase deliverables.
