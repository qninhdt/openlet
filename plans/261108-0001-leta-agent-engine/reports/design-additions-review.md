# Design additions relative to the brainstorm

> Historical review of the superseded draft. All items 1–42 have since been reviewed; accepted corrections are incorporated in the [current 19-phase plan](../plan.md) and [design contract](../design-contract.md). Old phase numbers, line references and recommendations below describe that earlier draft and must not be implemented as current requirements. Navigation links now point to replacement owning phases.


New user direction: [workspace-resource redesign](../../reports/design-261108-0148-leta-workspace-resource.md) supersedes account-dependent recommendations. Large text remains S3/blob; generic accessible-scope discovery serves users and Leta. This inventory remains a historical review list, not authority to restore managed agent accounts or large-text streaming.

Status: historical inventory; user review completed through item42. Planning only; no implementation is authorized by this report.

Review progress: items 1–34 are settled subject to their recorded corrections and the accepted workspace-resource redesign. Item 27 preserves source-file child artifacts addressed by source path or /@<original-file-id>/relative-artifact, without a separate artifact-ID concept/namespace. Item 30 uses only native data APIs and Mirage hooks. [Current decisions](../../reports/design-261108-0148-leta-workspace-resource.md) take precedence over the historical inventory below. Items 35–42 are now accepted with corrections recorded in the current decision checkpoint; no implementation has started.

This is a comparison, not another accepted architecture contract. The baseline is the current-decision portions of [the engine checkpoint](../../reports/brainstorm-261107-2159-leta-engine-design.md) and [the evidence/tool checkpoint](../../reports/brainstorm-261107-1653-leta-evidence.md), together with the user's subsequent instructions. Historical rejected proposals in those files are not baseline. A source-backed implementation choice is still an assistant choice unless the user accepted it. Earlier review statements about having no technical blocker did not constitute user approval of every added policy.

The inventory covers consequential behavior, data/transport contracts and operational defaults added or made explicit in the 18 phases. Proposed filenames, ordinary helper names and test organization are not separate product decisions. Recommendations below are proposals only; this report does not silently amend their owning contracts.

## Policies and inconsistencies requiring explicit attention

### 1. Initial provider adapter

- Baseline: server supports a model/reasoning catalog. No explicit provider selection was found in the current brainstorm decisions.
- Plan: [Phase 1](../phase-01-dependencies-and-service-foundation.md) pins `langchain-openrouter==0.2.9`, with provider endpoint/key configuration.
- Effect: the initial integration follows OpenRouter's request/provider behavior. Multiple model choices do not by themselves establish multiple provider integrations.
- Recommendation: treat OpenRouter as an explicit initial-provider proposal, not an accepted constraint. Keep the selected factory and catalog regardless; do not build an unrequested provider-routing service.

### 2. Agent-selected Leti model overrides

- Baseline: the owner configures model/reasoning, Leti inherits by default. The earlier tool checkpoint's LetiSpec contains name/description/system_prompt only.
- Plan: [tool contracts](../tool-contracts.md) and [Phase 12](../phase-12-messaging-and-box-lifecycle.md) add optional model_id/reasoning_effort to create_box LetiSpec. The calling Leta can therefore choose overrides.
- Effect: model/cost configuration is no longer exclusively owner-controlled.
- Recommendation: remove those fields from the agent tool; keep owner-only configuration APIs. This is a proposed correction, not a completed edit.

### 3. Lifetime workspace binding

- Baseline: a Leta belongs to one workspace. Whether a left/archived account could ever move to another workspace was not separately settled.
- Plan: [Phase 3](../phase-04-workspace-resource-access-and-scope-view.md) retains the binding on inactive memberships and adds a unique index including them. The identity cannot join another workspace later.
- Effect: creating a new Leta is required for a different workspace; this is stronger than one active membership at a time.
- Recommendation: explicitly review this lifetime interpretation before implementing the constraint. It is simple for immutable Leta.workspace_id, but must not silently become policy for every managed account.

### 4. Fixed member role and applicability to existing managed accounts

