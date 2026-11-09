---
title: "Phase 6: Atomic small-text mutations and native node operations"
status: in-progress
priority: P1
effort: 4d
dependencies: [5]
---

# Phase 6: Atomic small-text mutations and native node operations

## Outcome

Implement bounded unary write/append/edit/positional-write/truncate against phase 5's small TEXT. Complete native node methods needed by Mirage while preserving current identity/revision guards, quotas, processing fencing, trash and no-overwrite/partial-copy behavior. The backend owns data invariants; Mirage owns commands and their parsing.

Read the [accepted design](../reports/design-261108-0148-leta-workspace-resource.md), [storage/read phase](phase-05-letfs-inline-text-and-reads.md), [search phase](phase-07-letfs-native-text-search.md) and [adapter phase](phase-08-mirage-workspace-adapter.md). Implementation and acceptance checks are complete; [execution evidence](reports/phase-06-execution.md) records full LetFS race regression, native response-loss/concurrency checks and typed clients. Current state is derived from checked tasks by `ak plan status`. Continue with phase07. No persistent environment was changed.

## Current owners and callers

All paths are relative to `/home/qninh/projects/openlet`.

- `apps/letfs/internal/filesystem/node_writes.go::CreateNode` has an actor/scope/request-key receipt with 24-hour expiry and accepts an optional UUIDv7, otherwise allocating server-side. Native text creation reuses this route with an explicit TEXT fingerprint; no permanent receipt was added.
- `node_writes.go::ReplaceContent` authorizes, resolves, checks node identity/revision/readonly, charges the size delta, invalidates processing, queues obsolete objects, writes payload and records processing intent. Owner replacement can convert blobs; new agent text APIs must refuse that conversion.
- `nodes.go::openSession` serializes writes with the existing filesystem/scope locks. `service.go::ReplaceContent` dispatches processing after commit; reuse that durable pending-work path.
- `copy.go`/`copy_data.go` implement bounded direct copy, independent object keys and retained partial outputs. `trash.go` detaches a subtree and retains quota. `scope_move.go` moves same-filesystem subtrees under current source/destination checks.
- The shared proto, gRPC handlers and Go/Python clients carry Locators and preconditions. Phase 8 calls those methods; lifecycle phase 12 uses stable native directory creation for box homes. No Python Store bypass or duplicate HTTP mutation route is introduced.

## Proposed bounded native text RPCs

Add unary `WriteText`, `AppendText`, `PatchText` and `TruncateText` on `FilesystemService`. Common request fields are filesystem/scope, root-restricted Locator, observed node identity/revision for replacement or explicit absence/parent guards for creation, and media type when creating. `PatchText` has a oneof for byte-offset overwrite or literal replacement.

The body/final stored result must fit `min(InlineLimit, MaxFileBytes)`; validate UTF-8, no U+0000 and existing text-only-scope control rules. The current default is 256 KiB and supported configuration maximum 1 MiB. Validate arithmetic and request bytes before taking SQL locks. An append/replacement that would exceed the final limit fails atomically; it never becomes an object/upload. There are no client-streamed mutation RPCs, large-text buffers, special text concurrency setting or raised shared RPC limit.

| Operation | Existing node | Missing node | Invalid/unsupported behavior |
| --- | --- | --- | --- |
| `WriteText` | Replace TEXT after observed ID/revision match. | Atomic create-if-absent with observed parent identity and current name absence. | Refuse existing binary/object payloads and readonly artifacts. |
| `AppendText` | Append inside the backend transaction after ID/revision match. | Same guarded text creation as WriteText. | Two requests from one observed revision cannot both silently commit. No worker read/merge/write. |
| `PatchText(offset, bytes)` | Overwrite `[offset, offset+len(bytes))`, preserve bytes outside that span and permit extension at EOF. | Offset zero may create under absence guards. | Negative/overflow offsets fail; past-EOF gaps are ENOTSUP; final bytes must remain UTF-8 without NUL. This is overwrite, not insertion. |
| `PatchText(old_text, new_text, replace_all)` | Exact literal replacement in the current guarded TEXT. | Fail. | Empty old text, no matches or multiple matches without replace_all fail; no successful no-op on a missing match. `replace_all` uses nonoverlapping occurrences. |
| `TruncateText(length, no_create)` | Shrink to exact byte length, or retain equal length after guards. | With no_create fail; otherwise length zero may create under absence guards. | Growth is ENOTSUP; cuts inside UTF-8 are invalid; no zero padding or hidden binary conversion. |

