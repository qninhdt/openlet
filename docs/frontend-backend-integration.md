# Frontend/backend integration — 2026-11-17

The authenticated application uses the gateway, Platform, Leta and LetFS APIs. Agent transcripts, requests, Box graphs, seeded storage, IndexedDB persistence and simulated authenticated mutations have been removed. Browser-local drafts, theme and display preferences remain local. The independently developed public `/app-preview` demonstration is isolated from authenticated routes and live APIs.

## Implemented changes

- Vite reads only the root `.env` Clerk publishable key, with a `VITE_CLERK_PUBLISHABLE_KEY` override, and proxies `/v1` to `127.0.0.1:8080`. Server secrets remain in the backend. Production still needs a same-origin gateway route or explicit API/CORS configuration.
- API and SSE authentication use the existing Clerk `openlet` JWT template. Its nested user claim matches the gateway. Identity initialization calls `/v1/me`, onboards only on 404, then refreshes the Clerk user and template token.
- Activity file snapshots carry real storage/node references from metadata already returned by file operations. Text/image reads, text writes/edits, listing and semantic search do not add RPCs to obtain these references. Clicking a reference uses the existing authorized LetFS flow. Legacy text snapshots remain readable.
- File choices bind cached storage roots into their own adapter before listing/searching. Model settings filter the catalog's nullable effort values and retain Default effort.
- Conversation storage creation forwards the LetFS consistency token to the browser. Authenticated requests retain it per Clerk user in session storage and send it on subsequent calls, including through Leta to LetFS. The file-copy path also retains the new storage token. This fixes the first-upload permission race without a new query, retry or sleep.
- The Uploads panel stays above the composer so it does not cover Send on desktop.
- Private-file copy confirmation retains the original mention label and serialized selection, replacing the typed mention with the authorized conversation reference. No query was added.
- Chat rendering tolerates rows removed by a paginated refresh while the assistant-ui runtime reconciles its previous snapshot. This fixes the reproduced crash after sending into a full chat page, without another query or a backend change.
- Empty workspaces expose General and Appearance settings before their first agent exists, including persisted preferences and responsive navigation.
- The development R2 CORS rule now includes localhost and 127.0.0.1 on ports 5173, 5174 and 5175. Existing origins, methods, allowed/exposed headers and max age were preserved; configuration was read back and compared after applying.

The backend changes reuse the existing schema, permissions and service operations. No database migration or additional access grant was introduced.

## Verification

The local `openlet-integration` Compose stack runs PostgreSQL, Temporal, SpiceDB, Redis, Qdrant, LiteLLM, Platform, LetFS, ingest workers and Leta with the configured real Clerk, LLM and development R2 resources. The gateway is at port 8080. Browser checks have used Vite at ports 3000, 5174 and 5175; the web test config starts or reuses its selected local origin.

**Latest full run:** `pnpm test:web` passed all **37 tests** in 3.9 minutes at `http://127.0.0.1:3000`: 13 public/adapter checks and 24 authenticated checks. Web/E2E type checks, lint (with existing warnings), production build, formatting and `git diff --check` also passed.

Passed browser checks with real services:

- A newly provisioned agent's first conversation upload sends the exact creation revision. Send remains unobstructed. The uploaded text can be edited, saved and reloaded in Storage.
- Real LLM/tool execution reads an attached text file and delivers a reply. Chat survives reload; file references open from both Chat and Activity. Adding/removing a reaction persists in the backend; Reply/Cancel updates the composer.
- A valid browser-generated PNG uploads to R2, is read by the model with `file_read`, opens from Activity and Storage, and downloads byte-for-byte unchanged.
- A real HITL question is answered in the UI. Schedule title edits and pause persist. A real Box graph displays its children and edges after reload.
- Workspace creation, General/Appearance settings before an agent exists, preference persistence, Storage upload/edit/reload, folder creation, move, rename, copy, Trash/Restore and provisioning the first agent have passed. Settings was visually reviewed at 390 and 1440 px; its mobile section navigation uses a horizontal row.
- A Personal-storage HITL approval grants the new test agent access; revoking that grant makes the same file reference return 403. The test uses its own newly created workspace.
- Authenticated routes, Vietnamese composer drafts across history navigation, Storage and reload pass at 390, 721 and 1440 px without page errors or page overflow.
- Model/Default effort settings save and survive reload. A private-file mention correctly returns 403, offers a conversation copy, replaces the original mention and reads back the copied content with the returned consistency token.
- Conversation files can be selected and dragged into the composer in Grid, Mosaic and List without re-uploading. Custom labels survive switching tabs. A deliberately failed HTTP upload retains the file and retries against real LetFS.
- Composer selection, fast typing, Vietnamese text and IME Enter work on mobile and desktop. IME Enter does not submit a chat request. A dedicated paused test agent reproduces full-page message eviction with 21 real messages, then verifies sending, reload and loading older history; this regression does not use the model.
- Sidebar agent creation, nested folders, assignments and pin/unpin persist in the backend. Resizing keeps the header aligned and supports keyboard expansion. Canonical unknown resources remain unavailable; legacy links resolve the supplied real IDs.
- The editor preserves UTF-8 BOM/CRLF bytes on save/download, CSV quoted and multiline cells, responsive drafts and discard confirmation. A real concurrent version update returns 409 without replacing the other writer's content or losing the local draft. Large previews stay read-only and invalid UTF-8 is not editable.