- Baseline: create_agent admits an own agent as member without admin escalation. The checkpoint describes a default member role and a narrowly authorized creation path.
- Plan: [Phase 3](../phase-04-workspace-resource-access-and-scope-view.md) requires managed rows to remain member, rejects later promotions through existing paths, and applies the new mapping/constraints to managed memberships generally.
- Effect: this can change existing Account/Workspace product behavior outside Leta; migration stops on historical agent-admin or multi-workspace data.
- Recommendation: keep member-only Leta creation, but do not extend permanent role/single-workspace restrictions to unrelated managed accounts without explicit scope approval. Creation permission and future administrator authority are separate questions.

### 5. Mandatory retained owner visibility

- Baseline: owner sees Leta resources/files, owner viewer survives archive, and ownership does not inherit Leta's foreign personal grants.
- Plan: [Phase 3](../phase-04-workspace-resource-access-and-scope-view.md) makes the default owner viewer non-relinquishable and discoverable through the owner's self-view even after the owner leaves the workspace.
- Effect: archive and workspace departure do not remove access to retained Leta personal files; ordinary revoke/repair must preserve this mandatory default.
- Recommendation: keep retained owner visibility as the concrete implementation of the baseline; explicitly disclose the non-relinquishable/post-owner-leave extension. It does not preserve shared-scope access.

### 6. Reusing names after deletion

- Baseline: names unique within the stated Leta namespace; Leti names immutable. Lifetime versus live-resource uniqueness was unspecified.
- Plan: [Phases 8](../phase-03-leta-domain-schema.md) and [12](../phase-12-messaging-and-box-lifecycle.md) enforce live uniqueness only. After archive and completed box-home trash, names can be reused with fresh box/Leti/home IDs. Box name is immutable while live.
- Effect: a reused name points to a new resource; historical IDs/messages never switch identity. Old paths can still require normal collision handling on owner restore.
- Recommendation: keep live-name reuse and immutable box paths for MVP; this is a product choice added during planning.

### 7. Disconnected communication graphs

- Baseline: undirected allowed-message edges, one representative, no execution DAG. Connectivity was unspecified.
- Plan: [Phase 12](../phase-12-messaging-and-box-lifecycle.md) explicitly permits disconnected boxes.
- Effect: an isolated nonrepresentative cannot exchange work/results with the representative, although it may have its own schedule/HITL.
- Recommendation: do not add a connectivity restriction without a need, but disclose that create_box does not guarantee every node can return a result to Leta.

### 8. Oversized pending input

- Baseline: Leti receives all pending contents in its captured batch; Leta receives a digest.
- Plan: [Phase 10](../phase-10-langgraph-agent-runtime.md) fails explicitly without advancing cursor when a valid complete new batch still cannot fit after old-context compaction. Leta's digest retains IDs/counts for the complete snapshot, not an arbitrary first page.
- Effect: the engine does not silently split/drop/summarize Leti input. It also does not guarantee automatic progress for an oversized batch. Changing the model can help; no selective inbox-resolution API was designed here.
- Recommendation: retain explicit failure as the faithful initial behavior, but approve this limitation deliberately. Automatic splitting would change the agreed all-pending steering rule.

### 9. Permanent run failure wake behavior

- Baseline: record failures and retry safely; no product step/call budget. A terminal-failure wake policy was unspecified.
- Plan: [Phases 8–10](../phase-09-temporal-agent-inbox.md) add failure_wake_seq. The same failed high-water mark cannot trigger an automatic hot loop; new input or explicit configuration/resume control can wake another attempt.
- Effect: permanently failing work remains visible/pending rather than consuming CPU/model calls forever. New input may encounter the original cause again.
- Recommendation: keep this small anti-spin rule. Do not present it as automatic failure repair or add a task state machine.

### 10. Interrupted shell/Monty execution

- Baseline: arbitrary shell effects do not become exactly once through checkpoints; unknown mutations require inspection.
- Plan: [Phases 5](../phase-06-letfs-text-mutations.md), [7](../phase-08-mirage-workspace-adapter.md) and [10](../phase-10-langgraph-agent-runtime.md) persist the actual tool start. A start without a saved result returns outcome_unknown under the same tool_call_id instead of rerunning the compound command.
- Effect: even a crash after the start marker but before actual execution can require inspection. The rule also conservatively covers read-only compound commands; simple replayable read tools remain different.
- Recommendation: keep the conservative compound-command rule. It avoids introducing a command parser/effect ledger to guess which partial statements ran.

### 11. Calendar wildcard accidentally narrowed