PostgreSQL TEXT cannot store NUL, so zero-filled pwrite gaps/truncate growth are deliberately unsupported. Ordinary string write/edit/append is fully supported. Preserve the user's accepted limitation; do not emulate padding with spaces, escapes or another byte store.

Return committed Node/stat, before/after revision, exact size/LF count/SHA-256 and native condition token from the transaction. An unchanged body/length may avoid revision/generation churn only after every current precondition passes. A stale precondition does not become valid because the intended final body equals current content.

## Preconditions, creation and commit sequence

1. Existing-node changes bind both observed node ID and positive revision. Keep existing `ExpectedNodeID`/`ExpectedParentID` path guards; path reuse cannot target a new occupant with the same revision number.
2. Creation binds observed parent identity and name absence under that parent. Extend `CreateNodeRequest`/Go/Python types with optional caller-supplied UUIDv7 `node_id`; omitted retains normal server allocation. Use the existing create-node key/receipt and reject conflicting ID/name/kind rather than adopting an occupied path.
3. Lifecycle persists `boxes.home_node_id` before creating its directory. A retry verifies that exact live node/root/parent/name/kind after receipt expiry; legitimate later contents or revisions do not make the home invalid. A different same-name directory is not proof of successful provisioning.
4. Inside the existing write transaction, recheck lifecycle, typed subject scope permission, backend root, path/node identity, artifact provenance and revision/absence; then lock/read the current TEXT.
5. Derive exact final bytes; validate UTF-8/control/size/overflow; charge `new_size-old_size` through `session.usage`. A shrink works at full quota. Existing detached artifacts remain charged until cleanup.
6. Reuse `session.invalidate`, object/generation cleanup and `recordIntent`. Store TEXT/size/hash/LF count, bump node revision/timestamps and commit together. GIN updates in phase 7 are transactional, never a best-effort job.
7. Dispatch processing after commit through `Service`. A dispatch failure leaves durable pending processing for existing recovery; it does not undo committed content or authorize replay of the write.

Do not hold database locks while consuming request bodies or waiting on Redis, model, Temporal or object-storage calls. Typed subject admission is checked at the trusted native boundary; content operations continue under `leta:L` after approval, never the approver/creator user.

## Native node operations

Extend existing methods rather than adding command-specific backend behavior. New generic `CreateDirectories` is needed only for bounded atomic missing-parent creation; extend `TrashNode` with an optional empty-directory requirement for native `rmdir`. Both use existing locks/guards, not a second filesystem abstraction.

| Adapter operation | Native method and invariant |
| --- | --- |
| `create` | Existing CreateNode/empty text path; atomic create-if-absent, preserve an existing file and fail on an incompatible type. |
| `mkdir(parents)` | Existing CreateNode for one directory; proposed bounded `CreateDirectories` for missing components, validated under the same root. `parents=true` accepts existing ordinary directories; false keeps existing collision errors. |
| `copy`/`dir_copy` | Existing CreateCopy; current source read_content, source identity/revision, destination write and existing stable request key. Preserve readonly source-copy allowances and destination artifact refusal. |
| `copy_from` | Same trusted backend/filesystem cross-mount native copy with independently validated source and destination roots. Do not copy metadata JSON as though it were the original blob. |
| `rename` | Existing UpdateNode/same-filesystem move; source identity/revision and destination parent identity/root, with current no-overwrite collision behavior. |
| `unlink` | Require file, then existing TrashNode. Binary source nodes can be moved/trashed without exposing/editing their bytes. |
| `rmdir` | Require ordinary directory, then TrashNode with atomic emptiness check under the owning lock; ENOTEMPTY leaves it intact. |
| `rm_r` | One TrashNode on the subtree root; backend root and artifact provenance still apply. |

