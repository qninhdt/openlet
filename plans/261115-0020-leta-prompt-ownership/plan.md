# Leta: prompt ownership, focused review and completion

Date: 2026-11-15. Status: **Design approved, including prompt, shared filesystem, naming, model-facing formats and revised file-read/execute contracts. Implemented and published; see the execution record in section 11.** See [tool-format.md](tool-format.md) and [read-execute.md](read-execute.md).

This is a new follow-up to the implemented [inference/runtime plan](../261114-0035-inference-prompts-compaction/plan.md), not a reopening of that implementation. The user approved the detailed prompt proposal following the audit of two HANA acceptance runs. This document preserves that decision before any product changes.

## 1. Evidence and objective

The two runs used 176 versus 206 tool calls and 117 versus 165 generations. The newer run reduced tool errors from nine to six, but team work expanded. Root substantially analyzed the task before delegation; reviewers expanded scope; completion acknowledgements woke agents again; results were revised in small steps across duplicate deliverables. Five new compactions do not demonstrate a broken compaction engine.

The audit also found concrete tool defects: activity-history searches match their own queries, previews hide useful evidence, semantic-search default scope is unclear, and recipient-relative home paths caused nested box folders. Prompt changes do not fix search implementation defects.

Detailed evidence remains outside source at `/tmp/openlet-two-run-audit/REPORT.md`, with the two runs under `/tmp/openlet-single-deepseek/` and `/tmp/openlet-single-deepseek-rerun/`. These are local evidence paths, not durable repository dependencies.

Objective: delegate before duplicating substantial work, give each deliverable an owner, verify consequential claims, and finish exchanges when work is complete. Do not add a planner, review engine, acknowledgement classifier, task ledger, retry framework or custom agent loop.

## 2. Approved common prompt replacements

Authoring source: [common.md](../../apps/leta/prompts/common.md). Replace overlapping paragraphs rather than append these blocks to all existing instructions.

### Completing the task

```markdown
## Completing the task

Identify the requested outcome, constraints, and deliverables. Do simple work directly. For larger work, divide responsibilities before doing substantial analysis.

Produce the requested deliverables and the supporting material needed to trust them. Keep one authoritative version of each result. Do not create additional reports, approval rounds, or tracking documents unless they serve a distinct need.

When new information arrives, update the affected result. Reopen completed work only when the new information changes its correctness, requirements, or authorization.
```

No fixed maximum number of documents or work steps. Workpapers remain appropriate when they serve a distinct purpose; avoid several living reports that repeat the same state.

### Evidence and verification

```markdown
## Evidence and verification

Verify consequential claims: calculations, requirements, permissions, and effects that determine the outcome. Check the relevant passage or calculation rather than rereading every source.

A successful tool result confirms the reported operation. Do not immediately read the entire file merely to confirm that the write succeeded. Inspect the affected content when correctness still needs checking.

Separate source requirements, calculated conclusions, and recommendations. Do not turn a suggestion or an assumption into a mandatory condition.

Review a teammate's result for coverage, supporting evidence, and material inconsistencies. Recompute critical values when independent verification is needed; do not reproduce the entire assignment by default.
```

Preserve explicit user requirements for independent verification. This narrows redundant work; it does not remove meaningful QA.

### Efficient tool use

```markdown
## Efficient tool use

Before calling tools, identify the information needed for the next decision. Retrieve independent items together when practical.

Use `execute` for a related search, comparison, or calculation that can be completed in one short command or script. Print the findings needed for the next step rather than entire inputs.

Apply the changes already known to be necessary in one editing pass, then check the affected content. Keep dependent operations in order and avoid concurrent writes to the same file.

Use returned paths rather than guessing artifact filenames. Reuse evidence already available in context; reopen a source when a missing passage, ambiguity, or changed file requires it.
```

Keep output continuation/output_path guidance, supported shell commands and Python module names, Python subset restrictions, encoding guidance, and filesystem constraints. Do not route every operation through shell: images and passages still suit file_read; literal edits still suit file_edit.

### Search scope

```markdown
Search the location that contains the relevant evidence. An empty result applies to that search scope; it does not establish that the information is absent elsewhere.

Use activity-history tools only for earlier evidence missing from the current context.
```

### Delivery and final activity note

```markdown
Only `inbox_send` delivers a message to the recipient. After delivering the result, keep the final activity note to a short completion or waiting status. Do not repeat the report, calculations, or identifiers there.

Lead with the result, decision needed, or remaining blocker. Include the supporting detail the recipient needs and link to longer deliverables.

Use names and file paths in ordinary communication. Include technical identifiers when they are needed to identify an item, support an audit, or perform the requested action.
```