- Baseline: the earlier tool checkpoint explicitly allows CalendarField="*" or an array of integers/ranges.
- Plan: [tool contracts](../tool-contracts.md) lists only arrays; [Phase 14](../phase-14-temporal-schedules-calendar.md) does not explicitly preserve the wildcard input.
- Effect: this is an unsupported contract omission, not a new agreed simplification.
- Recommendation: restore explicit "*" acceptance and normalize it to native ranges. Do not ask the user to reapprove the previously recorded wildcard capability.

## Engine persistence and Temporal detail added by planning

### 12. Domain identities and concrete schema

- Baseline: separate product records, account for Leta, none for Leti, stable retry identities, one thread per agent.
- Plan: [Phase 8](../phase-03-leta-domain-schema.md) makes root agent ID equal Account UUIDv7, derives thread_id from agent ID, reserves personal scope/home/membership/leave/grant IDs before effects, and uses eight product tables plus saver tables. JSONB holds source data, request payloads and schedule specs; no extra conversation/inbox/task/grant table.
- Added state enums: lifecycle initializing/active/deleting/archived; business runs running/paused/completed/failed/cancelled. Root-only authority fields are not copied onto Leti rows. Current inbox progress inside a run belongs to checkpoint; runs stores a return-time projection.
- Recommendation: keep. These are concrete storage choices rather than new user-facing entities.

### 13. Commit-ordered message and activity cursors

- Baseline: inbox cursor must never skip input; UI/history uses bounded pagination.
- Plan: [Phase 8](../phase-03-leta-domain-schema.md) allocates per-agent inbox_seq/activity_seq under short row locks rather than PostgreSQL sequences. Root/box gates serialize creation against deletion; composite FKs constrain graph endpoints and representative ownership.
- Why: a sequence value allocated first can commit later, so a high-water reader could skip it. No lock covers LLM or remote I/O.
- Recommendation: keep; modest write serialization per recipient buys correct cursor semantics without a new queue/lease.

### 14. Coordinator command receipts in activity_log

- Baseline: stable command identities, six Workflows and existing save Activities; no operation/outbox engine. Exact dedup after Continue-As-New was not specified.
- Plan: [Phase 8](../phase-03-leta-domain-schema.md) adds internal resource_change admitted/completed rows with actor/resource/action/key, canonical payload hash, admitted snapshot and completed result. Completed retries return before state/effects. These rows are retained and excluded from LLM transcript tools.
- Concrete issue: pause K loses its response; resume J succeeds; Workflow rotates; retry K must not pause the agent again. Update ID dedup alone does not survive the new execution as a lifetime command receipt.
- Cost: this is durable deduplication bookkeeping even though it reuses a table. More retained rows, checks and SQL calls are real complexity.
- Activity invocation change: schedule save→apply→return becomes save(admit)→apply→save(complete)→return using the same definition; some config commands likewise call save again. No seventh Workflow or new finalize Activity definition.
- Recommendation: retain the minimal receipt behavior, or explicitly narrow the retry guarantee. Do not justify it solely with “no new table.”

### 15. Workspace internal receipts retained indefinitely

- Baseline: reuse existing Workspace mutation keys/receipts, preserve key across RPC retry, and never recreate a revoked grant through repair.
- Plan: [Phase 3](../phase-04-workspace-resource-access-and-scope-view.md) extends existing idempotency_keys to scope commands, stores stable ingress hashes, treats null expiry as pending and infinity as completed internal retention. Existing public completed retention remains 24 hours.
- Why: grant K completes; revoke J completes; a delayed K retry after rotation/receipt pruning must not grant again. SQL membership/grant command completion waits for graph acknowledgement.
- Cost: retained internal receipts grow with commands. This is separate from Leta's coordinator receipt because Workspace owns the actual grant effect.
- Recommendation: keep within the agreed retry semantics; no second grant ledger or cleanup poller.

### 16. Runner recovery and writer details

- Baseline: one writer, saver/advisory lock, RAM within invocation, same run on retry.
- Plan: [Phase 10](../phase-10-langgraph-agent-runtime.md) uses one dedicated saver/lock connection, rejects reconnect-without-reacquisition, rechecks completed result after lock, and distinguishes pending-node resume, control-interrupt resume, final-checkpoint finalization and genuinely new run.
- Effect: final checkpoint followed by failed SQL finalization does not cause another model call. Recovery selector and graph entry may each load state; no per-model-loop reload is promised.
- Recommendation: keep. This fills real recovery branches, not another durability layer.

