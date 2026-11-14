# Model-facing names, inputs and tool results

Date: 2026-11-15. Status: **Design approved, including the revised file-read/execution presentation in [read-execute.md](read-execute.md). Implemented; see [execution record](plan.md#11-implementation-and-verification--2026-11-15).** The user approved the naming/output design and, after the requested source comparison, the plain file-read and `execute` contracts.

## 1. Measured scope

The newer acceptance run contains 319,375 characters of tool-result text. Shell accounts for 134,765 (42.2%), file_read 71,523 (22.4%), semantic search 34,182 (10.7%) and history_search 25,740 (8.1%). Simply rendering shell and text-read responses as text, preserving content and continuation facts, changes their combined size from 206,288 to 198,079 characters: about 2.6% of all tool-result text, not a promise of large token savings.

The same run has 532 UUID occurrences inside result text, 198 inside tool arguments and 55 inside inbox-input text. These counts exclude outer history/tool-call IDs that are not themselves model content. All five original user-message bodies are free of UUIDs. Some later messages explicitly ask for activity-log evidence and schedule forecasts, but do not ask to reproduce internal UUIDs in ordinary prose.

These are character and occurrence measurements, not provider token counts, replayed-context totals or predicted latency. The main opportunities are field selection, repeated long paths, duplicated content and avoidable readback steps. A format change alone will not fix expanded assignments or excessive review rounds.

## 2. Box name and directory

Approved choice: use the existing `name` as the short canonical box name. Do not add slug/display_name fields or a transliteration dependency.

- Lowercase ASCII words separated by hyphens, e.g. `quote-review`, `release-check`, `finance-close`; maximum 64 characters. Reject invalid input with a short example rather than silently converting it or adding random suffixes.
- Keep the existing uniqueness scope: one live box with that name per parent Leta, enforced by the existing live-name unique index. No global namespace. Existing lifecycle completes cleanup before an archived name becomes available again.
- Keep the name immutable for the life of a box, consistent with the current lack of a rename API. Longer business descriptions and local-language text belong in the existing description field.
- A box called `quote-review` has workdir `~/.boxes/quote-review/`, equivalently `/home/.boxes/quote-review/`. In examples, `/.boxes/...` means this home directory, not a new mount at the virtual filesystem root.
- Root and all Leti share the same home and accessible storage mounts. The workdir is an ordinary directory, not a security boundary, separate home, auto-sync location or per-agent mount.
- Keep internal box/agent UUIDs for relationships, workflows, idempotency and API identity. Domain internals do not switch to name-based primary keys.
- Existing folder node IDs remain the lifecycle cleanup targets. Never replace boxes.home_node_id with the shared storage root. File writes outside the box directory are not owned by box cleanup.

Leti system context should include a short authoritative fact block:

```text
Box: quote-review
Work directory: ~/.boxes/quote-review/
You: analyst (representative)
Teammates: reviewer — independent evidence review
Root contact: root
```

Use actual permitted contacts and existing role facts. Add to the role instructions:

```text
Use your box work directory for temporary files and intermediate outputs unless the task specifies another location. Read source files at their existing paths. Paths have the same meaning for you and the root. Coordinate changes to shared files.
```

Keep common path/cwd defaults at `~`; use explicit paths or execute.cwd for the workdir. Do not silently reinterpret relative file-tool paths while shell uses a different default. Root need not prescribe the box workdir in every assignment because it is already in Leti context.

Implementation must inventory live existing box names and directories before cutover. Renaming existing data, if needed, is a one-time operation using actual node IDs and collision checks; do not retain two runtime naming systems, copy directories or delete old data merely to satisfy a test.

## 3. Names and existing sequence numbers instead of UUID aliases

Use meaningful names or already-persisted sequence numbers where they identify an object exactly within the current context. Do not invent `h1/s1/b1` registries, UUID-prefix matching, short-hash identities or checkpoint-dependent alias maps.

| Object | Proposed model-facing reference | Internal identity |
| --- | --- | --- |
| Box | Its unique live name | Existing UUID |
| Connected teammate | Exact name within the current box | Existing UUID |
| Parent root | Literal `root`, reserved from conflicting contact names | Existing UUID |
| Incoming message | Existing recipient-scoped agent_messages.seq | Existing UUID/conversation UUID |
| History entry | Existing agent-scoped history.seq | Existing UUID |
| Human member | user_id when addressing a particular person | Existing UUID |
| HITL request | request_id | Existing UUID |
| Schedule | schedule_id | Existing UUID |
| Storage mount | Existing /mnt/<storage_id> | Existing UUID |

Approved tool-input changes, limited to the agent tool surface:

- `box_get(box=...)`, `box_delete(box=...)`, schedule target-box selection and box filters use the canonical name. Root can send to a box name; Leti can send to `root` or a permitted teammate name. Human destinations continue using user_id; do not guess identity from a display name.
- `inbox_read(message: int, ...)` reads the conversation containing that incoming message. Resolve by current recipient plus seq, then use the existing conversation/read implementation. A notification needs one small message number rather than a conversation UUID plus source UUID.
- `inbox_send(..., in_reply_to: int | None)` resolves that incoming message number within the sender's own inbox. When replying, allow `to` to be omitted and derive the actual recipient from the saved human/agent/box sender; if both are supplied they must agree. A new conversation still requires an explicit recipient. HITL/scheduler system events are not reply destinations. No implicit reply to whichever message happened to arrive most recently.
- `history_read(entry: int, ...)` resolves by current agent plus history.seq. Search results can use the same stable sequence as the user-visible audit reference.
- Public HTTP resources, Temporal IDs, event IDs and persisted foreign keys stay UUID-based. Keep the current graph/routing and authorization checks after resolving a name or sequence. This is input resolution against existing rows, not a new authorization mechanism or RPC.

Each ToolMessage still has its native tool_call_id for correct pairing. These framework IDs need not be repeated inside result content.

## 4. Storage paths

Keep `/mnt/<storage_id>` for the MVP. Storage names may collide or change, and several storages can have the same visibility. Do not add persistent alias tables or multiple fallback naming schemes to prettify paths.

Use name and read/write capability from the existing ListStorages response for discovery output. No per-result metadata RPC:

```text
Shared project documents — read-only
  /mnt/<storage-id>

Personal documents — read-only
  /mnt/<storage-id>
```

For a directory listing or search response, print the base path once and relative child paths below it. For shell work, use cwd and relative paths when practical. Never shorten an actionable path without providing its base, or mix incompatible path forms between tools and shell.

## 5. Rendering rules and retained data

- Change only model-facing HumanMessage/ToolMessage content. Tool-call arguments retain the native JSON schema required by the model protocol. HTTP/RPC payloads, client event envelopes, source records and domain schemas do not become prose.
- Render natural text with a few labels, headings and blank lines. Do not introduce a custom syntax/parser/framework or a model call to summarize tool results.
- Use direct, typed field selection at existing owning functions. A few small rendering helpers for repeated message/result layouts are sufficient. Do not serialize a DB row and then attempt to remove sensitive or useless keys from its JSON string.
- Omit nulls, empty metadata, repeated own IDs, transport IDs and creation timestamps that are not relevant to the operation. Preserve failed/unknown outcomes, scope, permissions, truncation, continuations and exact values needed for the next action.
- Keep exact document text, numerical precision, actual paths and human answers. Metadata projection is not permission to paraphrase evidence or truncate a decision silently.
- Preserve native image content blocks and existing image artifact references. Do not turn an image into textual base64 or an image-description-only response.
- Existing full request/resource data remain in their owning tables/APIs. Existing history records the content actually shown to the model; do not create a second full-result archive or change checkpoint/history transactions for this work.
- Keep the existing approximate 4,096-token/16,384-byte tool-preview budget and line pagination. It is an estimate, not a tokenizer guarantee. No new token-counting dependency or second truncation framework.

## 6. File and execution results

### file_list

```text
Directory: /mnt/<storage-id>/HANA-launch
01_Launch_brief.md
02_Supplier_quotes.xlsx/ [document artifacts]
03_Acceptance_terms.docx/ [document artifacts]
04_Signed_QA_retest.png
```

Show directory/file distinction, artifact folders, and an opaque next cursor only when present. Ordinary listing does not need node IDs, per-entry repeated absolute prefixes, null sizes or all file metadata. If a recursive listing is incomplete without a cursor, state that the agent must narrow the path/depth; do not imply a continuation exists.

### file_read and history_read

Approved file-read contract: return plain source text without per-line numbers. Keep optional line selection and an actionable continuation only when more content remains. The exact argument/default and output contract, replacing the original line-numbered draft, is in [read-execute.md](read-execute.md). A long line that cannot fit must retain the existing explicit notice and usable alternative; an empty preview is not a successful end of file. Uploaded-document previews list artifact paths without raw tree node objects. Images remain native multimodal content.

History reads include the entry number, kind/tool and event timestamp when needed for audit, followed by the actual content. Tool-call arguments or other structured historical data can stay JSON rather than inventing prose for arbitrary schemas.

### file_write and file_edit

Keep the existing small JSON acknowledgement `{ "path": "..." }`. It is already concise and useful. Do not echo written contents, versions or backend mutation IDs.

### execute (renamed from exec_shell)

```text
NorthPack: 15044400
SouthPack: 13556160
GreenCarton: 14886720
```

Approved contract: success returns terminal output with no `Exit: 0` banner. Append the actual nonzero exit code on failure; preserve timeout/cancellation and unknown outcomes. When truncated, show the marker and saved output path; preserve whether the saved capture is incomplete. Keep native error/exit metadata. The rendering and source comparison are in [read-execute.md](read-execute.md). Do not echo the command, environment or full source inputs; they already appear in the tool call or files. Rename the catalog entry and its references to execute without keeping a legacy alias.

### file_semantic_search

```text
Search scope: /mnt/<storage-id>/HANA-launch

03_Acceptance_terms.docx/README.md
Buyer may withhold only the value of disputed units pending resolution...
```

Group by search scope and show relative source path plus passage text. The current adapter already exposes only path and text per hit, so changing delimiters alone saves little. Do not imply that unused node/score/version fields are currently the problem.

Approved presentation limit: retain the current ranked hits; display at most 800 Unicode characters per hit with an explicit excerpt-truncated marker and source path. Keep every returned hit's path visible; if the overall tool budget is reached, remaining hits are paths without excerpts, clearly labeled. At top_k=10 this bounds ordinary excerpt volume without changing ranking, adding reranking or discarding source access. Reading the returned source recovers evidence. Do not select a new top_k or relevance cutoff as an incidental formatting change.

## 7. Workspace and box tools

| Tool | Proposed model-facing content |
| --- | --- |
| workspace_get | Own name, shared home, workdir for Leti, permitted contacts by name and concise responsibility. No own/root/storage/node IDs or duplicated roster prompts. |
| workspace_member_list | Keep compact JSON items with user_id, name and role; include a next cursor only if present. A small structured directory is already readable and supports exact human targeting. |
| box_create | Text acknowledgement containing canonical name, active state, workdir and representative name. No UUID or repeated creation input/Leti prompts. |
| box_list | One short block per box: name, state, description and member count. No parent/node UUIDs, creation timestamps or full graph. |
| box_get | Name, purpose, workdir, representative and members/links by names. System prompts remain opt-in. No model/effort/internal IDs in ordinary result; task does not manage deployment configuration. |
| box_delete | Small JSON acknowledgement with box name and archived state. Confirm cleanup scope; do not replay team data. |

Box create/get must supply routable names matching the tool-input contract; output-only replacement of IDs while tool inputs still require UUIDs would be broken.

## 8. Inbox and notification formats

### Root message notifications

Keep notification-driven reading for ordinary root inbox messages. Reduce preview from 240 to **120 Unicode characters including the truncation marker**. Collapse whitespace only inside previews. Preview is for triage, not the full instruction.

```text
New messages

From User | message=73
Please check the updated budget before finalizing the recommendation...

From box quote-review | message=74
Comparison and independent review are complete. The recommendation is...
```

Use known names; do not fetch another service solely to decorate a sender label. If an identity has no available name, use its source type and the actionable message number. Do not invent a person-name mapping.

Group conversation notifications within the fetched batch, keep the newest preview and a stable message number identifying that conversation. This does not mark unseen bodies as read or drop them. Preserve the existing batch cursor/admission semantics; a future correction in the same conversation must remain available to inbox_read. Read the ordinary message body before acting on it.

### inbox_read

```text
From User | message=73
<full original message>

---

From User | message=75
<next full original message>
```

Preserve chronological order and full bodies. Do not include created_at/in_reply_to/source UUID on every item by default. Keep sender context needed to interpret the request. The message number suffices to route a reply. Include continuation only when present; do not silently truncate unread bodies and mark them fully read.

### Leti input batches

Keep direct full-message delivery to Leti, using the same text layout with sender names and message numbers. Do not turn their assignments into previews requiring another read tool. Batch messages into the existing one HumanMessage per admission boundary, preserving order; no new message per item and no grouping that reorders instructions.

### inbox_list and inbox_send

inbox_list uses the root-notification layout, with the current unread/filter behavior and a next cursor only when present. inbox_send returns a small `{ "sent": true }` acknowledgement after confirmed delivery. Its internal returned UUID/recipient seq remain available to workflow/idempotency code and are not echoed to the model.

## 9. HITL results and direct decision events

Creation/cancellation tools return concise acknowledgements rather than the whole request row:

```json
{"request_id":"<uuid>","status":"pending"}
```

Already-granted access returns that fact and effective requested access; do not present the synthetic request UUID as an existing stored request when no HITL record was created.

hitl_list returns request ID once per item, title, meaningful status and grant outcome when applicable. Include the addressed person when it is needed to distinguish requests. Omit repeated requester/root IDs, full forms, reasons and creation metadata from list views. Empty result: `No pending requests.` when that filter was requested.

hitl_get renders the request title/status, questions and options as readable text, preserving answers and notes. Resolve question/option labels from the saved form; the model need not decode q1/o2 identifiers. A compact JSON block remains acceptable for structured response content where conversion adds no clarity. Include relevant expiry/resolution information when it affects the request or audit.

Keep the question itself focused on the missing decision; put lengthy background in the report rather than repeating it inside question text and every option. This is prompt/tool-description guidance, not an extra summarization call or a hard truncation of human decisions.

HITL terminal events should be rendered directly into the existing inbox batch, for root as well as Leti:

```text
Decision: Supplier selection | request=<uuid>
Status: answered
Which supplier should we use?
Answer: GreenCarton
```

For access:

```text
Access request: Personal documents | request=<uuid>
Decision: accepted
Access: granted (viewer)
```

Preserve accepted-but-not-granted, skipped/failed grant reasons, denied/cancelled/expired and all answer notes. Accepted is never rendered as granted unless outcome confirms it. Use the stored event result, not a fabricated success or a later unrelated state.

Use the existing pending-input DB query to obtain immutable title/form labels from local HITL records when needed; do not add a per-event RPC, Temporal activity or LLM summarizer. The full result is already delivered through inbox, so an ordinary completed answer need not require inbox_read followed by hitl_get merely to decode it. Keep get available for missing details and later audits.

## 10. Scheduler results and due events

- schedule_create/update: compact JSON with schedule ID, target name, effective type/spec and paused state. Confirm the effective stored timing/bounds without echoing full content, creator IDs or timestamps. Omitted bounds must still retain current behavior.
- schedule_delete: schedule ID plus deleted confirmation; no replay of instruction/spec. Already-delivered instructions are not retracted.
- schedule_list: text with ID once, title, target name, active/paused/deleted state and concise timing. Do not include full instruction or call Temporal describe once per list item.
- schedule_get: keep filtered JSON. Exact type/spec/calendar/timezone/start/end/anchor/paused state, full instruction, upcoming matching times and forecast_status are useful structured data. Remove creator/target UUIDs in favor of target name and omit unrelated DB metadata. Forecast times of a paused schedule are matching times, not promised executions; retain that distinction.

Render a due occurrence directly into the inbox batch:

```text
Scheduled task: Review purchasing progress | schedule=<uuid>
Scheduled for: 2026-11-15T09:00:00+07:00
<full instruction saved for this occurrence>
```

The timestamp is the actual stored occurrence time. Use the delivered content snapshot, not a newly fetched edited instruction. Do not generate both a notification preview and a duplicate full scheduled message. Due instructions still wake the same existing workflow; no polling, scheduler engine change or extra RPC is introduced.

## 11. History, empty results, errors and batching

- history_search: entry number, kind/tool, meaningful evidence preview and timestamp when needed. Reduce preview to 200 Unicode characters of content rather than a 500-character JSON header. Show pagination cursor only when present. Agent/run/UUID keys are not model-facing audit evidence.
- The confirmed history self-match/recursive-search issue still requires a search implementation fix; rendering cannot cure it. Keep public history complete. Do not silently claim the previously deferred search work is implemented or approved by this proposal.
- Empty results state the relevant scope/filter: `No matches in <path>.`, `No schedules.`, or `No pending requests.` Never turn an empty scoped search into a claim about all storage.
- Errors give the actual failure and a useful correction when known. Do not mask infrastructure failures as success or add automatic parameter-repair/retry layers. Unknown mutation outcomes stay unknown. Preserve native validation feedback and error status.
- Parallel tool calls retain one ToolMessage per tool_call_id. Do not merge unrelated tool results or replay a batch-level copy of each result.
- Multiple inbox items share one HumanMessage with clear sender/type boundaries and preserved order. Bound the fetched batch using the existing admission approach; never advance past messages that were omitted because of output size. Direct HITL/schedule rendering must not also emit a second preview for the same row.

## 12. Prompt addition and implementation boundaries

Add one concise common instruction instead of repeated anti-ID rules:

```text
Use people, team names and file names when communicating. Keep routing IDs, tool names and internal execution details out of ordinary messages unless the recipient needs them to identify an item or explicitly asks for technical details. Give colleagues the exact paths and references needed for their assignment; do not repeat unrelated identifiers.
```

Paths and business identifiers such as order numbers, batch codes and contract references remain useful evidence. Do not remove them under a blanket no-ID rule.

Approved implementation scope:

1. Box name validation, provisioning paths and lifecycle ownership; shared filesystem mounting/context; one-time review of existing live data. No new slug/alias table.
2. Agent-tool argument resolution for box/teammate names and message/history sequences, with existing authorization/routing; descriptions and fixtures. No parallel legacy signatures.
3. Narrow result projections and message rendering in tools/inbox, native image path, stored-decision label lookup and due-event snapshot handling. Public API/event envelopes and checkpoint/history ordering remain unchanged.
4. Focused tests for reply resolution scoped to recipient, mixed batched input/order/no duplicate events, grant-state rendering, output continuation, slug uniqueness and lifecycle directory scope. Strict Python typing/Pyright; update affected API fixtures without extending unrelated ingestion work.
5. Publish matching Langfuse prompts and compare a fresh journey's business correctness, generations, context use, tool errors and compactions. Measure actual token/cost data when available; do not equate character savings to guaranteed token savings or advertise a fixed performance percentage.

The proposal itself changed no running state; its approved implementation and verification are recorded in plan.md section 11.
