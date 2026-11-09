# Agent tool catalog and argument contracts

This is the final MVP tool surface, not a list of every backend RPC or VFS hook. Runtime injects authenticated agent/root/workspace identities and credentials. The model cannot choose actor, owner, grantee or approver. Every tool uses the same domain service as API/Workflow adapters and enforces current lifecycle/routing/permission.

Refs are UUID strings or exact names in the caller's allowed roster. Resolve ambiguity with a useful error and candidate IDs; never globally search another Leta's names. Parent/owner/self aliases are runtime-defined roster entries, not authority supplied by text. All pagination returns next_cursor and explicit truncation; bound limits in code/config.

## Workspace and history — Leta and Leti

| Tool | Arguments | Behavior |
| --- | --- | --- |
| get_workspace | none | Current workspace, identity, effective model_id/reasoning_effort, permissions, mounts and allowed messaging roster. Refresh the mount view at a safe boundary. |
| list_workspace_members | limit:int=20, cursor?:string | Human active members available for personal-scope requests; user ID/name, no foreign file bodies or new chat routes. |
| search_history | query?:string, limit:int=20, cursor?:string | Current agent's public LLM transcript, including input/tool args/results/final notes. Without query, recent entries. Not a pending-inbox search. |
| read_history | entry_id:string, start_line:int=1, max_lines:int=200 | Public entry detail with line paging/truncation. No hidden reasoning. |

History scope is the current agent. Owner APIs can inspect descendants; do not silently make a Leti history tool search every peer/root transcript. SQL substring matching is sufficient initially for history lookup; no new vector index/memory service.

## Messaging and inbox

| Tool | Arguments | Availability and behavior |
| --- | --- | --- |
| send_message | to:Ref, content:string, in_reply_to?:string | Both. Leta→owner/box; Leti→adjacent peer; representative→parent under box identity. Returns after recipient message/inbox commit, not recipient completion. |
| list_inbox | from?:Ref, unread_only:bool=true, limit:int=20, cursor?:string | Leta only. Grouped conversation/source/count/preview/address; no entire inbox injection. |
| read_inbox | conversation_id:string, unread_only:bool=true, limit:int=20, cursor?:string | Leta only. Returns details and marks only returned items read. |

conversation_id is the opaque projection of conversation_key, not a new conversation entity. in_reply_to must identify an allowed prior message with compatible route. Nonreplyable notification input cannot be replied to merely because it has source.label. Leti receives pending contents automatically and has no inbox tools.

send_message is the only tool delivering actual messages. There is no send_box or implicit final-text forwarding. A replyable source and the current roster determine the address; source strings/labels do not grant routes.

## Boxes — Leta only

| Tool | Arguments | Behavior |
| --- | --- | --- |
| list_boxes | limit:int=20, cursor?:string | ID/name/description/lifecycle and bounded counts. |
| get_box | box:Ref | Immutable graph, prompts, roster/representative, derived home path, persisted run/HITL/schedule summaries. |
| create_box | name:string, description:string, letis:LetiSpec[], edges:[string,string][], representative:string | Atomic complete graph configuration and lifecycle start; does not send work. |
| delete_box | box:Ref | Deletes whole box runtime, cancels future sources, trashes home after runners stop; retains history. |

LetiSpec is `{name, description, system_prompt}`. New Leti inherit Leta's model_id/reasoning_effort; only the owner configuration API may set/reset overrides. The agent tool does not choose model_id/reasoning_effort. Names are immutable and unique across Leta; box names are unique within Leta. Edges and representative reference Leti names in this creation payload. Validate nonempty graph, no unknown endpoints/self-edges, canonical duplicate edges and derived slug collision. No slug field or edit_graph/update_agent tool.

## HITL — Leta and Leti

| Tool | Arguments | Behavior |
| --- | --- | --- |
| ask_user | title:string, questions:Question[], timeout_seconds?:int | Multi-question form addressed to Leta creator. Returns pending immediately. |
| request_access | resource:{type:"personal_scope",user_id:string}, role:"viewer"\|"editor"="viewer", reason:string, timeout_seconds?:int | Request personal scope of human active in same workspace. Runtime derives resource owner and grants to the root Leta resource. |
| list_hitl | status?:pending/resolved/cancelled/expired, box?:Ref, limit:int=20, cursor?:string | Default current-agent requests. Leta may select owned box; Leti only its own. |
| get_hitl | request_id:string | Questions/resource/deadline, answer/decision and actual grant outcome. Leta may inspect descendants, Leti only its own. |
| cancel_hitl | request_id:string, reason?:string | Pending only; same management bounds. Does not undo accepted grants. |

```text
Question = {
  id: string,
  text: string,
  type: single_choice | multiple_choice | text,
  options?: [{id: string, label: string}]
}
```

Question IDs are unique across the form; option IDs are unique within the question. Choice questions require nonempty options; text questions have no options. No Other option. One form can mix all three kinds.

Owner answers map every question ID to:

- Single choice: `{option_id: null | option-id, note: string}`.
- Multiple choice: `{option_ids: option-id[], note: string}`; empty array valid, duplicates invalid.
- Text: `{text: string}` only.