### 17. Cooperative control and operational segmentation

- Baseline: pause/yield at a safe boundary and Continue-As-New even during long work; no model-call budget.
- Plan: [Phases 9–10](../phase-10-langgraph-agent-runtime.md) choose runs.yield_requested, public control-only interrupt/Command resume, and automatic invocation segments. Initial tests yield after 128 boundaries or two minutes, with recursion_limit=4096. Same business run/thread continues.
- Cost: periodic invocation/connection/Mirage rebuild and checkpoint recovery, even before Temporal history requires rotation. This is additional scheduling work, not free.
- Recommendation: keep a verified segmentation mechanism so upstream recursion is not a product cap; treat the particular thresholds as tunable experiments, not accepted performance claims.

### 18. Exact checkpoint/publication nodes and public summary input

- Baseline: persisted compaction summary, typed inbox/compaction UI and public history; no hidden reasoning; publish after checkpoint.
- Plan: [Phases 10–11](../phase-11-history-and-compaction.md) choose separate boundary→summary→collect→publish→model→assistant-publish nodes; explicit actual tool-start/result reuse; a supported async summarizer callable filters public blocks BEFORE its fixed prompt. Catalog supplies context/output counts; disable the middleware's implicit 4k-tail truncation or prove complete older-prefix coverage.
- Cost: more checkpointed middleware boundaries and a maintained public-block projection. The 80% trigger/20% recent policy already existed in brainstorm, so it is not a new addition.
- Recommendation: keep these correctness/privacy details. Do not confuse upstream source availability with a passed graph-order/runtime test.

## Service interfaces and filesystem additions

### 19. Concrete Account/Workspace RPC surfaces

- Baseline: services own their data/tuples, native provisioning/aggregate view required. Exact transports/method set were not all settled.
- Plan: [Phases 2–3](../phase-04-workspace-resource-access-and-scope-view.md) add Account EnsureManagedAccount/UpdateManagedAccount; new Workspace private gRPC listener and seven methods: GetWorkspace, ListMembers, AddAccount, RemoveAccount, GetFilesystemView, ResolvePersonalScope, ChangeScopeAccess. Explicit service credential/delegated actor allowlists; no generic lookup authority granted to Leta.
- Account internal ensure reuses repeat-safe owning store/tuple publication directly; it does not add an Account Workflow. Public Account creation stays intact.
- Cost: proto/client/listener/config and wire tests across services. Recommendation: keep typed native boundaries; no cross-service SQL.

### 20. Retained managed-owner mapping and aggregate view algorithm

- Baseline: Workspace supplies batch-authorized filesystem view, no mirrored grants table.
- Plan: [Phase 3](../phase-04-workspace-resource-access-and-scope-view.md) adds managed_owner_id to retained membership, backfilled from Account. View pages shared+retained personal candidates; three BulkChecks; scoped direct-role reads for can_relinquish; empty visible pages may still continue. LetFS BatchStat hydrates roots separately because Workspace does not own node roots.
- Cost: explicit ownership projection and multiple bounded RPCs at workspace construction. Account remains canonical owner; re-admission verifies the projection. No HITL-history lookup for access.
- Recommendation: keep the projection/view separation; review global policy constraints independently under items 3–4.

### 21. Canonical text migration and binary compatibility

- Baseline: redesign LetFS for native UTF-8 TEXT and complete applicable hooks; no raw agent blobs.
- Plan: [Phase 4](../phase-05-letfs-inline-text-and-reads.md) preserves three payload variants (TEXT/legacy inline bytes/object), adds newline/hash fields, MIME/processing-based classification and finite dry-run/apply/verify conversion including object-stored text. Canonical text uses MaxFileBytes rather than InlineLimit; no duplicate served blob copy. UTF-8 bytes/BOM/CRLF remain exact; NUL cannot enter TEXT.
- Cost: all download/copy/archive/parser/enrichment/index readers/writers need compatible handling; historical binary is never blindly decoded or deleted.
- Recommendation: keep additive migration/compatibility work. It is substantial requested LetFS redesign, not just an adapter file.

### 22. Large-text streaming across existing consumers

