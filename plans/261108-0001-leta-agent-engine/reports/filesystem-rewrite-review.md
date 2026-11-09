# Filesystem rewrite review

Status: DONE_WITH_CONCERNS. Phases 5–8 are rewritten for the accepted user/Leta-resource design. The concerns below are mandatory future implementation probes, not evidence that production behavior already passes or a request to change the accepted design.

## Authority and scope

Read the complete [accepted direction](../../reports/design-261108-0148-leta-workspace-resource.md), repository `AGENTS.md`, shared development rules and all old filesystem phases 4–7 before drafting. Applied the installed `ak-plan` skill. Historical review reports were treated as evidence only; superseded architecture was not retained as execution guidance.

Owned outputs are [phase 5](../phase-05-letfs-inline-text-and-reads.md), [phase 6](../phase-06-letfs-text-mutations.md), [phase 7](../phase-07-letfs-native-text-search.md), [phase 8](../phase-08-mirage-workspace-adapter.md) and this review. No old phase was deleted; controller owns old-file retirement and the whole-plan index/contracts. No application source, schema, dependencies, database, provider or deployment was changed.

## Source-backed checks

CodeGraph was consulted before indexed implementation lookup. Relevant current owners include `paths.go::session.resolve`, `nodes.go::ListNodes`, `node_writes.go::CreateNode/ReplaceContent`, `copy_data.go::session.inScope`, the inline configuration and the existing Download/Inventory consumers. Pinned external Mirage source was read directly from `/tmp/leta-filesystem-review/src`, including BaseVFS, PathSpec, cache/write types, policy context, workspace/session constructors, dispatch/key mapping and Monty config. Repository manifests and operations recovery documentation supplied future validation commands and backup route.

| Accepted invariant | Rewritten execution contract |
| --- | --- |
| Human users; Leta as resource | Closed verified user/leta native subject, trusted service selection and inherited Leti authority. No bot account/member or creator impersonation. |
| Generic accessible scopes | Phase 4 supplies scope/root metadata for users and Leta via private paginated LetFS candidates plus current permission filtering; no tree load or agent-only discovery route. |
| Existing small/large boundary | Small supported TEXT only, default 256 KiB/current supported max 1 MiB; eligible inline-only conversion. Object-backed text keeps existing transfers/processing and agent metadata/tree access. |
| Existing consumers | Bounded TEXT encodes into existing inline Download/Inventory variants; object paths stay unchanged. No ReadProcessingText, large-content refs, mutation streams or special text buffers. |
| Artifact paths | Actual ordinary nested child nodes, FILE source stat and named/source-ID-prefixed relative paths within the same home/shared/user mount. No projected/sibling mounts or separate artifact ID entity. |
| Image reads | Source-path custom read_image, backend-only on-demand bounded PNG/JPEG/GIF-first-frame preview, 40M input pixels/2048 edge/4 MiB/two slots. No synthetic preview hierarchy/raw original URL. |
| Native data and Mirage ownership | LetFS generic stat/tree/selected reads/metrics/mutations/literal candidates; adapter implements pinned hooks; Mirage owns commands, regex and flags. |
| Text limits | Ordinary edits/appends work; zero-filled gaps/growth and invalid UTF-8 cuts fail explicitly. Native final size cannot silently switch to object storage. |
| Existing mutation recovery | Existing keys/identity/revision guards, trash, no-overwrite and retained partial copy. Unfinished shell/Monty may replay; no execution ledger/permanent receipt/start-marker suppression. |
| Cache and Redis | Required startup/readiness Redis, current pre_vfs permission/root/liveness/token before cached bytes, FRESH observations and safe boundary mount refresh. No bypass/degraded mode. |
| GIN evidence | Small TEXT/artifact TEXT only; real production Store scope/root query/default planner and equality/space/write cost gate. Common/short/small-root scans remain valid. |

## Load-bearing future gates

1. **Truthful FILE parent through Mirage.** Native LetFS resolves children below a source file. Public PathSpec/key mapping/custom vfs_call can preserve the full accepted path, and resolve_path_stat does not coerce a real FILE into DIRECTORY. Pinned dispatcher directory/dot/trailing-slash checks still include ENOTDIR semantics; that source does not prove all required calls work. Phase 1 must first execute a tiny pinned Mirage VFS probe for named and `/@<original-file-id>/nested/child` paths through session/read_file/actual shell, keeping source stat FILE. Phase 8 repeats against actual LetFS. A concrete failure blocks dependent work and must be reported with the exact call/error; no namespace workaround, false directory kind, mandatory child-ID lookup or fork is authorized.
2. **Same-command cache reuse/custom mutations.** Pinned pre_vfs is documented before cache/backend I/O; native checks must validate current permission/token on every new operation. Phase 8 tests external updates, processing-only changes, revocation, custom edit invalidation and repeated reads inside a command, using public cache get_versioned/remove APIs if needed. No source-only claim of cache correctness is made.
3. **Actual selective-query GIN benefit.** The historical benchmark did not satisfy default-planner improvement. Phase 7 requires actual current schema/Store scope/root SQL, independent output equality, default plans, paired timings and write/index cost. Failure leaves the gate open rather than accepting a forced-index number.
4. **Explicit native connectivity under guest-network denial.** Phase 8 must prove Monty/shell ambient network is denied while borrowed app-native clients still work and close only their owned resources. No host/network fallback is planned.

These are implementation experiments with fixed accepted outcomes, not unresolved product choices. Source inspection and planned assertions are explicitly separated from executed runtime proof.

## Plan-only validation performed

- Read all four new phase files and checked their storage/authz/path/cache/replay boundaries against the accepted design.
- Checked frontmatter: all `pending`; numeric dependencies are 5→2, 6→5, 7→5/6, 8→4/5/6/7; all checklists unchecked and every phase below 800 lines.
- Checked relative Markdown links in owned phase files; all resolved at review time. Phase 4 is referenced by number so its controller-selected filename does not create a broken link.
- Reviewed every applicable BaseVFS hook against pinned source, including tree/range/head/tail/count/checksum/follow/read_many/search/mutations/copy and before_full_walk; lifecycle/unsupported host metadata surfaces are deliberate.
- Verified future commands against root/LetFS/Python manifests. New test names/packages are explicitly future deliverables; no test or benchmark was executed.
- Ran `git diff --check`; no whitespace errors were reported. The plan directory was already untracked, so that command alone does not validate new file contents; direct text/link/frontmatter checks covered the owned outputs.
- Checked whether any owned target existed before initial writes so it could be backed up; all five targets were absent. Existing files/other-agent changes were preserved and no long-running process was started.

No production backup/migration, native integration, dependency installation or runtime test was performed. Required future probes and selective GIN performance remain risks until executed. Unresolved product questions: none.

## Controller integration completion

The current 19-phase index and all replacement phase files now exist. Relative links/dependencies passed the final document sweep. Cross-plan follow-up corrections are recorded in [current plan review](plan-review.md); earlier missing-link/ownership notes above describe the parallel rewrite stage. Required runtime experiments remain pending; none were executed by document review.
