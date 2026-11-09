# Filesystem plan review and source evidence

> Historical review of the superseded draft. All items 1–42 have since been reviewed; accepted corrections are incorporated in the [current 19-phase plan](../plan.md) and [design contract](../design-contract.md). Old phase numbers, line references and recommendations below describe that earlier draft and must not be implemented as current requirements. Navigation links now point to replacement owning phases.


Reviewed 2026-11-08 against the current English design/tool contracts, phases 04–07 and their phase 03/08/10 integration points. Scope was read-only production/source review; this report is the only repository file owned by this reviewer.

**Disposition:** no remaining concrete blocking finding in the reviewed filesystem plan after the large-TEXT delivery correction below. This is approval of an executable plan, not evidence that the proposed APIs, migrations, authorization or performance already work.

## Findings and resolution

### P1 — Large canonical TEXT needs streaming delivery to existing download and ingest consumers — resolved in plan

- Original scenario: a textual object larger than 8 MiB previously reached download/processing callers through a signed URL. Converting it to canonical TEXT and merely UTF-8 encoding it into the existing inline fields would make its unary reply exceed the transport limit. New native text writes can reach the same failure independently of migration.
- Plan boundary: `phase-04-letfs-text-storage-and-read-api.md:39` permits native TEXT up to MaxFileBytes without an object fallback; `phase-04-letfs-text-storage-and-read-api.md:42` preserves all existing byte consumers. Streaming only the new Mirage reads would not repair those consumers.
- Implementation evidence: `packages/go/rpc/transport.go:21` fixes MaxMessageBytes at 8 MiB, enforced on both server directions at line 103. `apps/letfs/internal/transport/grpc/download.go:22` constructs a unary Download containing either a signed URL or all inline content. `apps/letfs/internal/transport/grpc/ingest.go:236` embeds content into InventoryNode, and lines 256–269 return that inventory in a unary PrepareEnrichment response; PrepareIndex uses the same inventory converter at line 46. `apps/letfs-ingest/src/letfs_ingest/processing/processor.py:56` reads only inline bytes or signed URLs; its enrichment loop at line 89 and index eligibility predicate at line 134 also require updating when a text reference is added.
- Smallest complete correction, now recorded at `phase-04-letfs-text-storage-and-read-api.md:44`: add an identity/revision/fingerprint-bound text reference to Download and consume ReadText through shared clients; stream the existing owner HTTP download; add generation-bound inventory references plus narrowly authorized IngestService.ReadProcessingText; update actual processor eligibility/read logic. Keep TEXT as sole authority and retain the shared 8 MiB ceiling.
- Regression gate now required at `phase-04-letfs-text-storage-and-read-api.md:52`: new and migrated TEXT above 8 MiB through owner HTTP, native clients, archive and both actual processing paths, with byte equality, bounded frames and stale-generation refusal. Compatible schema/reader rollout remains fenced; this additive response variant does not establish old-binary compatibility.

### P2 — Phase dependency metadata and scaffolding disagreed with the index — resolved by controller

The initial phase 04 frontmatter required phase 03 while the index listed only phase 01; phases 04–07 used `todo`/`depends_on` string IDs instead of the surrounding numeric `pending`/`dependencies` convention and retained template Requirement A/Task A tails. The controller normalized metadata against the index and removed the tails. Static assertions passed for all four current files. No production concern follows from the removed scaffolding.

## Filesystem evidence

### Provenance

The previously referenced `/tmp/leta-research` did not exist in this session. Retrieved the exact published Mirage and Monty wheels without installing or altering project dependencies, then extracted them into `/tmp/leta-filesystem-review/src` for source inspection:

| Distribution | SHA-256 |
| --- | --- |
| `mirage_ai-0.0.8-cp312-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl` | `c43677f6003dde5a0d944acfb80470c792111ce3312b621acc09ca4cb2caa9ce` |
| `pydantic_monty-1.4.0-py3-none-any.whl` | `e398217fdb701e4daaeeb9fd65ad9319627cb114334bc00d6cf2444845c43bca` |

The temporary extraction is reproducible evidence, not a repository runtime dependency. Upstream source references below use that extraction root. Current LetFS source was obtained through CodeGraph before bounded follow-up reads. No indexing, database change, deployment, commit or additional agent was started.

### Native storage, roots and public byte compatibility