- Baseline: selected reads avoid whole-worker downloads. Existing 8 MiB unary transport compatibility was not designed in brainstorm.
- Plan: [Phase 4](../phase-05-letfs-inline-text-and-reads.md) introduces text references in Download and processing inventories, actor-authorized ReadText and generation-bound IngestService.ReadProcessingText, bounded frames, and actual Go/Python processor consumers. Native text writes stream their request bodies too.
- Why: converting a formerly object-backed large file to TEXT cannot turn its old signed transfer into an oversized unary inline response.
- Cost: an ingest/native compatibility change beyond Mirage itself. Recommendation: keep; avoid global RPC-limit increases or another canonical object copy.

### 23. Root restriction in backend Locator

- Baseline: Leti home restricted to box, inherited shared/granted mounts.
- Plan: [Phase 4](../phase-05-letfs-inline-text-and-reads.md) adds optional Locator.root_id covering path/cwd/node-ID/@alias, intermediate ancestry and both mutation endpoints. Bound root cannot be moved/trashed through that view. Old callers without root retain existing behavior.
- Cost: extend existing resolver and each native operation rather than relying on Mirage path checks alone.
- Recommendation: keep; otherwise inherited scope credentials could escape a Leti's box home.

### 24. Native read/tree/search wire semantics

- Baseline: stat/tree/range/lines/head/tail/search/metrics APIs and hooks agreed; precise byte/frame rules left to plan.
- Plan: [Phases 4–6](../phase-05-letfs-inline-text-and-reads.md) define one-RPC path Stat, representation size separate from original size, bounded recursive tree, streamed selectors, LF count versus logical lines, exact UTF-8 byte offsets, checksums and terminal completion/error rules. Lines preserve CR/LF and final fragments; range may split a code point.
- Effect: native selectors avoid full transfer to the agent worker, although PostgreSQL may still read/decompress a large TEXT internally. This is not a constant-I/O promise.
- Recommendation: keep explicit semantics; defaults are item 41.

### 25. Mutation semantics and retry guards

- Baseline: native text writes/append/patch/truncate, backend guards and existing revision/quota/processing rules.
- Plan: [Phase 5](../phase-06-letfs-text-mutations.md) chooses streamed atomic input; positional overwrite versus exact-replace as separate selectors; caller-reserved node ID for home creation; current identity/revision/absence guards; content-preserving no-op avoids churn only after valid guards. Lost acknowledgements reconcile known node/revision/final digest or return conflict/unknown.
- Added limitations: pwrite gaps/truncate growth fail because NUL-fill cannot be TEXT; split-codepoint edits fail. Conditional replacement advertises only absent/match; ANY does not erase backend guards.
- Cost: stale writes can conflict and require intentional re-read; no arbitrary whole-command replay guarantee. Recommendation: keep honest limits rather than silently convert to blobs/pad spaces.

### 26. Shell removal/copy behavior

- Baseline: use current LetFS node/trash/copy contracts; accept Mirage limits.
- Plan: [Phases 5–7](../phase-06-letfs-text-mutations.md) makes rm mean trash even with -f/-r, no quota release/purge; rmdir atomically requires empty. Copy/move retains no-overwrite; partial native copy output remains after failure; cross-mount move may be copy-then-trash. No fake POSIX overwrite/ownership/symlink implementation.
- Effect: Bash-like commands do not promise complete POSIX semantics. Native copy must not copy binary metadata JSON as original file payload.
- Recommendation: keep documented actual backend semantics, with model VFS guidance.

### 27. Separate artifact namespace

- Baseline: blob metadata plus nested artifact tree, image through read_file; exact projection was left open.
- Plan: [Phases 4/7](../phase-08-mirage-workspace-adapter.md) choose readonly /artifacts/home/, /artifacts/shared/, /artifacts/users/<human-id>/ source-UUID trees. Normal files are leaves. Internal absolute HOME is /home; user-facing ~ remains unchanged. Deterministic metadata JSON has versioned bytes/size/hash and changes when processing/artifacts change.
- Cost: synthetic directory projection and paired normal/artifact mounts, but no collision with real .artifacts folders or file-as-directory misuse.
- Recommendation: keep; these paths are assistant-selected contracts, not earlier user-specified mount names.

### 28. Original-image preview policy