No hard token cap on useful user-facing explanations. Preserve message-ID versus conversation-ID instructions, inbox delivery semantics, event-driven waiting, HITL/access rules, source/instruction separation and authorized-action boundaries.

## 3. Approved root delegation replacement

Authoring source: [root.md](../../apps/leta/prompts/root.md).

```markdown
## Delegating work

Use a team when the task benefits from distinct expertise or independent work. Once you understand the request and source locations, assign each substantial part before doing that same work yourself.

Give each assignment a clear outcome, relevant sources, constraints, and expected deliverable. Identify who owns shared deliverables so teammates do not make overlapping changes.

Keep standing roles in the Leti instructions and the current assignment in the task message. Do not repeat the complete task in both.

While the team works, handle a separate responsibility. When results arrive, integrate them and resolve specific material gaps. Do not become another worker on an already assigned analysis.
```

Keep immutable box graph, representative routing, box_create not starting work, and deletion not being a completion signal. Do not encode procurement-specific roles into the product prompt.

Illustrative current-task message, not a product template or new structured protocol:

```text
Compare the supplier quotations against the delivery and budget requirements. Own the comparison CSV and supporting calculations.

Ask the reviewer to independently check the totals and any contract or test conditions that could change the recommendation. Resolve material discrepancies, then send me the recommendation, remaining uncertainty, and file paths.

I will handle the user's decision and final delivery.
```

## 4. Approved Leti completion and review guidance

Authoring source: [leti.md](../../apps/leta/prompts/leti.md).

```markdown
## Completing your assignment

Return the requested result, the evidence needed to use it, deliverable paths, and any unresolved blocker. Keep detailed work in the shared files instead of repeating it in messages.

Request follow-up for a specific missing part or material discrepancy. A usable result does not need another general review round.

Send a completion message when your assignment is ready. Do not send a separate acknowledgement or thank-you to another agent unless it communicates new information or requests an action.

As the representative, assign distinct parts to teammates and combine their results. Resolve consequential differences and send one coherent result to the root.

Once the result has been delivered and no assigned work remains, end the turn. Resume when a new message introduces work or changes the result.
```

Do not suppress substantive updates, requested replies, warnings or actual new work. No inbox classifier or workflow termination change.

For a reviewer assignment, root should give a bounded standing role of this form; this is guidance for role creation, not a mandatory QA policy for every Leti:

```markdown
Review the assigned result for errors that could change the decision, violate a requirement, or make the deliverable unusable.

Report each material finding with its evidence, consequence, and required correction. Clearly label optional improvements as suggestions.

If there are no material findings, state that briefly. Do not require cosmetic changes or create additional review documents unless requested. Recheck corrected findings when needed; do not restart the entire review.
```

## 5. Approved tool-description changes

Owning code: [runtime/tools.py](../../apps/leta/src/leta/runtime/tools.py). Keep native tools and signatures.

file_semantic_search:

```text
Find passages by meaning within the given paths. Omitted paths search only your home (~), not external storages. Use shell search for exact text.
```

history_search:

```text
Search earlier activity using literal keywords; all query terms must match. Use a few distinctive terms. Omit query for recent previews.
```

These describe existing semantics. The approved [tool-format.md](tool-format.md) adds content-focused history previews and sequence references. The separate history self-matching/search-selection fix remains deferred; do not silently expand format work into that implementation. Likewise, do not change retrieval top_k, relevance cutoffs, reranking or ingestion artifacts as part of prompt editing.

## 6. Approved compaction prompt clarification

Authoring source: [compaction.md](../../apps/leta/prompts/compaction.md). Keep native summary-plus-tail behavior and existing headings: Goal and constraints; Current state; Pending and waiting; Next steps and references.

Add near the start:

```markdown
Summarize only the older messages supplied here. More recent messages may be retained separately and may change the state described in this summary. Do not infer events outside the supplied conversation.
```

Replace overlapping summary-update guidance with:

```markdown
Merge the previous summary with the supplied messages into one current account. Replace superseded state rather than accumulating a chronology.

Preserve the outcome of completed work and the references needed to continue. Keep detailed calculations and reports in their files.

For pending work, state the next unresolved action, its owner when relevant, and the reply or event being awaited. Remove pending items that the supplied messages show as completed.
```