| Verified source | Plan implication |
| --- | --- |
| `apps/letfs/migrations/0001_initial.sql:16`, payload constraints at lines 32–33 | Current served payloads are inline bytea or object keys. TEXT is a real additive redesign; preserve arbitrary binary rows rather than decoding everything as text. |
| `apps/letfs/internal/filesystem/node_writes.go:63` | Existing text-only scopes validate UTF-8 and permit only tab/CR/LF controls. Phase 04 preserves that rule and additionally rejects NUL for canonical TEXT. |
| `apps/letfs/internal/filesystem/paths.go:84` | Existing recursive resolver owns path/cwd/direct ID/alias liveness and artifact provenance. The proposed optional root belongs here; client path checks alone would leave raw-ID escapes. |
| `apps/letfs/internal/filesystem/copy_data.go:338` | inScope replaces scope/root on a copied session. Phase 04 explicitly preserves independent source/destination restrictions rather than assuming a source bound survives this helper. |
| `apps/letfs/internal/filesystem/nodes.go:197` | BatchStat already supports 1–100 scoped Locators and validates scope/authorization, providing the phase 03/07 root hydration route without a new GetScopes API. |
| `apps/letfs/internal/filesystem/node_writes.go:173`, creation ID at line 225 | Creation receipt currently expires after 24 hours and the server chooses IDs. Phase 05 adds optional caller IDs; phase 08 persists boxes.home_node_id before provisioning, avoiding same-path adoption after receipt expiry. |
| `apps/letfs/internal/filesystem/trash.go:99` | TrashNode guards revision/readonly/root, inserts a trash entry and detaches the node. Phase 05/07 rm mappings retain this behavior and quota; no purge route is introduced. |

Byte ranges remain byte ranges, including partial UTF-8 sequences; line selectors retain CR/LF and a final fragment; newline metrics count LF, not logical lines. Phase 05 explicitly rejects zero-filled pwrite gaps/truncate growth because PostgreSQL TEXT cannot store NUL. These are deliberate stated limits, with concrete counterexamples in phase tests, rather than silent space padding or binary conversion.

### Mirage 0.0.8 hook availability and signatures

All paths in this table are relative to `/tmp/leta-filesystem-review/src`.

| Source | Verified contract |
| --- | --- |
| `mirage/vfs/base.py:289`, `:305`, `:449` | readdir may additionally take limit and return partial DirListing; ranged read uses offset/size only when reads_ranges is true; read_tree must be complete or decline with None. |
| `mirage/vfs/base.py:343`, `:362`, `:380`, `:394`, `:420` | Native head/tail/count/checksum/follow hooks exist. Checksums describe the exact readable bytes; follow yields complete lines in order and owns cancellation. |
| `mirage/vfs/base.py:478`, `:482`, `:500`, `:516`, `:646` | Conditional replace, write, append, pwrite and truncate signatures match the plan. Default pwrite/truncate describe zero filling, so the TEXT limitation must remain an explicit error. |
| `mirage/vfs/base.py:615` | copy_from is judged at both dispatch boundaries before invocation. EXDEV explicitly requests a read/write fallback; using it for unsupported blob transfer would risk copying metadata JSON as the original payload. The plan correctly requires a real refusal. |
| `mirage/vfs/base.py:687`, `:708`, `:721` | search/search_many/read_many exist with the listed result types. read_many keys are virtual paths and oversized per-file reads may be omitted. |
| `mirage/vfs/base.py:741`, `:780` | files_containing and lines_containing are complete-or-superset exclusion hooks. Extra candidates are safe; omitted matches are wrong. lines_containing preserves original line bytes and declines for representations that may contain NUL. |
| `mirage/workspace/workspace/workspace.py:3432` | Session.shell accepts stdin, cwd, cancel, runtime and stream. Passing source as stdin to `python -` with runtime=monty is a real API path. |
| `mirage/runtime/python/monty/config.py:21` | MontyConfig exposes max_memory; no invented CPU-limit field is needed. |
| `mirage/runtime/python/monty/execution.py:267` | Cancellation explicitly kills the checked-out worker PID before unwinding, addressing the upstream note that cancelling feed_run alone does not stop CPU execution. Application deadlines and cleanup tests remain necessary. |

