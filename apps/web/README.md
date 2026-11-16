# Openlet web

Frontend workspace for the public website, sign-in and the application.

The navigation follows OpenBot's UI structure, with Server mapped to Workspace. The shell is available at `/app`; nested page routes remain planned.

## Stack

- React + TypeScript (strict), built with Vite.
- Tailwind CSS 4 with the Vite plugin.
- shadcn/ui: Radix primitives, Nova style, neutral tokens, Lucide icons and a self-hosted Geist font.
- TanStack Router for `/`, `/login`, `/app` and the not-found page.
- TanStack Query, with one `QueryClientProvider` at the application root.
- `@assistant-ui/react` provides the Agent preview runtime and composer, with custom tool renderers. Backend integration remains pending.

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

`pnpm dev` serves the app at `http://localhost:5173`. `make check-js` runs formatting, type checks, lint and the production build, including this workspace.

Add shadcn components from this directory:

```sh
pnpm dlx shadcn@latest add dialog
```

The `@/` alias points to `src/`. Shared UI lives in `src/components/ui`, global theme tokens in `src/globals.css`, routing in `src/router.tsx` and application providers in `src/App.tsx`.

## Current scope

`/app` includes the page rail, workspace menu, resizable sidebar, quick search, navigation history, OpenBot’s two-pane mobile navigation and an optional context panel. Agents have a local interactive conversation preview with 27 custom tool renderers and four multi-turn demo scenarios; see [Agent UI](AGENT-UI.md). Schedule remains a blank page. Agent and workspace items are preview fixtures, not backend data.

`/app?view=settings` implements General and Appearance with browser-local preferences and theme selection. Chat preferences are stored for the future chat implementation. Desktop-only OpenBot settings, billing, analytics, provider quotas, marketplace, workflows and computer controls are omitted.

`/app?view=storage` implements the interactive Storage preview: roots only in the sidebar (no folder tree or group labels), nested folders and breadcrumbs in the content area, Mosaic/Grid/List, multi-selection, drag and drop, file/folder upload, download/ZIP, context menus, rename, copy/move, collision handling and Trash/Restore. Files are saved in IndexedDB per workspace and remain local to this browser; this is not cloud persistence or an authorization boundary. It does not call LetFS yet. Clear browser site data to reset fixtures. Large ZIP downloads are assembled in memory; use backend streaming when connecting real storage.

The page header ports OpenBot's page-owned identity/path and trailing controls into a shared frame. The identity accepts React content so conversation tabs use the same row; it does not impose storage controls on other pages. Sidebar resize keeps header alignment.

The viewer keeps the browser mounted underneath. It supports images, PDF, audio/video, Markdown, text/code, sandboxed HTML and XLSX sheets. Text previews stop at 1 MB; XLSX previews use OpenBot's bounded parser (500 rows / 50 columns). Unsupported formats can be downloaded. Source and license notices are in `src/vendor/openbot`. Preview images are attributed in `public/storage-preview/README.md`.

Set `OPENLET_STORAGE_SCREENSHOTS` to an absolute directory when running `pnpm test:web` to capture Storage in all three modes and the image viewer at 390, 721 and 1440 pixels.

All 63 official shadcn component modules are installed as source in `src/components/ui`. The shell composes these primitives and uses only semantic theme colors from `globals.css`. OpenBot's SolidJS shell structure was rewritten in React; its UI package is not bundled. The temporary blue logo adapts its original mark, with notices in `public/third-party/openbot`.

`pnpm test:web` runs browser checks independently of the backend API test suite. Set `OPENLET_SHELL_SCREENSHOTS` to an absolute directory to capture the shell, panels and Settings at desktop, tablet and mobile sizes.

Landing and login remain placeholders. Authentication and API requests are not implemented. Agent chat is a local UI preview.

This is a client-rendered SPA. Production hosting must serve `index.html` for application routes such as `/login` and `/app`. Public-page SSR or prerendering has not been configured.

## Agent avatars

Avatars use the original [jeremy-prt/bloub](https://github.com/jeremy-prt/bloub) engine, pinned at `b4bb3c1b5f93c7b87a2e8d620f667c4093d97749`. Upstream is a Vue app and does not publish an npm package. Its MIT engine is vendored unchanged under `src/vendor/bloub`, with a small React SVG renderer. No Vue or Solid runtime is required. Avatars animate only on hover, stop on pointer leave, and respect reduced motion.

Mobile follows OpenBot’s 720px breakpoint: the Workspace pane contains the page rail and full-width list; selecting an agent opens the Chat pane. A 64px bottom bar switches between those panes. Context panels replace the content below the chat header rather than opening a modal sheet. On phones the initial preview shows Workspace; selecting an agent opens its conversation.