Other checks: 17 tool/filesystem/auth Python tests passed; the SQL chat suite previously passed 20 tests with one Redis-dependent skip. Nine adapter/stream/file tests passed. Web and E2E TypeScript, Python type checks, Ruff, production build and whitespace checks passed. Web lint completes with existing warnings. Built assets were scanned against 18 configured server secrets; none were found.

## Conversation runtime fixes

- Uploaded originals are files in the agent filesystem. Shell `cp`/`mv` use native LetFS transfer operations; extracted artifacts remain accessible through `file_list`/`file_read`. The Redis VFS namespace was advanced so stale directory classifications are not reused.
- Root inbox messages of at most 120 original characters arrive in full, preserving whitespace, and are marked read in one batched update. Longer messages remain explicit truncated notifications until `inbox_read` obtains the original. All ordinary messages in a delivery batch remain visible; the latest message no longer suppresses earlier requests.
- Inbox text carries an explicit `to` address from the query; renderers require this contract without a legacy routing fallback. Prompts explain that `message=N` selects a conversation, unread messages are the default, and reread history is not new work. Ordinary sends omit `in_reply_to`; quoting is reserved for a meaningful reference.
- Semantic search excerpts allow 1024 characters per hit within the existing total output budget.
- Langfuse root/Leti version 9 was published with the new common prompt and existing model configurations preserved. The local Leta worker/API were rebuilt and restarted.

Validation: **65 Python tests passed**, with one Redis-dependent SQL test skipped; changed Python files passed Ruff and type checking. Real model checks confirmed that a short input sent once without `inbox_read` or quoting, while a long input called `inbox_read` before sending once without quoting. Actual shell copy across storages, move within one storage and move across storages preserved the JPEG bytes, checked by SHA-256 after downloading from R2. The affected original JPEG was recovered from Trash and moved into Personal as requested; the erroneous empty folder and temporary test copy remain recoverable in Trash. The existing 37-test browser baseline above predates these runtime fixes and was not rerun for them.

## Browser test migration

The former authenticated demo suites were replaced with real-service browser tests in `e2e/tests/live-web`. `pnpm test:web` now runs both the public/adapter project and the authenticated project, and requires the Clerk state and real development resource IDs below. Missing credentials fail with an explicit setup error; the authenticated project is not silently skipped.

| Former test area                   | Current real-service coverage                                                                                                        |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Chat, conversation files, activity | Real model/tool reply, history, reactions, Reply/Cancel, Activity references, uploads, retry, copy, labels and drags                 |
| Sidebar, organization, overview    | API-backed creation/settings, model/default effort, nested folders, assignments, pins, resizing                                      |
| Shell and routing                  | Mobile/tablet/desktop routes, Vietnamese drafts/history, IME, unknown resources, legacy URLs, empty-workspace settings               |
| Storage and editor                 | Upload/download, save/reload, folders, move/rename/copy, Trash/Restore, encoding, CSV, drafts, version conflicts, read-only previews |
| Box and HITL                       | Real graph/edges, questions, schedule edit/pause, access approval and revocation                                                     |

Assertions tied to static demo transcripts, simulated work states and IndexedDB write failures were removed with that implementation. The version-conflict check now uses an actual second LetFS write. Pure adapter/stream/file transaction tests and the isolated public playground tests remain in `e2e/tests/ui`. This migration does not preserve every former visual assertion: detailed avatar animation, scroll anchoring, marquee/OS folder drops, XLSX sheet switching and every dirty-workspace navigation permutation still need dedicated live coverage.

## Running live browser checks

`pnpm test:web` starts/reuses Vite and runs all web projects. It requires an existing signed-in Clerk browser state and real development workspace/agent IDs:

```sh
OPENLET_WEB_AUTH_STATE=/absolute/path/to/private-browser-state.json \
OPENLET_WEB_WORKSPACE=<workspace-uuid> \
OPENLET_WEB_AGENT=<agent-uuid> \
pnpm test:web
```

The gateway and backend stack must already be running. Default Vite origin is `http://127.0.0.1:5174`; `OPENLET_WEB_URL` can select another local origin/port. The public/adapter subset runs without signed-in state via `pnpm --dir e2e test:web:public`; the authenticated subset is `pnpm --dir e2e test:web:live`. The standalone `playwright.live-web.config.ts` remains available when Vite is managed separately.

The authenticated project creates development workspaces, agents, files, questions, schedules and Box graphs, and uses paid model calls. It retains these resources for inspection. Keep the browser-state file private and outside version control. One upload-retry test injects an HTTP 503; the subsequent retry and all file data use real LetFS.

## Coverage still outstanding

This is not a claim of 100% end-to-end coverage. The remaining visual and interaction coverage is listed in the migration section above; production application fixtures have not been restored to satisfy tests.

Membership/invitation journeys, revocation of user membership and active SSE access, multipart uploads, all media formats, production hosting and physical-device behavior have not been verified end to end. Optional Alloy is absent from the local stack, so telemetry export errors remain. No production deployment, account deletion or destructive cleanup was performed.
