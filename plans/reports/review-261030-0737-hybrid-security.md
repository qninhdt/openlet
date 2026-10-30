# Hybrid Artifact Plan - Security Review

## Verdict

No concrete security blocker found in the revised direct-child plan. The plan now defines a single shared trust rule - a strict file ancestor makes a node an artifact descendant - and requires that rule across path, alias, raw-ID, cwd, read, mutation, copy, deletion, and publication paths.

This was a read-only plan review. No source or plan edits, builds, tests, lint, typecheck, migrations, or runtime checks were performed.

## Contract verification

### Alias collision and scope: covered

- The alias is limited to the first filesystem-relative segment at an absolute mount root, or a relative path whose cwd is exactly that root; nested `@<uuid>` segments remain ordinary names (`phase-01-artifacts.md:48`). This preserves the current mount-to-filesystem authorization check in `paths::parts` (`services/letfs/src/fs/paths.rs:29-35`, `services/letfs/src/fs/paths.rs:49-71`).
- The plan reserves only canonical UUID-shaped root child names, keeps `@notes` and nested names legal, requires a pre-enable collision scan, and fails instead of shadowing existing data (`phase-01-artifacts.md:50`, `phase-01-artifacts.md:69`). Current name validation permits such names, confirming that contextual root validation is required rather than a global name ban (`services/letfs/src/fs/mod.rs:51-55`).
- Every destination context is explicitly included: create, upload, rename, move, copy, restore, and raw-ID requests (`phase-01-artifacts.md:50`, `phase-01-artifacts.md:72`, `phase-03-acceptance.md:28`). This covers current destination owners in node creation/move (`services/letfs/src/fs/nodes.rs:280-296`, `services/letfs/src/fs/nodes.rs:341-362`), uploads (`services/letfs/src/fs/uploads.rs:27-66`), copy (`services/letfs/src/fs/copy.rs:118-138`), and restore (`services/letfs/src/fs/trash.rs:69-99`).

### Readonly provenance through all locators: covered

- The source node itself is excluded from provenance, so it stays writable; any strict file ancestor marks the final node readonly (`phase-01-artifacts.md:55`). The plan requires final-target provenance after traversal and applies it to raw IDs as well as ordinary/alias/cwd paths (`phase-01-artifacts.md:72`).
- The resolver remains the common liveness/scope snapshot. Current resolution starts raw IDs and cwd paths through the same ancestry-to-root proof (`services/letfs/src/fs/paths.rs:99-115`), while the plan requires all three direct resolver callers and every wrapper consumer to move together (`phase-01-artifacts.md:18-19`, `phase-01-artifacts.md:71`).
- The plan distinguishes read-container behavior from writable-directory guards (`phase-01-artifacts.md:20`, `phase-01-artifacts.md:46`, `phase-01-artifacts.md:71`). That is necessary because current list and traversal require directories (`services/letfs/src/fs/nodes.rs:242-252`, `services/letfs/src/fs/paths.rs:109-112`), while public write destinations separately call `Node::directory` (`services/letfs/src/fs/nodes.rs:282-285`, `services/letfs/src/fs/uploads.rs:53-56`, `services/letfs/src/fs/copy.rs:123-126`, `services/letfs/src/fs/trash.rs:69-73`). The plan does not weaken those write guards globally.
- Readonly coverage includes edit, overwrite, rename, move, trash, purge, and every write destination; only processor publication may attach children under a file (`phase-01-artifacts.md:56`). Phase 3 requires each access form, foreign/scope rejection, hidden trash/staging nodes, source writability, and writable copied-out artifacts (`phase-03-acceptance.md:27-29`).

### Parent guards and lifecycle: covered

- Existing path preconditions distinguish expected target from expected parent (`services/letfs/src/fs/paths.rs:128-142`), and current mutation callers apply them before side effects (`services/letfs/src/fs/nodes.rs:282-284`, `services/letfs/src/fs/nodes.rs:314-316`, `services/letfs/src/fs/nodes.rs:345-347`, `services/letfs/src/fs/trash.rs:42-44`). The plan explicitly preserves expected-ID guards and updates every mutation boundary (`phase-01-artifacts.md:55`, `phase-01-artifacts.md:72`).
- Current leaf assumptions are correctly identified: inline copy treats files as terminal (`services/letfs/src/fs/copy.rs:20-31`), list requires a directory (`services/letfs/src/fs/nodes.rs:242-252`), inline purge removes one file (`services/letfs/src/fs/trash.rs:110-130`), and durable purge admission requires a directory (`services/letfs/src/fs/deletion.rs:78-105`). The plan routes hybrid files with children through durable copy/purge and retains leaf fast paths only after locked no-child checks (`phase-01-artifacts.md:62-64`, `phase-01-artifacts.md:74`).
- Deletion already walks actual parent edges and removes leaves first (`services/letfs/src/fs/deletion.rs:165-179`). The plan checkpoints detached top-level child forests before source replacement/link changes and keeps those roots hidden while cleanup drains (`phase-01-artifacts.md:59`, `phase-01-artifacts.md:65`).

### Publication validity and stale work: covered

- Unpublished output creates no nodes. Completion validates bounded paths, collisions, parent structure, counts, hashes, bytes, and rejects unexpected existing children (`phase-02-processing.md:48`).
- The publication transaction rechecks the nonsuperseded intent, exact active generation/UUID, live source, captured byte identity, and total depth before attaching children (`phase-02-processing.md:30`, `phase-02-processing.md:50-55`). This prevents stale attempts, raw-handle substitution, source replacement, and depth violations.
- Winning children, quota, handle finalization, and result commit atomically; a failed transaction exposes no children, and a lost response returns the stored result without a second charge (`phase-02-processing.md:53-57`). Phase 3 includes reordered generations, stale handle/complete/abort, lost responses, copy/publication ordering, replacement, and filesystem deletion fences (`phase-03-acceptance.md:31-35`).
- Direct presigned PUT now requires provider-enforced exact length and fails the acceptance gate if unavailable (`phase-02-processing.md:41`, `phase-02-processing.md:151`, `phase-03-acceptance.md:35`), resolving the prior unbounded staging-capability concern.

## Already adjudicated

The revised plan explicitly states that the supervised Docling child remains inside the worker process trust boundary and does not claim a separate sandbox (`phase-02-processing.md:37`, `phase-02-processing.md:151`). Per review scope, this accepted model was not reopened.

## Residual risk

The remaining risk is implementation consistency, not a missing plan contract: provenance and contextual alias-name validation must be returned by the shared resolver and checked before every side effect. The plan's caller inventory and focused acceptance matrix are adequate to detect omissions (`phase-01-artifacts.md:18-19`, `phase-01-artifacts.md:103-109`).

## Unresolved questions

None.

Status: DONE
Summary: No new security blocker found. The revised plan covers scoped alias collisions, strict-ancestor readonly behavior through path/ID/cwd forms, parent preconditions, hybrid lifecycle fast paths, and atomic stale-safe publication.
Skipped checks: No builds, tests, lint, typecheck, migrations, containers, or runtime/provider checks were run.
