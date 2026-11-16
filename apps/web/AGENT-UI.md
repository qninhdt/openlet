# Agent UI preview

Mode: Operate. Extend the existing OpenBot-derived shell; preserve its semantic shadcn tokens and geometry. This is a local, synthetic conversation demo, not a connected agent service.

## Direction and quality bar

Keep the content-sized message bubbles, editor-shaped tabs, 280px agent list (88px compact), 38px header and 360px context panel. Use actual provider marks and the shared Storage viewer/editor. Action results fit their contents up to 520px; questions/access prompts fit up to 540px; code and diffs use OpenBot's wide-message formula, `min(100%, max(720px, 70%), 1200px)`. A generic fixed width for every tool is inappropriate.

The main header has two editor-shaped tabs: Agent conversation and Overview. Overview is one page with agent identity/model/status and a unified activity list mixing messages, questions/answers, storage access requests and schedules. All/Needs you, search and a type filter refine the same list. Expanding a message never changes the agent's read state. Unread messages have a brand-token blue dot and stronger title; read messages use a quiet double check, with tooltip and accessible descriptions. Pending counts include only questions and requests addressed to the current demo user.

Settings opens a modal from Overview or the sidebar context menu. Name, description, model/effort and instructions are staged together; Cancel discards them and Save commits them locally. There is no settings side-panel tab. The right panel holds file tabs only; closing the last file closes the panel, and switching to an agent without open files hides it. The shared viewer/editor is reused from either main tab. Overview schedule editing and pause, agent pause, decisions and main-tab selection are local per-agent state. Question/request renderers and submitted decisions are shared with the conversation. Overview items are illustrative fixtures, not a backend aggregate or evidence of cross-user inbox access.

Bloub frames are tied to their engine identity so changing agents updates shape as well as color, including Storage breadcrumbs. User bubbles take their background and contrasting ink from the same shared agent palette. Expanded activity rows, tool steps and tool groups have 12px top padding between trigger and content; they retain natural height without inner vertical scrolling.

Each tool exposes its own meaningful structure rather than a title/subtitle template. File listings have type icons and sizes; reads show a historical snapshot; writes expose the created file; edits show added/removed lines; search uses bordered source headers and indented, italic excerpts. Inbox reads use sender avatars and message bubbles. Redundant delivery/representative captions, file-write summaries/line counts and the communication-edge label are omitted. Schedules show date/time, timezone, paused/active/deleted states and upcoming runs; updates retain the previous timing. History uses dated entries; members use a role table; teams expose the representative, communication edges and shared directory; human requests expose the requested scope and decision state.

The conversation owns vertical scrolling. Tool results and code output have no height cap or nested vertical scrolling. Wide tables and code use horizontal scrolling inside their bounded container. Execute has a terminal with a command and output; it deliberately has no cwd/exit-code metadata row, per user direction. Keyboard focus, collapse/expand, narrow layouts and long content must remain usable.

## Demo coverage

All 27 registered tools appear across four multi-turn scenarios in `src/components/agents/agent-demo.ts`:

- Atlas: historical decisions, workspace/member context, review team creation and cleanup, inbox delegation, plan/budget artifacts, single choice, multiple choice and free-text questions.
- Forge: directory listing, TypeScript read/edit, Python validation script, failed budget check, exact CSV edit, successful recheck and final attachments.
- Scout: cited search, no-result search, research read, a read-only access request, request status/list/cancellation and a revised announcement.
- Pulse: existing schedules, a paused briefing, weekly rescheduling, deletion, a one-time reminder, forecasts and empty history.

Tool groups/results start expanded so the demo can be inspected; each remains collapsible. A failed step is identified in the group summary. Attachments occur only on the messages that produced them. The shared viewer supports Markdown/CSV preview and source editing, highlighted code, local saves and downloads.

Answers, approvals, settings, file edits and sent messages stay in the mounted preview session. Pin order persists per workspace in localStorage. Reload resets the synthetic conversations and agent files. There is no live execution, schedule delivery, storage authorization or agent response generation. Tool presentation types are demo data; connect an adapter for actual backend outputs when integrating the API.

## Reference and verification

Reference source: nightly-labs/openbot, commit `e50025767311cad46c9fd67d7fa0daed81c4d370`; conversation AgentSteps, ChatActionCard, RoutineScheduleCard, QuestionPromptBubble and message styles. The explicit user request to remove height caps takes precedence over the upstream scrolling viewport.

Browser checks: `pnpm test:web`. Visual evidence: `.impeccable/review/agent-tools/` at 390, 721, 1344 and 1860px, including error/empty states, questions, request decisions and shared file tabs. Existing `.impeccable/design.json` is preserved; its blank-content description predates the Agent preview.

Latest verification: 50 browser tests passed (43.3s), including six Overview cases covering mixed activity, read-state preservation, shared question/request decisions, schedule editing/pause/state retention, settings commit/cancel and 390/721/1344px layouts. Production build/typecheck and lint completed (existing warnings remain). Overview visual evidence is in `.impeccable/review/agent-overview/`, at 390, 721, 1344 and 1860px, including modal, questions, requests, schedules and file panels. Trigger-to-content spacing was measured at 12px on phone and desktop; no document overflow or browser page errors appeared in that pass. The earlier independent Impeccable **ship** review covered the previous conversation/tool renderer scope. No design-system replacement, dependency addition or global CSS changes were needed for Overview.
