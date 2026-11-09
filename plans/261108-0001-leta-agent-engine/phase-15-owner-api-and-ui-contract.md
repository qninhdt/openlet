---
title: "Phase 15: Owner APIs and typed UI contracts"
status: completed
priority: P1
dependencies: [4, 8, 11, 12, 13, 14]
---

# Phase 15: Owner APIs and typed UI contracts

## Overview

Expose the completed engine through authenticated product APIs with predictable read models for chat, inbox, graph canvas, calendar and human requests. Keep owner chat simple while preserving the distinction between a delivered message and the agent's working transcript. This phase implements no browser interface.

Read [design contract](design-contract.md), [tool contracts](tool-contracts.md), Phase 3 schema and Phases 11–14 domain services. Domain mutations remain owned by those services/Workflows; HTTP routes are adapters.

## Current evidence and proposed files

- Existing Python `openlet.identity.authenticate_gateway` validates gateway token and exactly one verified user/subject header after phase02 migration; reuse it rather than parse unverified JWTs in Leta. `openlet.httpapi.problem_json` and `openlet.errors` own safe problem responses.
- Gateway routing lives in `infra/config/envoy.template.json`, rendered by `scripts/bootstrap/configure.py`. Phase 18 owns actual routing/wiring; this phase defines required route coverage and tests the API in process.
- Public manual contracts live at `packages/contracts/public/openapi.yaml`; generated LetFS OpenAPI remains machine-owned. Add Leta paths to the manual owning contract, not generated files.
- Proposed files: `apps/leta/src/leta/api.py`, `apps/leta/src/leta/http/{agents,messages,boxes,requests,schedules,history}.py` only where route groups need separate modules; avoid a class/file per endpoint. Add `apps/leta/tests/test_http.py` and `tests/integration/test_read_models.py`.

## Public route contract

All Leta paths below are new. IDs are UUIDs; datetimes are RFC3339. Authentication derives caller user from trusted gateway headers; bodies cannot supply actor/owner/grantee authority. Lists use bounded keyset cursor pagination and explicit filters, except the complete bounded calendar occurrence query, which has no public pagination.

| Method/path | Behavior and authority |
| --- | --- |
| GET /v1/leta-models | Server-supported model IDs, reasoning_effort values and useful context metadata; no provider credentials. |
| POST /v1/letas | Owner creates own Leta in workspace_id with name, description, system_prompt, model_id and reasoning_effort. |
| GET /v1/letas | Caller-owned Letas, optional workspace/status filters. |
| GET/PATCH/DELETE /v1/letas/{id} | Inspect; edit allowed name/description/system_prompt/model_id/reasoning_effort; archive rather than hard delete. |
| POST /v1/letas/{id}/pause or /resume | Control root and descendants through lifecycle Workflow. |
| GET /v1/letas/{id}/agents | Root/Leti roster and persisted status, used by canvas and subscriptions. |
| PATCH /v1/letas/{id}/agents/{agent_id} | Owner sets/resets Leti model_id/reasoning_effort overrides; null restores inheritance. No name, membership or graph mutation. |
| GET /v1/letas/{id}/boxes | Paginated box summaries. |
| POST /v1/letas/{id}/boxes | Same atomic box specification as create_box; owner may manage canvas through API. |
| GET/DELETE /v1/letas/{id}/boxes/{box_id} | Graph/detail or whole-box deletion; no individual Leti mutation. |
| POST /v1/letas/{id}/messages | Owner input to root Leta only; `{id,content,in_reply_to?}` with client-stable message UUID. |
| GET /v1/letas/{id}/messages | Actual owner↔Leta chat, not every assistant note/input/tool item. |
| GET /v1/letas/{id}/messages/{message_id} | Retry/admission lookup bound to this owner conversation. |
| GET /v1/letas/{id}/inbox | Owner inspection of root or selected owned agent incoming records. |
| GET /v1/letas/{id}/history | Typed transcript page for root or one selected owned agent, optional run filter; returns public entries and message refs. |
| GET /v1/letas/{id}/history/{entry_id} | Bounded detail for a public transcript entry. |
| GET /v1/letas/{id}/runs/{run_id} | PG run state/result/error and stable root stream location; no Temporal history payload. |
| GET /v1/letas/{id}/human-requests | Owner's managed Leta/box request inspection, not approval authority for other resources. |
| GET /v1/human-requests | Requests addressed to caller, including foreign resource approvals. |
| GET /v1/human-requests/{request_id} | Recipient-safe card; requester/owner use their management view. |
| POST /v1/human-requests/{request_id}/response | Submit ask answers or accept/deny; authorize exact recipient. |
| POST /v1/letas/{id}/human-requests/{request_id}/cancel | Owner cancellation of pending owned request, not reversal of accepted grant. |
| GET/POST /v1/letas/{id}/schedules | List/create definitions with owned target filtering. |
| GET/PATCH/DELETE /v1/letas/{id}/schedules/{schedule_id} | Inspect/update/delete; PATCH paused implements pause/resume. |
| GET /v1/letas/{id}/schedule-occurrences | Bounded calendar preview across authorized selected schedules. |
| GET /v1/letas/{id}/events | SSE subscription, implemented in Phase 16. |