An AST self-check verified the positional signatures of pwrite, truncate, follow, copy_from, read_many, files_containing, lines_containing, search_many and _replace, plus candidate-hook keyword-only arguments. This did not import native wheels or execute Monty.

### Authorization before cache, freshness and replay

`mirage/policy/base.py:106` and `mirage/policy/types.py:899` establish Policy.pre_vfs/VfsContext and explicitly place the hook before backend **and cache** I/O, including runtime and command calls. The phase 07 direct native access check therefore has an actual interception point; it must bypass Mirage dispatch to avoid recursion and must fail closed on revoke/dependency failure.

`mirage/cache/file/config.py:28` and line 42 verify RedisCacheConfig's limit/max_drain_bytes/url/key_prefix fields. `mirage/cache/file/mixin.py:59` provides public path/subtree removal. `mirage/observe/context.py:327`, line 400 and line 440 provide start_op, record and record_stream with fingerprint/revision metadata. Those signatures support the plan's token recording without patching internals.

Freshness still requires the explicit implementation gate at `phase-07-mirage-workspace-adapter.md:73`: `mirage/cache/manager.py:427` deliberately reuses a probe stat within one command until a cache drop; `:250` also documents command-local listing trust. A native permission check cannot by itself refresh a stale content token. Preserve the planned same-command external-writer test and compare the directly observed backend token before a cached read; use public cache removal on mismatch. Source inspection establishes this requirement, not a successful cache-coherence result.

Phase 08 activity_log start/result entries and phase 10 recovery use the same persisted tool-call identity. Started shell/Monty calls without a result become outcome_unknown; native mutations reconcile known IDs/revisions. This matches the accepted restriction against opaque command replay and requires no new receipt/lease/fencing entity.

### Exact search and production-query performance

The accepted GIN index is a partial index over canonical TEXT, with the storage_kind predicate repeated in the production query. Phase 06 also requires live authorized scope/root joins and a metadata-representation branch, so binary metadata matches are not lost simply because they lack TEXT payloads. Whole-word overinclusion, Unicode-fold-sensitive conservative candidates, multiline fallback and completion/error handling agree with Mirage's exclusion-hook contract.

The query benchmark remains an implementation gate, not an achieved improvement. Historical evidence is `plans/reports/benchmark-261107-1919-letfs-trigram.py` and `plans/reports/benchmark-261107-leta-trigram-results.json`; phase 06 accurately distinguishes the reported default Seq Scan timings from forced-index diagnostics. Its required test uses actual production Store SQL, scope/root predicates, equality checks, EXPLAIN JSON, index/TOAST sizes and paired samples. A selective default-plan failure keeps the phase open; broad/short-term scans remain valid. No performance result or fabricated quota is added by this review.

### Images and projection

`apps/letfs/internal/filesystem/artifacts.go:13` identifies original images with parse=false at lines 23–24; existing image publication does not imply an original preview artifact exists. Current phase 04 correctly specifies on-demand backend DecodeConfig/decode/resample/re-encode through ReadArtifactImage and an actual synthetic descriptor, without requiring a new persistent ingest stage.

Normal binary/image shell reads remain metadata. The sibling `/artifacts/home`, `/artifacts/shared` and `/artifacts/users/<account-id>` mounts avoid physical `.artifacts` collisions and retain matching backend roots. The reserved `_previews` child is in a synthetic namespace whose other children are source UUIDs. Preview limits are explicit, including supported PNG/JPEG/GIF first-frame behavior, unsupported WebP, dimension/output limits and bounded decode admission. No original signed URL or source bytes are returned to the agent image tool.

## Verification boundary

Performed: current-plan read/review, CodeGraph source tracing, pinned-wheel source inspection/hashes, hook-signature AST assertions and phase metadata/scaffold assertions. The only substantive source compatibility finding was corrected in the plan during review.

Not run: proposed LetFS/Mirage integration, Monty execution, migrations/backup/restore, live authorization/revocation, or production-query benchmarks. Their phase acceptance gates remain mandatory; no production code or data changed.

Status: DONE
Summary: Reviewed filesystem phases against current LetFS and pinned Mirage source; large-TEXT unary delivery gap is resolved in the plan and all cited implementation experiments remain explicit.
Concerns/Blockers: No remaining concrete plan blocker in this review scope; runtime and performance claims await implementation evidence.