- Baseline: image read via artifact/preview, no original raw blob handed to shell/Monty.
- Plan: [Phase 4](../phase-05-letfs-inline-text-and-reads.md) generates readonly on-demand PNG previews inside LetFS, at /artifacts/<mount-key>/_previews/<source-id>.png. Standard-library PNG/JPEG/GIF only initially; GIF first frame; dimensions/bytes/concurrency bounded; strips original metadata through decode/re-encode. Unsupported formats return an explicit result.
- Cost: new bounded backend image processing, transient CPU/RAM and lower-resolution/single-frame output. No separate persistent image Workflow. Recommendation: review this format/quality policy; keep the raw-blob boundary. Exact values are item 41.

### 29. Redis cache authorization and capability declarations

- Baseline: Redis, FRESH/current fingerprints, backend permissions, invocation-owned dynamic mounts.
- Plan: [Phase 7](../phase-08-mirage-workspace-adapter.md) specifies cache prefix including deployment/agent/root/projection digest, invocation-unique mutable session, real observe tokens, ListingVersion.NONE and pre_vfs backend authorization even BEFORE cache hits. Listing is relisted rather than trusting a directory version that misses descendant changes. Current authz/freshness can therefore involve more than one native request.
- Cost: Redis avoids bytes/refetch work, not every RPC. Permission failures fail closed. Exact freshness behavior inside one shell command is an integration gate; no invented invalidation bus.
- Recommendation: keep current permission checks and actual supported cache hooks; measure redundant Stat calls before optimizing.

### 30. Complete literal search and Mirage fallback rules

- Baseline: full applicable hooks, native exact search/GIN, Mirage owns regex/commands and accepted fallbacks; semantic search is separate.
- Plan: [Phase 6](../phase-07-letfs-native-text-search.md) uses complete bounded FILES/LINES streams with no cross-request snapshot cursor; searches text plus readable binary-metadata/artifact representations. Overflow explicitly declines the Mirage hook rather than providing incomplete exclusion candidates. Unicode-unsafe case folds, whole-word/multiline constraints can overinclude or fall back, preserving correctness.
- Effect: some grep flags/short/common terms still scan/read bodies; filling all hooks never guarantees every command pushes down. Literal search remains available with semantic allow_indexing=false.
- Recommendation: keep correct candidate completeness; no second regex parser/search service.

### 31. Default-planner GIN performance acceptance

- Baseline: GIN chosen; earlier isolated benchmark still scanned, tune real query without globally disabling seqscan.
- Plan: [Phase 6](../phase-07-letfs-native-text-search.md) makes release acceptance require an effective default GIN path and repeatable gain for at least a selective sufficiently large real scope/subtree case, with index/write costs recorded. Small/common/short-query scans remain valid. Index uses partial storage_kind=text predicate, with existing fenced migration rather than unrequested online-index tooling.
- Cost: a performance gate can keep the phase open after functional correctness. Recommendation: keep the measured gate to substantiate the selected optimization; do not advertise universal GIN benefit.

## HITL, schedule, UI and operations detail

### 32. HITL edge behavior

- Baseline: kinds/statuses/recipients/grantee/forms already accepted.
- Plan: [Phase 13](../phase-13-async-hitl-resource-access.md) chooses already_granted fast return, exact full-form answer maps, blank text accepted, once-normalized server deadline, clock_timestamp after row lock, idempotent identical terminal response, conflict for changed/late response. Human API can acknowledge committed acceptance while actual grant remains pending.
- Effect: no duplicated permission prompt when current rights suffice; late duplicate of a previously valid answer can still return its result. Grant revalidation can permanently fail after a valid acceptance, which remains resolved with failure outcome.
- Recommendation: keep these explicit edge rules; no extra HITL status or held-tool executor.

### 33. Exact native schedule compilation

- Baseline: at/interval/calendar/end_at, anchored recurrence, native executor, BUFFER_ONE and nominal scheduled_at.
- Plan: [Phase 14](../phase-14-temporal-schedules-calendar.md) rounds absolute at upward to native second precision; intervals compile epoch-relative offset plus start boundary; at compiles full UTC calendar with one remaining action; recurring end_at maps directly. End_at on at is rejected, target reassignment omitted.
- Cost: not subsecond scheduling; DST/missing-day semantics follow native Temporal. Recommendation: keep these concrete mappings and explicit seconds precision; retain wildcard correction under item 11.

### 34. Editing an already fired one-shot