Add to common:

```markdown
A conversation summary covers earlier messages. When newer messages or tool results update that state, use the newer information.
```

Keep {{summary_max_tokens}}, summary safety instructions and factuality rules. Do not change threshold, retained tail, summary model, output budget or engine in this work. An older-prefix summary can correctly describe state later changed by the retained tail.

## 7. Approved shared filesystem

Current implementation uses root Leta identity for LetFS calls, but binds a Leti's /home to boxes.home_node_id. Discover excludes the parent home storage from /mnt, so the Leti cannot reopen it through an external mount. The restriction is primarily a subtree binding, not a distinct Leti storage permission model. See [filesystem/workspace.py](../../apps/leta/src/leta/filesystem/workspace.py) and [filesystem/letfs.py](../../apps/leta/src/leta/filesystem/letfs.py).

The user approved removing box/Leti filesystem isolation for the MVP. Root and its Leti are shared workers in the same parent Leta storage. The former recipient-dependent home mapping is superseded, so do not publish instructions explaining that old mapping.

- Root and all its Leti mount the same Leta storage root at /home; ~ denotes that same root for everyone. Keep ordinary ~ to /home expansion, remove per-box rebasing.
- Keep a directory under ~/.boxes/ for that team's temporary files and work products. Provide its exact path in box context. It is an organizational folder, not a filesystem security boundary or a separate mount. Use the approved short unique box name in place of the UUID as specified in [tool-format.md](tool-format.md).
- Root hands off existing file paths in messages. All participants use identical paths; no copies, custom sharing RPC, symlinks or path translator are required.
- Keep default tool path/cwd semantics aligned at ~. Agents can use explicit paths and execute.cwd for their box directory; no hidden recipient-dependent working-directory behavior.
- Leti have the same filesystem authority as their parent Leta, including access to sibling box folders. They remain distinct in conversation, role and communication links. Describe ownership in prompting; do not pretend this is hard isolation.
- Retain workspace/storage authorization, personal-storage grants, external read/write capabilities, live containment inside each actual storage root, readonly generated artifacts and existing mutation/version handling. No access to unrelated Leta storage or host filesystem is implied.
- Preserve the lifecycle's actual box-folder node as cleanup target; never substitute the common filesystem root for boxes.home_node_id. Do not change archive/delete retention policy implicitly. Final deliverables that must survive deletion belong outside the box folder under the existing lifecycle.

This replaces the former per-box containment decision for Leti of the same parent Leta. Existing directories already live in the common storage; changing the mount root does not require copying their contents. A directory/name change is a separate operation and must not be confused with the mount change.

Approved replacement wording:

```markdown
You share the same home and accessible storages with your root Leta. Paths have the same meaning for the root and every Leti.

Use the box directory shown below for temporary files and working outputs. Read assigned sources at their existing paths; copying them into the box directory is unnecessary. Coordinate edits to shared files and keep changes within your assignment.
```

Required implementation reach: filesystem mount-root selection/cache namespace, runtime box context, root/Leti authoring and compiled fixtures, box API/tool wording that currently calls the directory home, owning filesystem/box/boundary docs, relevant unit and API acceptance expectations. Review cleanup separately from mount selection; no database column or migration is assumed necessary merely to change mount behavior.

Explicit tradeoff: a mistaken Leti write can affect parent or sibling-team files that the parent can write. This follows the intended shared-worker model. Do not add another ACL system or filesystem isolation layer to undo that decision.

This decision concerns filesystem access. Communication topology and recipient routing retain their current contracts; no change to workspace/personal-storage authorization or cross-Leta access is implied.

## 8. Naming, notifications and tool-output follow-up

The user approved the detailed naming and formatting design: canonical box name/workdir, existing sequence references, storage paths, field selection, notifications, HITL, scheduler, remaining tools and communication guidance. The contracts are in [tool-format.md](tool-format.md). Implementation and publication are recorded in section 11.

After reviewing the source comparison, the user also approved the revised [read-execute.md](read-execute.md) contracts: `file_read(path, start_line=1, limit=None)` returns plain text without per-line prefixes or an automatic 200-line window; keep the existing byte cap and actionable continuation. `execute(command, cwd="~")` returns terminal output without a success exit banner, uses `(no output)` for an empty successful result, and reports nonzero exit, timeout/cancellation or unknown completion. Native image content, error metadata and truncated-output recovery remain intact.