Workspace owns grant revoke and received-scope cleanup during Leta deletion. No independent Leta leave/transfer API or tool is exposed. Its new accessible-scope view is the single source for mount discovery. Do not duplicate grant mutation endpoints in Leta.

Workspace phase04 separately owns GET /v1/workspaces/{workspace_id}/scopes for the authenticated user or an authorized leta_id inspection. No agent-only scope-list API. The events endpoint is stable for the Leta, including future child runs; its envelope is {leta_id,agent_id,run_id,event} with nullable run_id for domain changes outside a run.

## Implementation steps

1. Implement the application lifespan using process-owned PG pool, Redis client, Temporal Client, authz and typed Openlet clients. API owns no LLM runner or background workflow polling loop. Validate configuration/startup dependencies and close all clients at shutdown.
2. Authenticate every route before selecting root/agent IDs. Check current workspace membership and leta.read/manage against the canonical root resource. No post-owner-departure bypass. Workspace create permission applies at creation, not a blanket right to read everyone's agents. Creator visibility over activity does not grant direct file access to foreign personal scopes received by Leta.
3. Declare strict request/response models, reject unknown mutation fields, and distinguish omitted/null fields. PATCH may not change ownership, root workspace, kind, Leti name or graph. Owner-only Leti model_id/reasoning_effort edits use the lifecycle configuration path, with null restoring inherited values; they do not introduce an agent update_agent tool. Validate the effective model_id/reasoning_effort pair from catalog before submitting a command, including descendants affected by a root model change; reject incompatible inheritance with a useful list rather than silently selecting another mode. Runner applies edits at its next safe boundary without erasing context.
4. Commands that start multi-step lifecycle operations use a stable Idempotency-Key; the accepted request holds the same allocated ID and payload across timeout/retry. Use the ordinary Leta-local idempotency_keys table for HTTP allocation/hash and completion expiry, following existing Workspace mechanics; retain downstream keys through internal clients; do not create a generic operation object. Return command/resource state when complete; an RPC timeout returns an explicit unknown/pending result and retry instructions using the same key. Never claim atomic cross-service creation.
5. Message POST uses the client-stable UUID as receive Update ID and domain message ID. Return persisted acknowledgment only after receive completion, not Temporal acceptance alone. During worker outage, retain pending/unknown semantics and support lookup/retry; never show a PG inbox row that does not exist.
6. Read queries use PostgreSQL domain tables, typed activity payloads and refs. Do not reconstruct canvas/inbox/history from Workflow histories or checkpoint snapshots. Batch agent/run/HITL/schedule summaries to avoid N+1 canvas queries. A canvas response includes immutable agents/prompts/representative/edges and pending counts, but does not imply unsupported graph edit operations.
7. Define one timeline DTO shared by historical and live events: ActivityEntry `{id,agent_id,run_id?,seq,kind,created_at,message_id?,tool_call_id?,data}` from Phase 11 plus explicitly typed domain-message/request/schedule references. Canonical transcript kinds are inbox_input, assistant, tool_call, tool_result, final_note and compaction. Owner/received chat is projected from messages with explicit sender/recipient, not a second transcript kind enum. Route projection follows these owning discriminated unions rather than guessing from role/content.
8. Input component uses grouped digest/full fields from the saved model input, source labels/refs, counts, previews and expandable details. Raw runtime HumanMessage serialization is available only as intentional transcript detail if needed, not the default chat bubble. Runtime role=user never establishes owner identity. A referenced owner message renders as one owner bubble plus its input reference, not a duplicate owner bubble.
9. Compaction component exposes summary entry identity and exact persisted summary. Tool components expose public call name/args/result with truncation/detail references; final text is a note. Provider hidden reasoning is neither stored nor returned. Treat agent-generated Markdown/HTML as untrusted renderable content in the contract; no executable markup.
10. Resource-owner request DTO excludes unrelated history/workspace files. Show requester agent/box, Leta and its owner, resource/role/reason, deadline, decision and grant outcome, plus disclosure that Leta/Leti receive access and owner can see resulting activity. Ask DTO supports one form with multiple questions, empty selections/notes and text-only free text. Validate response on server rather than trusting UI form behavior.
11. Read history by per-agent sequence keyset and hydrate full body/args/results only for selected items. Chat messages keep their owning `(created_at,id)` cursor. Conversation projection may return independent message/activity cursors and merge for presentation by timestamp/identity; it must not pretend a timestamp is a global committed cursor across all agents. Canvas selects an agent to inspect; one stable SSE stream covers the root and all descendants, with no per-agent subscription registry. Return incomplete/truncated markers; never hide a terminal error as an empty list. IDs in URLs are checked against root ownership to prevent cross-Leta traversal.
12. Update OpenAPI examples and contract tests for all route bodies, safe errors, pending acknowledgment, nullable values and typed timeline payloads. Keep tests for existing Account/Workspace/LetFS API behavior unchanged unless their accepted contract intentionally changed.