Every removal available to the agent means **trash**, retains charged bytes and remains restorable through existing owner routes. No purge or age-based trash cleanup is added. Root restrictions apply even to direct RPCs, aliases, source/destination lookups and restore.

Keep current no-overwrite and partial-copy contracts. An unsupported overwrite flag reports the actual native error; the adapter must not delete/trash a destination to emulate POSIX replacement. A cross-mount move can be copy-then-trash through Mirage; it is not an atomic rename. Failed directory copy retains already committed output; do not roll it back by deleting user-visible content or automatically retry the entire copy.

## Conditional writes and ordinary recovery

Phase 8 implements Mirage `_replace(ReplaceRequest)` using `ABSENT_WRITE` and `MatchWrite(version)`. Advertise only `condition_support={'put': frozenset({'absent','match'})}` initially. A single versioned native token binds node identity/revision and representation digest; distinguish writable condition revision from content-only drift tokens. `ANY_WRITE` still observes current state and submits the native guard, so a race returns conflict.

For lost acknowledgements, use current authorized state plus existing keys/preconditions: resolve stable created IDs, inspect known node/trash identities and compare guarded intended final state when available. Never retry an unguarded append, remove a replacement path occupant, or infer a unique operation's authorship solely from equal bytes. A different/ambiguous state returns an ordinary conflict/error for agent inspection. Do not add a special outcome state, execution ledger, permanent receipt table or append token registry.

An unfinished shell/Monty call can replay after crash; the user accepts duplicate/partial effects and agent correction. Native preconditions remain required but do not promise exactly-once compound commands. Already saved tool results are reused by phase 10; a stream-publication problem does not replay applied filesystem effects.

## Files and callers to change

| Action | Paths | Responsibility |
| --- | --- | --- |
| Add | `apps/letfs/internal/filesystem/text_mutations.go`, `text_mutations_test.go`, `text_mutations_integration_test.go` | Shared guarded small-TEXT mutations and independently expected byte tests. |
| Modify | `apps/letfs/internal/filesystem/{node_writes,service,nodes,paths,trash,copy,copy_data,scope_move}.go` | Stable optional creation ID; root-preserving operations; atomic directory checks/creation; keep quota/processing behavior. |
| Modify/add | `packages/contracts/proto/openlet_api/letfs/v1/letfs.proto`; `apps/letfs/internal/transport/grpc/text_mutations.go`, existing `filesystem.go`, `copy.go`, `trash.go` | Unary requests/results, generic directory operation fields and all root/precondition mappings. |
| Modify | `packages/go/clients/letfs/{filesystem,operations}.go`; `packages/python/src/openlet/clients/letfs.py`; corresponding client tests | Exact Locators, guards, typed results and ordinary error propagation. |
| Modify | `apps/letfs/cmd/server/main.go` and native admission tests | Add only allowed data methods for trusted `leta` subjects; retain denial of raw blob transfer/ingest/admin/purge. |
| Modify | Existing copy/trash/node/processing/scope integration tests | TEXT and root invariants across actual SQL and gRPC boundaries. |
| Modify | `docs/api-contracts.md`, `docs/data-model.md`, `docs/operations.md` | Small-text/zero-fill limits, trash/no-overwrite/partial-copy behavior and ordinary retry guidance. |

