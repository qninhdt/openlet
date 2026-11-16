# Bloub engine

Vendored unchanged from [jeremy-prt/bloub](https://github.com/jeremy-prt/bloub), commit `b4bb3c1b5f93c7b87a2e8d620f667c4093d97749` (MIT).

Upstream is a Vue application with no published npm package. Its framework-independent `src/bot` engine is used by `components/agent-avatar.tsx`, a React renderer. No Vue runtime, demo UI, video exporter or SolidJS fork is included.

To update, replace these engine modules from the pinned upstream and rerun typecheck and browser tests. `cycles.ts` and upstream tests are not needed by the idle avatar renderer.
