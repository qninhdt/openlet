> Historical snapshot, superseded on 2026-10-30 by the user-approved [direct-child artifact plan](../261029-1624-artifact-file-processing/plan.md). Its schema, path, ownership and pending-review statements describe the previous draft; do not execute them. Use the current plan and [validation report](./validation-261030-0737-hybrid-artifact-plan.md). General runtime/source evidence remains useful where the current plan retains it.

# Artifact File Processing Plan — Security Adversary Review

## Scope and verdict

Reviewed the four plan files, the relevant artifact/runtime research, and the current letfs resolver, HTTP/authentication, storage/upload, copy/trash/deletion, Compose, and Workspace authorization paths. This is a plan review only; no code, tests, lint, typecheck, or build was run.

**Verdict: BLOCKED on two High-severity plan gaps.** The source-authorization, artifact-liveness, read-only, stale-attempt, final-key, quota-publication, and cleanup design is otherwise explicitly covered.

## Findings

### High — The untrusted Docling child is not isolated from worker credentials or network

**Plan evidence:** Phase 2 gives the Python worker a processor token and Temporal connection (`phase-02-processing.md:27`), then launches Docling as a child process (`phase-02-processing.md:38`, `phase-02-processing.md:56-57`). The planned container is only described as non-root/offline (`phase-02-processing.md:28`, `phase-02-processing.md:73`, `phase-02-processing.md:110`), and Compose work mentions CPU/memory/tmpfs but not credential, file-descriptor, process, or network isolation (`phase-02-processing.md:96`). Phase 3 only proves that the *container* has no DB/S3 secrets (`phase-03-acceptance.md:151`).

**Source evidence:** Temporal currently runs with `--allow-no-auth` on the shared backend network (`deploy/compose.yaml:54-61`). Service credentials are mounted into containers and connection details are environment/config inputs (`deploy/compose.yaml:3-8`, `services/letfs/src/config.rs:37-55`). The current internal letfs boundary is a bearer token accepted across private routes (`services/letfs/src/http/mod.rs:132-149`, `services/letfs/src/http/mod.rs:151-182`). A normal subprocess inherits environment and open file descriptors unless the implementation deliberately prevents it.

**Attack scenario:** A crafted PDF/Office document exploits Docling or one of its native/parser dependencies, or triggers an external-resource fetch. Code executing in the conversion child can inherit/read the route-limited letfs token or Temporal connection material and can reach the backend network. It can then mint source/staging capabilities, interfere with unauthenticated Temporal state, probe internal services, or exfiltrate document data. Non-root and memory limits reduce host impact but do not preserve the intended credential boundary.

**Minimal correction:** Make “the conversion child has no credentials and no network” an explicit requirement and acceptance gate. Spawn it with a strict environment allowlist, closed unrelated file descriptors, a separate scratch-only filesystem view, and no network namespace/access; apply `no-new-privileges`, drop capabilities, and use a read-only root filesystem where supported. Keep all authenticated letfs/Temporal I/O in the parent activity. Add a malicious fixture/test that attempts environment/secret reads, backend/outbound connections, and external relationship/resource fetches and proves they fail.

### High — Presigned PUT can become an unbounded, uncharged storage-write capability

**Plan evidence:** Phase 2 binds exact length/checksum/conditional-create only “where the provider test proves support” (`phase-02-processing.md:31`) while staging is deliberately uncharged until publication (`plan.md:25`). Validation happens after upload (`phase-02-processing.md:32-33`, `phase-02-processing.md:58-59`). Phase 3 tests mismatch semantics (`phase-03-acceptance.md:33-34`) but does not say providers must fail closed when request-size binding is unavailable.

**Source evidence:** The current authenticated upload path enforces `MAX_FILE_BYTES` while streaming (`services/letfs/src/fs/uploads.rs:129-150`) and terminates transfer after 120 seconds (`services/letfs/src/fs/uploads.rs:102-105`). Direct object-store PUT URLs bypass that server-side byte counter. Current capacity admission bounds the number of outstanding uploads/operations, not provider bytes (`services/letfs/src/fs/uploads.rs:14-25`).

**Attack scenario:** A compromised worker requests a legitimate staging handle, then uses a replayable PUT URL to upload an object much larger than the declared output when the provider does not enforce the signed `Content-Length`. Rust later rejects publication, but the oversized object already consumes storage/bandwidth and remains until cleanup grace. Repeating this across the allowed outstanding handles creates storage-cost/availability impact without filesystem quota admission.

**Minimal correction:** Treat enforceable maximum/exact request length as mandatory for direct presigned PUT, independent of optional checksum and `If-None-Match` support. If a provider cannot prove it, do not issue a PUT URL; use a bounded authenticated streaming endpoint with the existing byte/deadline pattern. Make SeaweedFS and R2 acceptance assert both oversize rejection at upload time and no oversized object persisted; unsupported semantics must block release rather than silently weaken the capability.

## Verified caller and boundary coverage

- Resolver consumers were enumerated: node batch/read/create/modify (`services/letfs/src/fs/nodes.rs:235`, `services/letfs/src/fs/nodes.rs:242`, `services/letfs/src/fs/nodes.rs:282`, `services/letfs/src/fs/nodes.rs:314`), upload targets (`services/letfs/src/fs/uploads.rs:36`, `services/letfs/src/fs/uploads.rs:53`), copy and durable rechecks (`services/letfs/src/fs/copy.rs:20`, `services/letfs/src/fs/copy.rs:115`, `services/letfs/src/fs/copy.rs:225`, `services/letfs/src/fs/copy.rs:455`), trash/restore (`services/letfs/src/fs/trash.rs:42`, `services/letfs/src/fs/trash.rs:70`), and content reads (`services/letfs/src/http/mod.rs:371-380`). Phase 1 explicitly requires updating every resolver caller and central writable enforcement (`phase-01-artifacts.md:82-84`).
- Workspace remains the public authorization boundary: file actions authorize membership/role before resolving storage (`services/workspace/internal/http/files.go:61-80`), streaming uploads separately require editor access (`services/workspace/internal/http/files.go:280-300`), and the plan explicitly forbids status/root-ID leakage (`phase-01-artifacts.md:140`).
- Already covered, not findings: source-live owner-aware resolution and hidden trash/staging/foreign IDs (`phase-01-artifacts.md:33-35`, `phase-01-artifacts.md:95`); stale attempt/source fencing (`phase-02-processing.md:35-37`); final keys never exposed as writable capabilities (`phase-02-processing.md:32`); no network I/O under DB locks and atomic publication (`phase-02-processing.md:59`, `phase-02-processing.md:153`); bearer URL redaction and expiry/grace recovery (`phase-02-processing.md:34`, `phase-02-processing.md:162`, `phase-03-acceptance.md:33-35`, `phase-03-acceptance.md:150-151`).

## Unresolved questions

None. Both corrections are implementation constraints within the accepted architecture; neither requires an additional workflow/activity, Python DB/S3 credentials, a new artifact registry, or a change to the accepted artifact ownership model.

Status: DONE
Summary: The plan is strong on authorization, liveness, atomicity, and stale-output fencing, but must explicitly isolate the untrusted conversion child and fail closed when presigned PUT size cannot be provider-enforced.
Concerns/Blockers: Two High-severity release blockers above.