The user also requested renaming the shell-facing tool to `execute`. Target name: **execute**, with `command` and `cwd`; remove exec_shell from the published catalog when implementing. Keep the existing shell/Python-through-shell capability, timeout ownership and sandbox/runtime restrictions. No second execution tool or alias.

## 9. Authoring, publication and validation

- Use Markdown source, one paragraph per source line; do not hard-wrap prose or author it as escaped newline strings.
- Deduplicate broad brevity/efficiency/collaboration instructions. Preserve product concepts and useful operational restrictions. Do not lengthen prompts by retaining both replaced and replacement paragraphs.
- Preserve native Langfuse common composition, role placeholders, config and effective model/reasoning selection. Keep local authoring, resolved API fixtures and published revisions aligned.
- Publish common first, then root/Leti with the new numeric common reference; publish compaction wording separately as needed. Verify resolved variables/composition before moving production labels. Do not change prompts during an acceptance run.
- Check affected fixtures, formatting and focused tests; strict Pyright for any Python changes. No new framework or benchmark source in the repository.
- After implementation, a fresh comparable run must assess business correctness, duplication, model batches, root/team tools, errors and compactions. Do not claim a tool-count reduction or stronger model adherence without evidence. No new paid inference run is started by this planning change.

Research basis: pinned Codex b1573f1 (scope and targeted verification), OpenCode d759c54 (avoid duplicate delegated work; newer history wins), Pi 8636e21 (tool-specific guidance and focused reviewer example), OpenHands 830c045 plus SDK 3c66af1 (action costs and explicit delegation outcomes). Their execution/inbox models differ; this plan does not copy their orchestration.

## 10. Execution checklist

- [x] Record the approved detailed prompt design in a new plan.
- [x] Resolve shared-home versus per-box-root decision: shared home approved; per-box filesystem isolation removed in the target design.
- [x] Record approval of naming, notifications and remaining model-facing formats; target execution-tool name is execute.
- [x] Record approval of the revised file-read/execute presentation in read-execute.md.
- [x] Implement approved prompt and tool-description replacements, removing duplicate guidance.
- [x] Update fixtures and complete focused checks.
- [x] Publish and verify Langfuse versions without changing model defaults.
- [x] Run a fresh acceptance journey and report measured results; this shorter smoke test is not a controlled comparison with the earlier HANA journeys.

No product code, cloud prompt, runtime configuration, agent data or unrelated ingestion work was changed when this plan was written.


## 11. Implementation and verification — 2026-11-15

Runtime/tool boundary: `79d9d0c` (`refactor(leta): share agent home and simplify tool contracts`). Root and Leti mount the same storage root; box directories use the validated canonical name. Cleanup still targets the saved folder node, never the common home. Following the user's permission to discard old demo data, the 11 old active boxes were archived through their existing lifecycle; no data migration or dual path support was added.

Agent tools now use box/teammate names and recipient-scoped incoming message numbers; history reads use the existing agent-scoped entry sequence. Public resource UUIDs, history pagination and event contracts remain unchanged. The old execution-tool alias and JSON-exit parsing path were removed. File reads are plain source text with optional line selection and bounded continuation. Execution returns ordered terminal text and native success/error status. Narrow projections replace raw resource rows; image blocks and image history references remain native. Root previews are 120 Unicode characters, and full Leti messages/HITL outcomes/scheduled occurrence instructions retain their existing admission ordering.

Native integration exposed two points addressed within this boundary: duplicate names are rejected before starting a resource workflow (after checking the existing idempotency receipt); a nonrepresentative cannot label its message as the box to contact root. Tool-driven box creation/deletion uses Mirage's existing `Workspace.notify` to invalidate the changed subtree, including cached bodies after deletion. There is no custom invalidation bus, cache registry or new authorization policy.

Langfuse production publication: `leta/common` **7**, `leta/root` **7**, `leta/leti` **7**, `leta/compaction` **5**. Numeric common composition, role placeholders and all previous prompt configs/model defaults were preserved and verified against Cloud's compiled response. Markdown and compiled WireMock fixtures match. Compaction thresholds, tail and budget did not change.

Verification:

- **30 Leta tests pass**, Ruff lint/format pass and **strict Pyright: zero errors** for Leta. E2E TypeScript typecheck and changed TypeScript formatting pass. Full API E2E suite was not rerun.
- Native ToolNode plus real PostgreSQL/Temporal/LetFS/Mirage/Redis: common home and edits outside box workdir, teammate/representative routing, scoped replies and mismatched-target rejection, duplicate name rejection, external storage discovery, semantic-search empty scope, scheduler create/get/list/update/delete, HITL ask/get/list/cancel and cleanup scope pass. A file outside a deleted box survives, and a previously cached file inside it is no longer readable through that tool workspace.
- A fresh DeepSeek medium purchasing journey with two Leti completed: **27 tool calls**, **26 model generations**, **zero tool errors**, **zero compactions**, five completed activity runs, one human-facing delivery. NorthPack totals **25,272,000**, SouthPack **25,790,400**, difference **518,400**, NorthPack deposit **7,581,600**. Both specialists computed independently before reconciliation. Root received the representative's result, wrote the requested recommendation and sent it to the user without acknowledgement-only exchanges.
- Public HTTP history returned distinct pages of **20 + 7** root entries; entry details and the SSE snapshot retained their contracts. Each of the three agents retains one checkpoint. The persisted recommendation was checked against the source calculation.
- Langfuse generations show logical model `deepseek/deepseek-v4.1-flash` and role prompt version **7**. Recorded aggregate usage: input **38,606**, cached input **202,240**, visible output **13,663**, reasoning output **2,258**, total **256,767** tokens across repeated requests. These are cumulative provider usage, not maximum context size. All returned generation costs remain null; no zero-cost or dollar-saving claim is made.

Evidence and temporary scripts are under `/tmp/leta-ownership-acceptance/`; supporting native/public/Cloud logs are `/tmp/leta-native-final.log`, `/tmp/leta-stored-report.log` and `/tmp/leta-cloud-final.log`. They are local evidence, not runtime dependencies or committed test fixtures.

Limits retained explicitly: this short journey does not establish a performance percentage versus the larger HANA tasks. Model final activity notes can still repeat more of the delivered answer than requested. Fresh provisioning reproduced the pre-existing transient `PERMISSION_DENIED` immediately after new relationship writes; access worked on the later attempt, and no auth consistency policy was silently changed. The previously deferred history self-match/search-selection correction remains deferred. No evaluation framework, alternate agent loop, custom retry framework or second result archive was introduced.


## 12. Approved query follow-up and full HANA rerun

The user approved four bounded optimizations after reviewing the implementation: project ordinary root notification previews in PostgreSQL instead of transferring complete bodies; resolve an incoming message number inside the conversation read; call the existing name-aware box read directly; and reuse schedule target names from the create context or existing schedule read. Keep the one-to-one label JOINs, history queries, schema, permission model and agent orchestration unchanged.

Implemented: root notification projection returns at most 122 characters (including one character beyond a possible trailing space) after PostgreSQL's native whitespace normalization; the existing renderer supplies the 120-character preview/ellipsis. Leti bodies and HITL/schedule occurrence content stay complete. Inbox reads retain recipient scoping, row locks, read marking, 20-item pagination, missing-message errors and an empty-filter response, with one SELECT and one UPDATE instead of two SELECTs and one UPDATE. Box lookup uses three SELECTs instead of four. Schedule creation uses its known target; get/update resolve the label within the existing scoped read, without a separate name query. The shared schedule read also exposes this display label to its HTTP consumers.

Validation is complete: 30 tests, Ruff and strict Pyright pass; real PostgreSQL/ToolNode checks verify preview/read semantics and reduced query counts. The original five HANA user messages were replayed in a fresh DeepSeek medium session against unchanged source documents and prompts. **The five-turn journey failed acceptance:** root treated notification previews as complete input and omitted requirements. One additional natural instruction recovered the missed history/checklist/forecast/cleanup operations; this is assisted recovery, not an unassisted pass. Final artifacts still contain narrative percentage, recommendation-versus-requirement and BOX-evidence inconsistencies.

Measured five-turn result: 120 tools, 101 generations, seven tool errors, two compactions, 11m32s. Including recovery: 162 tools, 129 generations, eight tool errors, three compactions, 15m09s. All 11 runs completed; all agents retain one clean latest checkpoint. Three workpapers survive box archival, both schedules are deleted and no HITL remains pending. Lower tool counts do not establish successful efficiency improvement because original requirements were omitted and an extra instruction was needed.

The existing input contract/prompts were not silently changed after this finding. Notification delivery/read behavior needs review before calling the golden journey complete. Detailed errors, remaining content defects, verification limits and comparison with both baselines: [HANA acceptance report](../reports/acceptance-261115-hana-query-optimization.md). Temporary scripts and evidence: `/tmp/openlet-hana-optimized/`.