Regenerate contracts, never hand-edit generated clients. Phase 12 owns box state/lifecycle persistence; phase 8 owns VFS body collection and conditional mapping. Integrate shared proto/client edits serially with phases 5 and 7. Do not add a text-write configuration knob.

## Implementation steps

- [x] Add focused tests for concurrent append, literal match cardinality, blob/artifact refusal, inline-size boundary, quota rollback and UTF-8 byte cuts before implementing mutation logic.
- [x] Add optional caller creation ID using existing receipts. Test key replay, expired receipt plus live identity, wrong scope/root and unrelated same-path occupants; coordinate box-home state with phase 12.
- [x] Share only needed invariants from current ReplaceContent; implement unary Write/Append/Patch/Truncate with one owning transaction and committed result tokens.
- [x] Complete generic mkdir/rmdir and Locator-aware wrappers. Test source/destination root checks and artifact-copy permissions through direct authenticated gRPC.
- [x] Add concurrent real-client and response-loss fault tests. Confirm no additional idempotency/receipt table or special replay state appeared.
- [x] Add conditional-write contract fixtures for phase 8, retaining no-overwrite and current partial-copy semantics.
- [x] Regenerate contracts, run focused then shared-contract checks and review storage/quota/processing/authz together before exposing writes.

## Validation

| Scenario | Pass condition |
| --- | --- |
| Two writers append from one revision | One guarded commit; other conflicts unless it explicitly rereads before a later operation. No lost bytes or double unguarded append. |
| Owner update between observation and write | Node/revision conflict; a cache token never authorizes overriding current owner data. |
| Empty/CRLF/multibyte/exact replace | Exact bytes/hash/LF metrics; no-match/ambiguous match fails atomically. |
| Limit/NUL/pwrite gap/truncate growth/split UTF-8 | Typed limit/invalid/ENOTSUP; identical content/revision/quota/processing state afterward. |
| Full quota shrink and invalidated artifacts | Shrink succeeds; retained detached bytes stay charged until real cleanup. |
| rmdir races with child creation | Serialized success or ENOTEMPTY; no committed child is silently lost. |
| Trash file/tree and lost response | Native trash retains quota; replacement occupants are never deleted; owner restore still works. |
| Copy across roots/scopes with mid-copy error | Correct permissions/independent storage keys; committed partial output remains and error propagates. |
| Blob text and readonly artifacts | Agent mutation cannot convert blob to TEXT or change generated children through aliases/IDs. |

Future commands from the repository root; new test names are implementation deliverables:

```sh
pnpm contracts:generate
pnpm contracts:check
go -C apps/letfs test ./internal/filesystem ./internal/transport/grpc
go -C apps/letfs test -race -tags integration ./internal/filesystem ./internal/transport/grpc -run 'Test(TextMutation|ConditionalText|StableNodeCreation|NativeDirectory|Copy|Trash|Scope|Processing)' -count=1
uv run --locked --package openlet-python pytest packages/python/tests/test_letfs_clients.py -q
go -C packages/go test ./clients/letfs
pnpm --filter @openlet/letfs check
pnpm --filter @openlet/letfs test:integration
```

## Acceptance, risks and rollback

- [x] All supported text mutations stay within current inline limits and execute atomically with quota/processing/condition updates.
- [x] Every operation enforces typed subject, root, liveness, identity/revision and readonly invariants at the backend.
- [x] Actual SQL/gRPC concurrency and response-loss tests pass without new receipt infrastructure or exactly-once claims.
- [x] VFS guidance and real errors retain accepted trash/zero-fill/no-overwrite/partial-copy limitations.

The user explicitly waived production-data backup/backward-compatibility requirements. Validate schema and behavior in owned disposable environments; no existing user environment reset or production deployment is authorized. Roll back admission by disabling agent write mounts/tools and draining invocations; keep TEXT-compatible readers and user data/trash. There are no mutation streams to drain and no new buffer setting to remove. Do not deploy old binaries against TEXT rows or delete partial copy output as cleanup.
