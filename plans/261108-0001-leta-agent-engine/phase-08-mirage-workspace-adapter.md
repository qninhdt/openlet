---
title: "Phase 8: Mirage workspace adapter and complete native LetFS hooks"
status: complete
priority: P1
effort: 5d
dependencies: [4, 5, 6, 7]
---

# Phase 8: Mirage workspace adapter and complete native LetFS hooks

## Outcome and dependencies

Give each agent invocation one Mirage workspace/session using the same native LetFS mounts for direct tools, Mirage commands and pinned Monty. Use `mirage-ai==0.0.8` with its `pydantic-monty==1.4.0` extra, verified typed `leta:L` authority, backend subtree roots, required Redis FRESH caching and current permission checks before cache hits.

The [accepted design](../reports/design-261108-0148-leta-workspace-resource.md) and phases 4–7 own resource/scope discovery, [reads](phase-05-letfs-inline-text-and-reads.md), [mutations](phase-06-letfs-text-mutations.md) and [generic text search](phase-07-letfs-native-text-search.md). Phase 10 owns invocation/checkpoint recovery. This phase owns the adapter, not a second filesystem, shell parser or permission authority.

Implementation and focused native/cache/runtime validation are complete; see [execution checkpoint](reports/phase-08-execution.md). Phase01's tiny probe and phase07's search gates were extended here against actual LetFS, PostgreSQL, SpiceDB, Redis and Monty. Current published source was reverified against uv.lock under `/tmp/openlet-mirage-source/mirage_ai-0.0.8/`; the older `/tmp/leta-filesystem-review/src` path no longer exists.

## Mandatory early compatibility gate

Phase 1 must run a tiny real pinned Mirage probe **before expensive LetFS work**. Its minimal test VFS truthfully stats `report.pdf` as FILE while natively supporting `report.pdf/nested/report.md` and `@<original-file-id>/nested/report.md`. Exercise session dispatch, the intended `read_file` wrapper, `stat`, explicit child listing/read, `cat`, `head` and relevant listing/tree commands. Capture actual paths/return values/errors and versions. This probe is a dependency capability check, not production implementation.

Supported public plumbing preserves full `PathSpec.vfs_path`/`mount_path`; `mount_key` and `_keyed_paths` supply mount-relative backend keys. `@vfs_call` custom methods run through policy/session dispatch and can forward the complete accepted locator. `resolve_path_stat` returns a real FILE stat without forcing it to DIRECTORY. This is a plausible minimal adapter route, not proof every command traversal accepts a file ancestor. The pinned dispatcher also has ENOTDIR rules for directory-dependent operations, especially creation/dot/trailing-slash behavior.

Keep source stat truthful, file reads as source metadata, children as ordinary native nodes and both accepted path forms. A failed named/source-ID child read or required real hierarchy call is a load-bearing compatibility failure: retain the exact reproducer and stop dependent implementation. Do not fix it by changing paths, pretending every blob is a directory, requiring child-ID lookup, forking Mirage, installing a later version or adding a projected artifact namespace. Phase 8 repeats the gate against real native LetFS, SpiceDB and Redis after the tiny probe passes.

## Invocation identity, mounts and lifetime

1. Fetch phase 4's generic accessible-scope native API with the verified server-selected root Leta subject. Workspace uses private paginated LetFS scope candidates/root metadata, current typed-subject BulkChecks and existing human labels; mount discovery loads no file tree and needs no BatchStat root hydration loop.
2. Create `Workspace(...)`, then `await workspace.session(session_id)` at invocation start. Stable `workspace_id` identifies the agent/cache scope; session ID includes agent/run/attempt so retries/concurrent invocations never share mutable cwd/env/session state. Close workspace/session execution in `finally` on success, cancellation and all failures.
3. Leta home uses `agents.home_scope_id`. Leti inherits `leta:L`, replaces only its home root with the persisted live `boxes.home_node_id`, and mounts no rest-of-Leta home. Shared/approved user scope rights remain the root Leta's current rights. No Leti authz subject, user account, login or workspace membership exists.
4. Immutable descriptors contain backend identity, filesystem/scope/root IDs, stable mount key, virtual prefix and effective mode. Native Locators always carry the descriptor root. Agent tools accept virtual paths only; neither model input nor public user headers select a native actor/root.
5. Share app-owned async native clients/pools; invocation VFS/accessors borrow and never close them. Workspace closes its owned caches/runtimes/session handles; app shutdown closes app pools. Do not use an app-global mutable workspace/mount list.