## Execution evidence

Authenticated adapters, bounded SQL read models and strict DTOs now cover every
non-SSE route below. See [phase15 execution](reports/phase-15-execution.md) for
current tests and limitations. HTTP key completion uses the ordinary existing
Workspace expiry pattern, including completed retry suppression across Temporal
run rotation; no product operation/receipt registry is introduced. The API
idempotency table is infrastructure alongside phase03's eight product tables.

## Requirements

- [x] Owner APIs cover lifecycle, inbox/chat, canvas, transcript, requests and schedule preview.
- [x] Resource owners can view/respond only to addressed requests without gaining Leta history access.
- [x] Historical/live typed payloads support custom inbox/compaction components without text parsing.
- [x] Mutation retries and timeout responses use stable resource/message identities.

## Verification and acceptance

Run `uv run --locked --package leta pytest apps/leta/tests/test_http.py -q`, then read-model integration tests. Run `pnpm contracts:check` after updating the manual OpenAPI owner and generator consumers. Real gateway coverage is Phase 18.

- Missing/duplicate/spoofed trusted headers and invalid caller identity fail before data access.
- Owner A cannot read/manage B's Leta by changing any root/agent/box/run/message/entry/request ID.
- Resource owner B can accept their personal-scope request from A's Leta; A cannot accept it; B cannot read A's full transcript.
- A Leti ask is addressed to root owner and never appears as direct Leti chat permission.
- Runtime input card, owner bubble, actual send, final note, tool result and compaction remain distinct after reload. Original owner text is not duplicated.
- Paused/archived read models preserve history and explicit state. Read models use PG, not Temporal history or Redis data; deployment readiness still requires Redis.
- Same message UUID/key retries after commit/response loss produce one resource; mismatched payload conflicts.
- Pagination remains stable with new inserts and rejects a cursor reused against a different root/filter.

## Risks and rollback

The API is a trust boundary: resource-owner request access must not accidentally reuse owner-Leta authorization. Large transcript results require pagination/redaction limits, not silent data loss. Rollback stops new API admission and retains committed records; old APIs cannot safely operate against changed domain contracts without coordinated version rollback. No persistent data changes occur during planning.
