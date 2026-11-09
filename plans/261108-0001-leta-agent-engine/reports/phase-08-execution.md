# Phase 08 execution checkpoint

Status: implemented and focused integration passed. Phase09 Temporal inbox is next. The runtime/LLM roster and public APIs remain in their owning later phases; this phase does not claim a runnable full agent engine.

## Delivered

- `filesystem/workspace.py` creates and closes one pinned Mirage workspace/session per invocation, borrowing application clients. Current accessible-scope pages yield root home, shared and approved human mounts. Leti inherits root authority and binds home to its persisted live box directory. Safe refresh replaces changed mounts without sharing session state across agents.
- `letfs_vfs.py` implements applicable native hooks: truthful stat, directory/tree listing, selected/range/head/tail reads, counts/checksums, image reads, literal candidates, semantic search, bounded read-ahead, conditional small-text writes/append/patch/truncate/edit/create, directory creation, native copy/move/trash and invocation-local follow polling. Unsupported metadata is not fabricated. Copy across mounts retains blob storage rather than copying metadata JSON as content.
- `access_policy.py` checks current native content/metadata authority and fingerprints before Mirage cache I/O. Actual Redis FRESH caching invalidates outdated same-command reads through public cache methods. Blob metadata/tree changes invalidate cached representations even when the original source revision stays unchanged. Native root and provenance checks remain authoritative.
- Seven direct tool wrappers share one session. Images return supported bounded previews via read_file; blobs return metadata plus the ordinary artifact tree. Python uses Monty with the same mounts, a16MiB memory ceiling and no host/environment/network access. Shell output/deadline limits close executions through Mirage's public collect context. VFS guidance is generated from current mounts.

## Verification and review

- Final native gate: `OPENLET_MIRAGE_INTEGRATION=1 go -C apps/letfs test -race -tags integration ./internal/transport/grpc -run '^TestIntegrationMirageLetFS$' -count=1 -v` passed16.681s. Its three Python journeys passed6.51s against real authenticated LetFS, PostgreSQL, SpiceDB, Redis and Monty. Log `/tmp/openlet-leta-phase08-hooks-race.log`.
- Journeys cover truthful FILE/artifact paths by name and original ID, metadata-only blob reads, generated-artifact write denial, box-root alias escape denial, selected bytes/lines/count/digest, write guards and stale replacement, native append/follow, read-ahead bounds, tree entries, copy across mount roots, shell mutations, parent/child isolation, images, mount read/write refresh and borrowed-client lifetime.
- Cache journey covers external writes between invocations and between two reads in one command, processing-only metadata changes with unchanged source revision, actual Redis outage, warm-cache revocation and denied guest network traffic. Monty tests cover file mounts, host-file/import denial and actual memory exhaustion. Shell tests cover output overflow, timeout and no live processes afterward; follow unit tests cover fragments, offset reads and cancellation.
- Focused workspace/VFS unit tests:7 passed0.70s. Ruff check/format, generated contracts check and whitespace check passed. Previous phases retain their broader Go regression evidence; this phase ran the focused native race gate rather than repeating unchanged full suites.
- Scoped source review covered mount authority, cache-before-admission ordering, both copy endpoints, borrowed-client ownership and shell collect cleanup. An added direct-backend replacement test initially read through a deliberately policy-free facade and observed its old cache; the test now checks native bytes directly, while the separate production-policy journey proves external-change invalidation. No cache workaround or production permission relaxation was added.

## Continuation

Implement phase09's AgentWorkflow, SQL Local Activities and Update-with-Start bridge; then phase10's actual checkpointed runner. Do not register a successful placeholder runner. Lifecycle/HITL/schedule workflows and Redis event publication remain with their planned phases. No paid inference, persistent reset, commit, push or deployment occurred. Owned fixtures exited; existing agent-lab containers remain untouched.