| Virtual prefix | Actual backend root | Mode |
| --- | --- | --- |
| `~` represented by absolute HOME `/home` | Leta ordinary home scope root, or Leti's box subtree | Current effective READ/WRITE |
| `/shared/` | Workspace shared scope root | Current effective READ/WRITE |
| `/users/<user-id>/` | Approved human personal scope root | Viewer READ or editor WRITE |

There are no additional artifact/preview mounts. `/shared/docs/report.pdf/nested/report.md` and `/shared/@<original-file-id>/nested/report.md` resolve through the same descriptor; equivalent paths work under home/user mounts. Native original-ID resolution retains root, liveness/generation and artifact readonly checks. Metadata returns the actual nested child tree and those usable paths; no source object URL/raw payload reaches the adapter.

Refresh scope descriptors at invocation start and safe graph boundaries after access outcomes or `get_workspace`. Complete/cancel all current tool/shell/Monty work before mount mutation. Diff descriptors using pinned `Workspace.add_mount`, `await workspace.unmount` and `set_mount_mode`; refresh any session mode cap too, or avoid a redundant cap. New invocations rebuild current rights. Revocation already blocks the next backend operation before a refresh; stale mount labels and cached bytes cannot keep access alive.

## Required Redis and permission/fingerprint checks

Use actual `RedisCacheConfig(url=..., key_prefix=..., limit=..., max_drain_bytes=...)` and `ReadSpec(policy=ReadPolicy.FRESH, ttl=...)`. Redis is required at startup/readiness and during normal operation. There is no optional Redis startup, cache-bypass mode, alternate local cache on outage or stale-byte fallback. Cache loss refetches through current native checks; Redis outage returns a clear dependency error. Phase 18 owns shared Redis memory/eviction settings; phase 16 owns the separate per-Leta event stream.

Declare facts only after implemented:

```python
caches_reads = True
read_revalidatable = True
reads_ranges = True
supports_snapshot = True
listing_version = ListingVersion.NONE
```

`supports_snapshot` means drift fingerprints, not historical data or replayable tool effects. Leave `local=False`; exact representation sizes permit `sizes_always_known=True` only when every regular-file stat can actually return one. `ListingVersion.NONE` avoids claiming directory revisions cover every content/processing change.

- Cache prefixes include deployment/workspace/root-Leta/agent identity and a stable digest of mounted scope/root/representation-version tuples. Different box roots/targets cannot inherit bytes at a reused virtual path. Do not include credentials or mirror ACLs in Redis.
- `FileStat.size`, `fingerprint` and read observations describe exact readable bytes. TEXT tokens bind ordinary node ID/revision/digest. Blob metadata tokens include its exact represented metadata/processing/current nested tree even when source revision did not change. Store native condition revision separately from drift digest; never parse a bare hash as a revision.
- Use actual `mirage.observe.context.start_op()` and `record(..., fingerprint=..., revision=...)`; any iterator returned inside the adapter follows the pinned `record_stream` contract. Normal read/search hooks return bytes/lists from unary native calls. Record tokens for empty reads and correct normal calls, not only when a recorder happens to be active. Do not mark selected/range bytes as a complete whole file.
- Implement `async Policy.pre_vfs(self, ctx: VfsContext) -> Action | tuple[Action, ...] | None`. Pinned `VfsContext` documents execution before backend/cache I/O. Resolve immutable descriptor via `ctx.prefix`; call the native service directly to check current typed-subject permission, bound root, liveness/provenance and current token at `ctx.path`, or validated parent on creation. Bypass the facade for this check to avoid policy recursion; each actual mutation rechecks inside its transaction.
- Content/excerpt/image/count/checksum/read-ahead checks require current `scope.read_content`, including cache hits. Metadata uses metadata permission. Do not memoize grants for an invocation or a whole shell command. For copy/move, independently check each source/destination descriptor; bulk hooks authorize each answered file.
- FRESH must compare current content tokens even for repeated same-command reads after an external update. If command-local reuse can bypass that comparison, compare the freshly authorized native token with public `workspace.cache.get_versioned(path.virtual)` and use public `workspace.cache.remove(path.virtual)` on mismatch before dispatch continues. Verify key identity and interactions in the pinned integration; do not fork private internals or accept bounded freshness instead.
- Normal Mirage write invalidation and native tokens handle local writes; verify that custom `edit_text` invalidates the same public cache path and ancestor listing state as built-in writes. If custom-call bookkeeping is insufficient, use supported public cache removal with the returned native token rather than private dispatcher changes. No invalidation bus, changefeed, custom cache table or Redis authorization lease is added. Backend failure/revoke always fails closed before cached content is released. Already delivered transcripts are not remotely erased.

