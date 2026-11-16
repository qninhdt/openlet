# OpenBot source port

`spreadsheet-workbook.ts` is copied unchanged from nightly-labs/openbot at
`fe548649eae069e03e525e2b609ec52b042f2c0f`, packages/contracts/src/spreadsheet-workbook.ts.
Its license is included alongside it.

The Storage components port the structure and interaction rules of LibraryPage,
LibraryPathHead, LibrarySelectionPill, ImageLightbox,
FilePreviewPanel, marquee-selection and library-folder-drag to React/shadcn.
PageHeader follows the upstream page identity/path + trailing children contract;
React nodes can occupy identity, including a conversation's own tab strip.

Differences: real nested filesystem semantics, separate storage roots, cross-storage
transfers, roots-only sidebar (no folder tree), browser upload, right-click menus, and Trash instead of virtual placements.

Upstream uses PolyForm Noncommercial 1.0.0 (see LICENSE), not MIT. The copied parser retains those terms; commercial deployment requires rights compatible with that use. Bloub has its own separate MIT notice.

The Agent interface also ports geometry and interaction rules from OpenBot at
`e50025767311cad46c9fd67d7fa0daed81c4d370`:
`ConversationHeader`, `ThreadTabs`, `TabShape`, `AgentSteps`, sidebar pinned/compact styles,
`chat-action-card.css`, `question-prompt.css` and `browser-takeover.css`.
Provider SVG paths in `components/agents/provider-logo.tsx` follow
`packages/brand/src/provider-logo-shape.ts`; the origins are recorded there.
The React Agent tool renderers map Openlet's tool names to these presentation rules;
they are not a claim of equivalent upstream tool implementations.