- Baseline: one-shot exactly one logical occurrence, stable identity on retries. Editing after fire was not specified.
- Plan: [Phase 14](../phase-14-temporal-schedules-calendar.md) preserves consumed allowance for metadata/pause edits and lost acknowledgements. Explicit change to timestamp/spec rearms a new occurrence; already-due at uses the same delivery Workflow/result instead of rerunning a completed occurrence.
- Effect: rename/title edit does not send again; explicitly rescheduling a consumed reminder can run again.
- Recommendation: keep this product behavior, subject to user review.

### 35. Pause/delete admission boundary for scheduled inputs

- Baseline: stop future source; do not retract committed inbox input.
- Plan: [Phase 14](../phase-14-temporal-schedules-calendar.md) treats delivery snapshot as admission for pause: pause after snapshot does not retract it even if inbox delivery is still pending. Delete checks tombstone/root state again at inbox admission and can skip that late delivery. Snapshot freezes payload across later edits.
- Effect: pause is not a guarantee that only already-committed inbox rows can still arrive. Recommendation: explicitly review this chosen boundary; changing it requires another current-state check before receive, not another scheduler service.

### 36. Calendar preview pagination and ordering

- Baseline: frontend gets bounded definitions/occurrences; Temporal preview is not execution history.
- Plan: [Phase 14](../phase-14-temporal-schedules-calendar.md) continues native matching times from exclusive last timestamp around the server's 1,000-result cap, limits definitions/RPCs, and exposes incompleteness. Across many schedules, pages do not guarantee globally earliest-first order; FE merges/sorts fetched pages. Temporal outage leaves definitions readable but recurring preview explicitly unavailable.
- Cost: less backend merge/cursor machinery, but a partially fetched calendar cannot claim to show every event in range. Recommendation: keep bounded explicit completeness; review the non-global page ordering if frontend needs a different contract.

### 37. Historical/live API projection details

- Baseline: PG product UI, typed custom input/compaction cards, actual send distinct from note, no CoT.
- Plan: [Phases 11/15](../phase-15-owner-api-and-ui-contract.md) choose a selected agent's seq cursor plus independent chat cursor, six public transcript variants, message refs rather than duplicate chat bodies, owner-side box creation endpoint and recipient-only human-request endpoints. No global cross-agent commit sequence; raw runtime input is not default chat rendering.
- Cost: frontend handles typed entries and two streams of records rather than a flat messages array. Recommendation: keep explicit projections. Exact public route spellings/grouping are new plan choices, not additional runtime components.

### 38. Provisional token loss on reconnect

- Baseline: bounded Redis replay and PG fallback, no whole-lifetime replay.
- Plan: [Phase 16](../phase-16-redis-agui-streaming.md) captures Redis head before PG snapshot, suppresses duplicate fully materialized blocks and orphan pre-head suffixes, and uses fresh attempt identity on runner recovery. Provisional pre-head output may disappear until a durable transcript replaces it. Durable domain refs dedup by existing IDs.
- Cost: valid simplified reset behavior does not preserve every partial token; avoids reconstructing historical open blocks. Recommendation: keep and disclose this UI behavior.

### 39. Per-connection PostgreSQL state refresh

- Baseline: Redis worker→API streaming, no general repair poller. New-run/HITL discovery on an already open SSE connection was not specified.
- Plan: [Phase 16](../phase-16-redis-agui-streaming.md) refreshes PG state every two seconds per connected SSE session, batched for its explicit subscriptions, to discover new runs/requests/control state.
- Cost: real polling proportional to connected clients; latency up to the refresh interval for those changes. It is not an all-agent reconciliation process, but should not be hidden by that distinction.
- Recommendation: keep as a small MVP alternative to a separate notification topology; measure query load. Stop on disconnect.

### 40. Redis failure policy

- Baseline: Redis is disposable cache/temporary replay, not authority. Failure fallback specifics were not settled.
- Plan: [Phases 7/16/17](../phase-16-redis-agui-streaming.md) makes stream writes best effort without rerunning business effects. Initial Mirage cache-dependent filesystem calls return typed tool errors during Redis outage rather than an unverified cache bypass. Durable inbox/HITL/schedule processing continues. One private nonpersistent bounded Redis deployment serves both namespaces.
- Cost: filesystem tool availability depends on Redis in this first integration, despite canonical data remaining in LetFS.
- Recommendation: keep the honest initial failure contract unless a cache-bypass path is explicitly tested and selected; do not claim Redis outage is impact-free.