## Pinned BaseVFS hook matrix

These are signatures from 0.0.8 `mirage/vfs/base.py`, not guessed local interfaces. Imports must come from the installed release. The base `read` supports awaitable bytes or an async iterator; the adapter may implement it as `async def read(..., offset: int=0, size: int | None=None) -> ByteSource` when `reads_ranges=True`. `readdir`/`read_tree` may add the documented `limit: int | None=None` parameter. Preserve inherited `@vfs_call` marks on overrides.

| Base signature | Native mapping and contract |
| --- | --- |
| `async stat(self, path: PathSpec) -> FileStat` | One native Stat resolves path, true kind, readable size and tokens; FILE source is not relabeled DIRECTORY. |
| `async readdir(self, path: PathSpec) -> list[FileStat] \| DirListing` | Locator-complete ListNodes, actual ordinary child hierarchy; consume pages up to requested bound. Limited/pattern-filtered output is `DirListing(..., partial=True)`. |
| `def read(self, path: PathSpec) -> Awaitable[ByteSource] \| AsyncIterator[bytes]` | Unary native ReadText range/whole selector, including blob metadata; no GetDownload. Return bytes under bounded small-file/metadata ceilings and stamp exact tokens. |
| `async read_tree(self, path: PathSpec) -> dict[str, FileStat] \| None` | Native actual ReadTree with relative keys/stat-equivalent values. Consume complete bounded result; return None on incompleteness so Mirage walks. Validate real file-owned hierarchy behavior in the mandatory gate. |
| `async first_lines(self, path: PathSpec, n: int) -> bytes \| None` | Native head selection; exact original lines/newlines. |
| `async last_lines(self, path: PathSpec, n: int) -> bytes \| None` | Native tail selection. |
| `async line_count(self, path: PathSpec) -> int \| None` | Native LF count, matching `wc -l`. |
| `async checksum(self, path: PathSpec, algorithm: str) -> str \| None` | Native exact permitted-representation digest; None on unsupported algorithm so Mirage hashes allowed read bytes. |
| `async follow(self, path: PathSpec, n: int, interval: float) -> AsyncIterator[bytes] \| None` | Native selected tail plus revision/range polling described below; current authz on every new operation. |
| `async files_containing(self, path: PathSpec, text: str, *, whole_word: bool, ignore_case: bool) -> list[PathSpec] \| None` | Phase-7 unary complete exact/superset file list; no regex/word parser. Return None on explicit incomplete result. |
| `async lines_containing(self, path: PathSpec, text: str, *, ignore_case: bool) -> ByteSource \| None` | Original complete candidate-line bytes from unary TextSearch; None on incomplete/unsupported safe extraction. No chunk assembly. |
| `async write(self, path: PathSpec, data: ByteSource) -> FileStat \| None` | Collect at most inline limit plus one byte, close input once, call unary guarded WriteText. Oversize never reaches an upload path. |
| `async append(self, path: PathSpec, data: ByteSource) -> FileStat \| None` | Bounded input then unary AppendText; no whole-file Python read/merge/write. |
| `async pwrite(self, path: PathSpec, data: bytes, offset: int) -> FileStat \| None` | Native positional PatchText; no gaps/invalid UTF-8 result. |
| `async truncate(self, path: PathSpec, length: int, no_create: bool=False) -> FileStat \| None` | Native truncate; atomic no_create, shrink only or equal length, zero-length creation under absence guard. |
| `async _replace(self, request: ReplaceRequest) -> FileStat \| None` | Bounded body consumed once; ABSENT/MATCH to atomic native guards. ANY observes then guards. |
| `condition_support(self) -> ConditionSupport` property | Only `{'put': frozenset({'absent','match'})}` until additional native condition kinds truly exist. |
| `async create(self, path: PathSpec) -> FileStat \| None` | Native create-empty-if-absent; preserve existing content. |
| `async mkdir(self, path: PathSpec, parents: bool=False) -> FileStat \| None` | Native guarded directory creation with actual missing-parent behavior. |
| `async copy(self, src: PathSpec, dst: PathSpec) -> FileStat \| None` | Existing native direct copy/request key; source and destination roots, no-overwrite. |
| `async copy_from(self, source: BaseVFS, src: PathSpec, dst: PathSpec) -> None` | Same trusted LetFS/backend/filesystem direct copy across mounts with both roots. If a blob cannot be copied natively, refuse with a real error instead of EXDEV fallback that would turn metadata JSON into payload. |
| `async dir_copy(self, src: PathSpec, dst: PathSpec) -> FileStat \| None` | Native bounded directory copy, retain partial output on failure. |
| `async rename(self, src: PathSpec, dst: PathSpec) -> FileStat \| None` | Native current move guards; preserve no-overwrite. Cross-mount flow stays library-owned copy/trash behavior. |
| `async unlink(self, path: PathSpec) -> None` | File-type check then native trash. |
| `async rmdir(self, path: PathSpec) -> None` | Native atomic empty-directory trash. |
| `async rm_r(self, path: PathSpec) -> Any` | Native one-subtree trash, no purge. |
| `async search(self, path: PathSpec, query: SearchQuery) -> list[tuple[str,str]] \| None` | Existing authorized SemanticSearch, current generation and root restriction; actual readable paths, independent from literal candidates. |
| `async search_many(self, paths: list[PathSpec], query: SearchQuery) -> list[tuple[str,str]] \| None` | Scope-grouped semantic calls, bounded parallelism, merged rank/limit and readable-path dedup under current roots. |
| `async read_many(self, paths: list[PathSpec], limit: int) -> dict[str,bytes]` | Bounded parallel native whole reads; per-file limit and aggregate output bound, record each answered token. Omitted oversized entries are read later under the normal contract. |
| `async before_full_walk(self, path: PathSpec, *, files: int \| None=None) -> None` | Honor actual native walk/copy bounds and current read/write authority for broad work; no bespoke command parsing. Do not refuse searches/listings where Mirage's documented contract only clips its walk. |