Notes are optional at ingress and normalize to empty string; selections may be empty. Submitting the form is distinct from leaving it pending. Agent has no respond_as_owner tool. Result/timeout enters the original requester's inbox. Ask always targets Leta creator; resource approval always targets resource owner. If already granted sufficient rights, request_access returns already_granted/current mount instead of creating another pending request.

No dangerous-tool approval policy, test_approval, request_approval or generic arbitrary-action executor. Accept changes access only; it does not replay a held filesystem/tool action.

## Schedules — Leta and Leti

| Tool | Arguments | Behavior |
| --- | --- | --- |
| create_schedule | title:string, content:string, spec:ScheduleSpec, target:Ref="self", end_at?:datetime | Leta targets self/owned box representative; Leti targets self. Relative input normalizes once. |
| list_schedules | box?:Ref, limit:int=20, cursor?:string | Default current agent; Leta may inspect owned box schedules. |
| get_schedule | schedule_id:string | Definition/state plus bounded upcoming preview when available. |
| update_schedule | schedule_id:string, title?:string, content?:string, spec?:ScheduleSpec, end_at?:datetime\|null, paused?:bool | Omitted field unchanged; null end_at removes recurring cutoff; paused controls pause/resume. No target reassignment. |
| delete_schedule | schedule_id:string | Stops future input sources; does not retract delivered messages. |

```text
ScheduleSpec =
  {type:"at", at: RFC3339 timestamp}
  | {type:"at", after_seconds: positive integer}
  | {type:"interval", every_seconds: positive integer, anchor_at?: timestamp}
  | {type:"calendar", timezone: IANA name, fields: CalendarFields}
CalendarFields = {
  second?, minute?, hour?, day_of_month?, month?, day_of_week?, year?
}
field = "*" | [integer | {start: integer, end?: integer, step?: positive integer}]
```

at has exactly one of at/after_seconds. Calendar defaults/ranges follow the pinned Temporal SDK and are expanded in API output. See [Phase 14](phase-14-temporal-schedules-calendar.md) for compilation, one-shot state, anchoring, BUFFER_ONE and preview limits. No hardcoded daily/weekly scheduler variants and no separate heartbeat/alarm service.

## Filesystem, compute and semantic search — Leta and Leti

| Tool | Arguments | Behavior |
| --- | --- | --- |
| list_files | path:string="~", depth:int=1, limit:int=100, cursor?:string | Metadata/tree under allowed mounts, no body download to build a listing. |
| read_file | path:string, start_line:int=1, max_lines:int=200 | Text selection; blob metadata plus artifact tree; image artifact/preview yields multimodal output. Line selector applies only to text. |
| write_file | path:string, content:string, overwrite:bool=false | Create/replace inline UTF-8 text under current permission/precondition; never blob payload or readonly artifact mutation. |
| edit_file | path:string, old_text:string, new_text:string, replace_all:bool=false | Exact text edit; default exactly one match, errors for no/ambiguous matches. |
| run_shell | command:string, cwd:string="~", timeout_seconds:int=30 | Mirage virtual shell and supported commands/flags; no host Bash/subprocess. rm trashes, never purges. |
| run_python | code:string, timeout_seconds:int=30 | Monty through Mirage using the same view; no host interpreter/ambient network/packages. |
| semantic_search | query:string, paths?:string[], limit:int=10 | Default all current readable normal roots; optional paths narrow them. Reauthorize/hydrate hits and map to readable artifact paths. |

Every direct file tool uses Mirage session/VFS dispatch, not a bypass to LetFS. Adapter hooks use native LetFS APIs for range/line/tree/search/mutations; do not expose one LLM tool per backend hook. mkdir/copy/move/trash/append/head/tail/find/grep/rg use run_shell and actual supported Mirage behavior.

Native text read/write/search use bounded unary RPCs. Mirage may supply an iterator for redirected writes; the adapter consumes it once under the existing inline limit before one native mutation. tail -f uses the follow hook's unary range polling at the requested interval and remains bounded by command timeout/cancellation. Neither feature adds an LLM tool, streaming RPC or backend watcher.

Normal mounts remain ~/ /shared/ /users/<id>/. Artifacts are ordinary file/directory nodes with parent_id under the source file, not a separate ID type or namespace. Keep paths such as `/shared/docs/report.pdf/report.md` and `/shared/@<original-file-id>/report.md`, including nested artifact directories. Blob metadata returns that actual tree with readable source-relative paths; the model need not know child node IDs. Preserve native readonly/root/permission checks. No /artifacts mounts or synthetic preview directories. read_file can request a permitted image preview/artifact without exposing original blob bytes to shell/Monty. The named/source-ID-prefixed traversal must be tested with the pinned Mirage adapter; source inspection alone is not a passed integration test.

Do not index/read raw blob bytes through agent credentials. Images come from a valid artifact/preview and current authorization. semantic_search is not grep and cannot supply incomplete top-k results to files_containing. Unsupported Mirage behavior remains explicit; no parser fork.

## Owner operations outside the tool catalog

Owner creates/configures/pauses/resumes/archives Leta, can set/reset Leti model_id/reasoning_effort overrides, views all owned resources and responds to addressed requests through product APIs. Resource owners respond through their addressed-request API. Neither becomes an agent tool for impersonating a human.

Limits for output size, concurrency, streaming and model context are operational safeguards. Do not turn them into an unapproved product model-call/task budget or silently drop pending inputs.