### 41. New operational defaults

These numbers were selected by planning, not product requirements or measured production settings. Keep them configurable/subject to the owning experiment, with no product model-call budget.

| Area | Proposed initial value | Owner |
| --- | --- | --- |
| Temporal history rotate | 8,000 events or 8 MiB, plus server suggestion | Phase 9 |
| Local SQL / Local Activity | 2s statement timeout / 5s start-to-close | Phase 9 |
| Runner heartbeat | Every 1s, 10s timeout | Phase 9 |
| Runner segment | No fixed periodic segmentation after items 1–18 review; yield for required history rotation/upstream safeguard only | Phase 10 |
| Tree | 10,000 entries, 4 MiB serialized ceiling | Phase 4 |
| Native data frames | At most 64 KiB | Phases 4–6 |
| Exact search literal / replace old_text | 4,096 bytes / 1 MiB | Phases 6/5 |
| Buffered text writes | 2 active, setting range 1–16, no unbounded queue | Phase 5 |
| Image preview | 40M input pixels, 2,048px long edge, 4 MiB output, 2 slots | Phase 4 |
| Filesystem view | At most 100 scopes/check batch, direct-role read concurrency 8 | Phase 3 |
| Calendar query | Default 31 days, max 366; 1,000 occurrences/page; 32 definitions/RPCs; concurrency 4 | Phase 14 |
| History API | Default 50, max 100 entries; byte limits/detail handling still need consistent implementation | Phase 11 |
| Redis run replay | 24h touch TTL, 8 MiB payload, 20,000 entries/run | Phase 16 |
| SSE | 32 subscriptions/connection; 2s state refresh; coalesce 25ms/16 KiB | Phase 16 |
| Redis server | Initial 256 MiB; bounded allkeys eviction preference after SDK tests | Phase 17 |

Earlier tool defaults (for example 30-second shell timeout, 200-line read and 20-item tool pages) and compaction 80%/20% already appear in the brainstorm, so they are not new decisions. Some concrete pool/concurrency/memory/output defaults remain execution tuning, not values already settled in this plan.

### 42. Packaging, readiness, rollout and recovery

- Baseline: Python API/worker in leta, two queues, existing deployment/backup conventions, no separate scheduler/chat service.
- Plan: [Phases 1/17](../phase-18-deployment-and-recovery.md) selects FastAPI lifespan, one image/two processes, initially one worker process hosting both SDK Workers, dedicated Leta DB role/database, explicit Goose+saver migration CLI rather than startup migrations, private Workspace RPC and Redis. Readiness does not infer model health by paid inference; Redis is reported degraded rather than stopping durable processing.
- New operational reach: current Compose/bootstrap/gateway/CI/recovery manifests include Leta writers/domain/checkpoints/native schedules AND model catalog/config, since restored persisted selections need the same catalog. Redis is discarded. TEXT/schema release is coordinated with incompatible old binaries fenced, not claimed as an independent rolling release.
- Cost: multi-service coordinated rollout and backup/restore work. No new backup daemon, schema framework, cloud platform or deployment authorization.
- Recommendation: keep existing owning operational routes and explicit finite migrations. Phase 1 must prove actual dependency/native-wheel compatibility; all runtime/crash/search-performance/restore tests remain unexecuted.

## Baseline deliberately not counted as additions

The stack, one workspace for Leta, six Workflow types and their Local/regular definitions, Update-with-Start admission, PG inbox messages, Leta digest versus Leti full steering, single send_message, representative/edge rules, retained idle Leti, resource-owner approval granting to root Leta, owner-addressed multi-question ask, four HITL statuses, at/interval/calendar with BUFFER_ONE, inherited permissions, normal mounts, Redis cache, Mirage/Monty/full applicable hooks, GIN choice, own-agent history tools, persisted compaction/custom UI and RAM-within-invocation behavior were already brainstormed. They should not be presented as new decisions requiring another design interview.

## Review disposition

Items 1–34 are settled with corrections in the current workspace-resource checkpoint. Original account-based, large-text-streaming, sibling artifact namespace, command-specific backend and rejected retry recommendations remain historical only. Items 35–42 are presented for review next and are not accepted by silence. The implementation plan requires coherent rewrite after this final review; no implementation has started.