Other base surfaces remain deliberate: `exists(path)` derives from stat; `is_mounted()` reflects actual backend availability; `storage_location()` may report a nonsecret backend/filesystem/scope/root identity so identical targets are recognized without conflating different roots. `capacity()` returns real authorized filesystem quota only when available, otherwise UNKNOWN. Keep `delta_hook=None`; no feed exists. Remote VFS `get_state`/`load_state` retain the default live-override requirement with no secret/content serialization. `close()` releases only invocation-owned handles exactly once. Host ownership/mode/symlink/device metadata and `setattr` remain unsupported rather than fabricated overlays presented as durable LetFS facts.

For `follow` (`tail -f`), return an invocation-local async iterator that polls the existing unary Stat/ReadText range APIs at the supplied `interval`. Read initial tail/full size/token in one snapshot; buffer incomplete final line and yield complete newline-terminated lines. Read only new bytes after the consumed offset, with current authorization and the matching observed fingerprint. Retry raced stat/range within the tool deadline; never concatenate mismatched versions. On shrink reset offset according to pinned tail behavior; replacement/delete/revoke raises an ordinary native error. Command timeout/cancellation closes iterator/poller. Do not add a follow RPC stream, database changefeed, backend subscription or background watcher. Edits appearing/disappearing between polls are not reconstructible.

