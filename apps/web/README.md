# Openlet web

Frontend workspace for the public website, sign-in and the application.

The navigation follows OpenBot's UI structure, with Server mapped to Workspace. `/app` redirects to the selected workspace; application pages use nested routes.

## Stack

- React + TypeScript (strict), built with Vite.
- Tailwind CSS 4 with the Vite plugin.
- shadcn/ui: Radix primitives, Nova style, neutral tokens, Lucide icons and a self-hosted Geist font.
- TanStack Router for public pages and nested workspace/agent/storage/Box/settings routes.
- TanStack Query, with one `QueryClientProvider` at the application root.
- `@assistant-ui/react` provides chat/activity runtimes and custom tool renderers; the composer ports OpenBot’s native contenteditable editor.

## Commands

Run from the repository root:

```sh
pnpm install --frozen-lockfile
pnpm dev
pnpm typecheck
pnpm lint
pnpm build
pnpm test:web
pnpm preview
```

The web config reads only `CLERK_PUBLISHABLE_KEY` from the repository root `.env`; `VITE_CLERK_PUBLISHABLE_KEY` in `apps/web/.env.local` or the process environment can override it. Backend secrets remain server-side. Vite proxies `/v1` to `http://127.0.0.1:8080` in development. For production, route `/v1` to the gateway at the web origin, or set `VITE_API_BASE_URL` and configure the gateway's CORS policy.

`pnpm dev` serves the app at `http://localhost:5173`. `make check-js` runs formatting, type checks, lint and the production build, including this workspace.

The full `pnpm test:web` suite includes real Clerk/gateway/LLM/R2 browser checks and requires signed-in Clerk state plus development workspace/agent IDs; see [integration status, coverage and run instructions](../../docs/frontend-backend-integration.md). It starts/reuses Vite at port 5174. Use `pnpm --dir e2e test:web:public` for public pages and pure adapters without the backend. Development R2 CORS supports localhost and 127.0.0.1 at ports 3000 and 5173–5175.

Add shadcn components from this directory:

```sh
pnpm dlx shadcn@latest add dialog
```

The `@/` alias points to `src/`. Shared UI lives in `src/components/ui`, global theme tokens in `src/globals.css`, routing in `src/router.tsx` and application providers in `src/App.tsx`.

## Current scope

`/app` includes the page rail, workspace menu, resizable sidebar, quick search, navigation history, OpenBot’s two-pane mobile navigation and an optional context panel. Agents, Box and Storage use the authenticated backend APIs and SSE streams; see [Agent UI](AGENT-UI.md). The application has no demo fallback: missing authentication configuration shows an error.

`/app/:workspaceId/settings/:section` includes Your profile, General and Appearance with account preferences saved through Platform. Workspace settings use General/Members in the same dashboard frame; the sidebar footer switches between personal and workspace settings. The bottom avatar menu switches workspaces and opens their settings. Desktop-only OpenBot settings, billing, analytics, provider quotas, marketplace, workflows and computer controls are omitted.

`/app/:workspaceId/storage/:storageId` implements Storage: roots only in the sidebar (no folder tree or group labels), nested folders and breadcrumbs in the content area, Mosaic/Grid/List, multi-selection, drag and drop, file/folder upload, download/ZIP, context menus, rename, copy/move, collision handling and Trash/Restore. Files use the LetFS API and workspace permissions. ZIP downloads stream to a writable file when available, with browser-download fallback. Removing the former preview persistence does not erase existing browser-local data or upload it to the backend.

The page header ports OpenBot's page-owned identity/path and trailing controls into a shared frame. The identity accepts React content so conversation tabs use the same row; it does not impose storage controls on other pages. Sidebar resize keeps header alignment.

Storage has a permanent browser tab and closable file tabs; selected files and folders have distinct routes. The shared viewer also renders conversation files in the Agent right panel. It supports images, PDF, audio/video, Markdown, text/code, sandboxed HTML and XLSX sheets. Text previews stop at 1 MB; XLSX previews use OpenBot's bounded parser (500 rows / 50 columns). Unsupported formats can be downloaded. Source and license notices are in `src/vendor/openbot`.

The live suite exercises real file transfers and Grid/Mosaic/List conversation drags. Screenshots and failure context are written beneath `.local/e2e`.

All 63 official shadcn component modules are installed as source in `src/components/ui`. The shell composes these primitives and uses only semantic theme colors from `globals.css`. OpenBot's SolidJS shell structure was rewritten in React; its UI package is not bundled. The temporary blue logo adapts its original mark, with notices in `public/third-party/openbot`.

`pnpm test:web` runs browser checks independently of the backend API test runner, against the running local services. The empty-workspace test captures Settings at mobile and desktop sizes.

The public playground is isolated from authenticated application data. Authentication/API configuration is described in [Agent UI](AGENT-UI.md).

This is a client-rendered SPA. Production uses the Cloudflare Worker `openlet-web` at `openlet.qninhdt.com`. `worker.js` proxies `/v1` to the API gateway, preserves streaming responses and disables API/HTML caching. Other requests use the `ASSETS` binding with SPA fallback, configured in `worker.config.json`. Build `dist` using the production Clerk publishable key, package the Worker and assets into Cloudflare Build Output, then run `cf deploy --prebuilt`. Check the proxy with `node --test apps/web/worker.test.mjs` from the repository root. Public-page SSR or prerendering has not been configured.

## Agent avatars

Avatars use the original [jeremy-prt/bloub](https://github.com/jeremy-prt/bloub) engine, pinned at `b4bb3c1b5f93c7b87a2e8d620f667c4093d97749`. Upstream is a Vue app and does not publish an npm package. Its MIT engine is vendored unchanged under `src/vendor/bloub`, with a small React SVG renderer. No Vue or Solid runtime is required. Avatars animate on hover/focus and while working, pause offscreen or in hidden tabs, and respect reduced motion.

Mobile follows OpenBot’s 720px breakpoint: the Workspace pane contains the page rail and full-width list; selecting an agent opens the Chat pane. A 64px bottom bar switches between those panes. Context panels replace the content below the chat header rather than opening a modal sheet. On phones `/app` initially shows Workspace; selecting an agent or opening a canonical detail URL shows its content.

## Routing and retained state

Examples (IDs are stable; display names are independent):

- `/app/:workspaceId/agents/:agentId`, with `/overview`, `/activity`, `/box` and `/letis/:letiId/activity` children.
- `/app/:workspaceId/boxes` or `/app/:workspaceId/boxes/:agentId`.
- `/app/:workspaceId/storage/:storageId`, with `/folders/:folderId` or `/files/:nodeId` children.
- `/app/:workspaceId/settings/general` and `/appearance`.

`/app?workspace=…&view=…&agent=…` links redirect with replace. Header tabs, sidebar, breadcrumbs and Back/Forward share route state. Unknown canonical resources show an unavailable state rather than falling back to another resource. API access controls still enforce authorization.

The workspace layout retains draft messages, file sessions/tabs, browser folders, per-agent Chat/Activity reading positions and Box viewport state while only the selected main surface mounts. Dirty files may navigate within the workspace without losing edits. Leaving the workspace or unloading the document asks before discarding unsaved file changes, including files whose editor is no longer mounted. These in-memory drafts are not durable across a confirmed reload.