Mirage's `ByteSource = bytes | AsyncIterator[bytes]` is a library interface, not a native transport requirement. Adapter write/append/replacement may consume an incoming iterator once under the inline limit and send one unary body. Keep applicable hooks; no backend streaming is needed for text read/write/search or follow. Existing ZIP/blob-transfer streaming and the accepted AI/event Redis–SSE path retain their separate contracts; this plan does not remove existing StreamArchive native API.

## Direct tool wrappers and custom dispatch

Use [tool contracts](tool-contracts.md), retaining existing catalog names. The following are custom adapter methods, not Mirage built-ins or extra LLM tools:

```python
@vfs_call(effect=Effect.READ, target=Target.FILE)
async def read_image(self, path: PathSpec) -> ImageRead: ...

@vfs_call(effect=Effect.READ, target=Target.FILE)
async def read_text_lines(self, path: PathSpec, start_line: int,
                          max_lines: int) -> TextRead: ...

@vfs_call(effect=Effect.WRITE, target=Target.FILE)
async def edit_text(self, path: PathSpec, old_text: str, new_text: str,
                    replace_all: bool=False) -> FileStat: ...
```

`ImageRead`/`TextRead` wrap generated native results. Every call goes through the session dispatcher so mount modes, current policy and readonly checks run. `read_image` resolves the same original source image path or actual image-child path; no separate preview hierarchy is required.

| Tool | Mapping |
| --- | --- |
| `list_files(path,depth,limit,cursor)` | Session VFS/native listing and actual tree, explicit bounds/cursor/incomplete state; no body scan. |
| `read_file(path,start_line,max_lines)` | Truthful session stat followed by custom selected text or ordinary blob metadata/tree read. Supported image source/child calls `session.vfs.dispatch('read_image', path)` and emits MIME/base64 multimodal output plus provenance. Image line options fail clearly rather than reinterpret a preview as text. |
| `write_file(path,content,overwrite=False)` | Conditional put, absent by default; overwrite observes then submits current guarded TEXT token. |
| `edit_file(path,old_text,new_text,replace_all=False)` | Custom edit_text → native exact PatchText. No whole-file Python replacement loop. |
| `run_shell(command,cwd='~',timeout_seconds=30)` | Actual `session.shell(command, cwd=..., cancel=event, ...)` under deadline, bounded output and honest IOResult/stream status. Mirage parses and executes its own commands. |
| `run_python(code,timeout_seconds=30)` | `session.shell('python -', stdin=code_bytes, runtime='monty', ...)`; no shell interpolation/host Python route. Same mounts/deadline/cancellation/output bounds. |
| `semantic_search(query,paths?,limit)` | Session search/search_many with current readable roots; retain current semantic disabled/degraded errors, never substitute literal search. |

Images use phase 5's backend limit: PNG/JPEG/GIF first frame, max 40M input pixels, 2048 long edge, 4 MiB output, two preview slots. Unsupported format/decode/limit/saturation errors are explicit. Shell/Monty read only metadata, never original binary bytes or signed URLs.

## Shell/Monty isolation and replay

- Mirage owns commands, grep/regex/glob/find options and fallbacks. No backend command-specific API, replacement command parser or fork is introduced. Test actual pinned behavior with independent expected output.
- `rm` means current native trash, including recursive/force cases; no quota release/purge. Keep no-overwrite and partial-copy contracts, and explicit pwrite gap/truncate-growth/UTF-8-cut errors.
- Construct Workspace with `network=False`, explicit Monty runtime and no local/WASI/host runtime fallback, host filesystem mount or ambient external function binding. Backend client connectivity must remain the app-owned explicit native channel; verify denial of guest ambient network without breaking that channel.
- Monty is a Python subset: no third-party imports, class inheritance, method decorators, yield or host `sys.stdin`/`sys.argv`/module `-m` execution. Use injected guest argv/stdin/workspace env and the shared RuntimeFiles/MontyFs boundary, never worker process environment.
- Use actual `MontyConfig(max_memory=...)`; no invented CPU-limit field. Wrapper deadline/cancellation and bounded stdout/stderr must terminate invocation-owned execution and close RuntimeFiles. Monty callbacks may read whole small files; ranged shell hooks do not make every guest read ranged.
- An unfinished shell/Monty call may replay after crash and the agent inspects/corrects duplicate/partial effects. Phase 10 reuses saved tool results. Do not add start markers, outcome suppression, execution ledgers or permanent receipts; an SSE/Redis publication failure never authorizes replaying applied effects.

## Files and implementation steps

All paths are relative to `/home/qninh/projects/openlet`; existing Python snake_case module conventions apply.

| Action | Files | Responsibility |
| --- | --- | --- |
| Add | `apps/leta/src/leta/filesystem/workspace.py` | Invocation factory/cleanup, immutable scope/root descriptors, safe refresh and cache namespaces. |
| Add | `apps/leta/src/leta/filesystem/letfs_vfs.py` | One native LetFS adapter: actual hierarchy, read/search/write/node hooks, tokens and custom image/line/edit calls. No ArtifactVFS/projection module. |
| Add | `apps/leta/src/leta/filesystem/access_policy.py` | Current native authorization/token checks before cache access using actual Policy.pre_vfs. |
| Add | `apps/leta/src/leta/filesystem/tools.py` | Catalog wrappers, bounded body/output handling, multimodal image output and shell/Monty cancellation/errors. |
| Add | `apps/leta/tests/test_filesystem_workspace.py`, `test_letfs_vfs.py`, `test_filesystem_tools.py` | Real Mirage object mapping/lifetime/contract tests. Phase 1 owns the earlier tiny compatibility probe. |
| Add | `apps/leta/tests/integration/test_mirage_letfs.py`, `test_mirage_cache_permissions.py` | Actual native Go service/PostgreSQL/SpiceDB/Redis plus pinned Mirage/Monty; no fake replacement for the integration subject. |
| Modify | `apps/leta/src/leta/config.py`, phase-1/10 worker assembly | Borrowed clients, required Redis readiness and existing tunable runtime/memory/time/output/cache defaults. |
| Modify only if missing | `apps/leta/pyproject.toml`, root `uv.lock` | Keep phase-1 exact Mirage/Monty pins; do not upgrade during planning or select main docs. |
| Modify | `docs/architecture.md`, `docs/api-contracts.md`, `docs/operations.md` | Real mounts/artifacts/native boundary, cache permission checks, accepted operation/runtime/replay limits. |

1. [x] Verify exact installed versions/imported signatures and phase 1 compatibility output. Fail dependency drift; preserve FILE sources and accepted named/source-ID artifact paths.
2. [x] Build invocation factory, generic scope-view consumption and Leti box-root validation. Test no bot membership/creator impersonation and no global session mutation.
3. [x] Implement truthful stat/list/tree/read plus custom line/image calls through public session dispatch; repeat the early artifact path probe against real native services.
4. [x] Implement every applicable hook in the matrix, conditional writes, bounded ByteSource collection, polling follow over unary range reads, read_many, native cross-mount copy and semantic mapping. Cover honest unsupported limits; do not add text-search/follow streaming RPCs.
5. [x] Wire required Redis FRESH observations and pre_vfs current permission/token checks. Test external writes/processing changes and same-command cache reuse using the public cache removal route if necessary.
6. [x] Refresh mounts/modes only after active tools finish/cancel; test grant/revoke before refresh and safe get_workspace boundaries.
7. [x] Expose the seven tools through one session; verify actual shell flags, Monty subset/isolation, timeout/output/memory errors and resource cleanup.
8. [x] Generate VFS.md guidance from actual capabilities/paths/limits and attach it to the model without credentials/native actor selection. Run focused/native integration checks and review cross-module authz/cache/storage behavior.

## Validation and acceptance

| Journey | Required result |
| --- | --- |
| Root Leta / Leti / foreign personal grant | Correct home/shared/user roots only; creator personal scope never appears without a real grant; Leti inherits root subject with only its box home. |
| Truthful source and nested artifact paths | FILE source metadata plus successful named/source-ID nested child reads/listing through read_file/session and actual shell; no child-ID requirement or projected workaround. |
| Direct backend escapes | Paths, IDs, cwd, `..`, aliases and both copy ends fail outside the bound root even without client policy. |
| Hook coverage | Each applicable matrix hook is reached through actual Mirage/session/native calls; RPC spies can count but cannot replace native storage. |
| Selected reads/edits | Backend range/head/tail/metrics/tree/exact-edit methods run; no GetDownload/full-worker-merge substitute. |
| Unary search and polling follow | Search hooks return lists/bytes or None on explicit incomplete result. tail -f calls bounded unary range reads at the requested interval and releases its iterator on timeout/cancel; new reads enforce current rights. No backend stream/subscription is opened. |
| Regex/flags | Real literal/alternative/multiple-pattern/Unicode/position/context/inverse/glob/find results match independent fixtures and library fallback stays correct. |
| Warm cache then revoke/change | Current permission denies the next read/image/search before bytes; external writes/processing-only updates change FRESH tokens, including repeated same-command reads. |
| Redis unavailable | Startup/readiness fails; runtime dependency errors are explicit with no local/bypass/stale mode and no tool-effect replay. |
| Grant/revoke during active command | Existing mount structure stays stable; next backend operation checks rights; safe boundary refresh changes modes. |
| Images | Same source path returns bounded supported multimodal preview; ordinary reads stay metadata; no original raw blob or signed URL. |
| Concurrent write/copy/trash | Guards reject stale overwrite; accepted no-overwrite/partial-copy/trash behavior remains truthful. |
| Monty failure/cancel/crash | Same mounts, no host files/env/network/import escape, bounded resources and cleanup; unfinished tools may replay while saved results are reused. |

Future commands after phase 1 creates the package/fixtures; new test names are deliverables:

```sh
uv run --locked --package leta pytest apps/leta/tests/test_filesystem_workspace.py apps/leta/tests/test_letfs_vfs.py apps/leta/tests/test_filesystem_tools.py -q
uv run --locked --package leta pytest apps/leta/tests/integration/test_mirage_letfs.py apps/leta/tests/integration/test_mirage_cache_permissions.py -q
uv run --locked --package leta ruff check apps/leta
uv run --locked --package leta ruff format --check apps/leta
pnpm contracts:check
go -C apps/letfs test -race -tags integration ./internal/filesystem ./internal/transport/grpc -count=1
```

Fixtures use owned disposable dependencies/deterministic ports or private listeners, track PIDs/ports/worktrees and stop what they start. Missing Docker/Monty/Redis or failed source-parent compatibility is an unmet prerequisite, not a skipped PASS.

- [x] All hook/runtime/cache/permission tests pass with actual pinned Mirage and native LetFS; source inspection is labeled separately.
- [x] No independent artifact namespace, raw blob access, optional Redis path or backend command parser exists.
- [x] Current permissions/root/fingerprints precede cache reuse; concurrent/failed effects follow accepted ordinary recovery.
- [x] Scope discovery and safe refresh serve the accepted human-user/Leta-resource model.

## Risks and rollback

Load-bearing risks are truthful file-parent traversal through pinned Mirage, cache reuse within a command, and guest-network denial versus explicit native client traffic. Resolve them by the mandatory probes/tests; do not assert compatibility from signatures. Report a concrete unsupported path before changing accepted design or dependency versions.

The user confirmed no production data and no backup prerequisite. Use owned fresh fixtures; never reset unrelated persistent environments. Disable agent tool/mount admission and drain invocations to roll back the adapter, then remove only its disposable cache prefixes. Keep required Redis for the service, LetFS data/trash/TEXT, durable engine/history and accepted paths. Never delete user data to repair cache drift.
