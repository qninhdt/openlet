---
title: "Phase 5: LetFS small inline TEXT and native reads"
status: completed
priority: P1
effort: 5d
dependencies: [2]
---

# Phase 5: LetFS small inline TEXT and native reads

## Outcome and execution boundary

Store supported small UTF-8 text in PostgreSQL TEXT and expose native metadata, tree, selected-text and bounded image-read APIs. Preserve existing object-backed text, owner transfers, processing, quotas and binary bytes. Typed `user`/`leta` native principals from phase 2 are required; a Leti uses its root `leta:L` principal and a narrower backend root.

The [accepted design](../reports/design-261108-0148-leta-workspace-resource.md) governs this phase. [Phase 6](phase-06-letfs-text-mutations.md), [phase 7](phase-07-letfs-native-text-search.md) and [phase 8](phase-08-mirage-workspace-adapter.md) consume its native contracts. Phase 4 owns private scope candidate enumeration and generic Workspace accessible-scope discovery; this phase does not duplicate either API.

Implementation complete; see the [execution checkpoint](reports/phase-05-execution.md) for verification and the resolved Temporal fixture readiness failure. The pinned Mirage 0.0.8 compatibility probe passed with a truthful FILE source and named/original-ID child artifact reads on Python3.14.10. The real native adapter integration remains phase08 work. A concrete incompatibility blocks dependent implementation until reported; changing the accepted paths or forking Mirage requires a new decision.

## Current implementation and affected contracts

All implementation paths below are relative to `/home/qninh/projects/openlet`.

| Source owner | Existing behavior and required reach |
| --- | --- |
| `apps/letfs/migrations/0001_initial.sql` | `files` has `inline_bytes` or `object_key`; add one TEXT variant without reinterpreting binary bytes. |
| `apps/letfs/internal/config/config.go` | `InlineLimit` defaults to 262144 bytes and its existing maximum is 1048576; `MaxFileBytes` defaults to 100 MiB. Agent-editable text uses the inline boundary, not the blob maximum. |
| `apps/letfs/internal/filesystem/node_writes.go::inlineSize/validateInlineText/CreateNode/ReplaceContent` | Existing inline size, scope-specific control-character, quota and processing rules must reach the TEXT variant. |
| `apps/letfs/internal/filesystem/paths.go::Locator/session.resolve` | One recursive query resolves paths, IDs, cwd and root `@UUID`; it already follows children under a file and computes readonly file ancestry. Preserve these properties when adding root restrictions. |
| `apps/letfs/internal/filesystem/nodes.go::ListNodes` | Native listing accepts a Locator and can return children under a file; propagate readonly provenance for listed descendants instead of hardcoding it false. |
| `apps/letfs/internal/filesystem/download.go`, `archive.go`, `copy_data.go`, `scope_move.go` | Existing byte consumers must encode small TEXT as exact UTF-8; object behavior remains unchanged. |
| `apps/letfs/internal/filesystem/processing_publication.go`, `upload_publication.go`, `enrichment.go`, `indexing.go` | Publication/classification and inventory readers must support bounded TEXT while retaining current generation fencing and existing inline/signed-object inventory variants. |
| `apps/letfs-ingest/src/letfs_ingest/processing/processor.py` | Reads the current inline-content/signed-URL inventory variants. Keep those variants; bounded TEXT is encoded into the existing inline-content field. |
| `packages/go/rpc/transport.go` | Shared RPC maximum is 8 MiB. A normal small TEXT payload, bounded metadata and a 4 MiB image preview fit without a new large-content transport. |

## Storage contract

1. Add `files.text_content TEXT`, `newline_count BIGINT` and `text_sha256 TEXT`. Extend the existing storage-kind/payload check so exactly one payload exists: TEXT for `storage_kind='text'`, bytea for existing `inline`, or `object_key` for existing `object`. TEXT count/hash describe `convert_to(text_content,'UTF8')`; other variants have no TEXT metrics. Empty text is `''`, never NULL.
2. New supported text must fit `min(InlineLimit, MaxFileBytes)`, be valid UTF-8 and contain no U+0000. Preserve the stricter existing control-character rule in text-only scopes. Keep BOM, CRLF, trailing spaces and final unterminated lines exactly; do not normalize.
3. Use one classifier for inline publication: explicit native text writes and inline textual MIME/processing formats are candidates; known binary formats remain binary even if their bytes happen to decode as UTF-8. Invalid UTF-8/NUL stays exact binary in blob-enabled scopes; a text-only-scope invariant violation is rejected without dumping content.
4. Fresh development installs use the ordered schema migrations and current writers. The user explicitly rejected legacy conversion tooling and production/backward-compatibility prerequisites; do not add an inline-conversion CLI. Existing binary inline and object-backed content remain supported payload variants, including object-backed textual MIME. Do not fetch S3 text for conversion, add large canonical TEXT, or create Download/Inventory text-reference variants or `ReadProcessingText`.
5. Preserve owner byte APIs and ingest authority. TEXT becomes exact UTF-8 bytes at the existing bounded inline boundary; original object uploads/downloads, parser access, signed transfers and archive streams keep their existing contracts. Agent methods never expose those signed URLs or raw blob bytes.
6. Update every served-payload reader/writer, copy and direct SQL fixture together. Staging `uploads.inline_bytes` is still transfer state, not a second served TEXT copy. Charge exact UTF-8 byte size; storage conversion alone changes neither quota, node count, revision nor processing generation.
7. A lower later `InlineLimit` must not make previously valid stored bytes unreadable or silently move them to objects. Enforce the current limit on new/final mutation bodies; inventory existing rows before changing configuration. The existing 1 MiB maximum still bounds legitimate stored TEXT.

## Backend root restriction

Add optional `root_id` to the existing proto/Go/Python Locator, preserving existing field numbers. Omitted means the ordinary scope root. The trusted adapter always supplies its immutable descriptor root; model tool arguments cannot supply principal, filesystem, scope or root IDs.

- Validate a supplied root as a live ordinary directory in the selected active filesystem/scope, descended from its actual scope root. Keep the actual scope root for liveness/provenance checks and a separate traversal boundary for the mount. Do not turn a generated artifact directory into writable authority.
- Absolute paths start at that boundary; relative cwd, direct node IDs, `@<original-file-id>` aliases, every intermediate step and final nodes must remain inside it. `..` cannot climb out, even temporarily before returning inside. Root aliases still work for descendants inside a box root.
- Enforce the same check on existing node/read/mutation/copy/trash/restore methods, not only new RPCs. A bound root cannot be renamed, moved or trashed through that view. Source and destination roots are independently validated; `session.inScope` cannot replace a destination restriction with its whole scope.
- Scope permission checks use the verified typed subject and never infer user authority from a UUID alone. The `leta` service credential can select a server-owned root resource subject only on its allowed native methods; a public user cannot select `leta` through headers or payloads. Root restriction narrows permission and never grants it.

## Proposed native read contracts

Extend `FilesystemService` and its generated Go/Python clients. These are proposed new RPC names, not claims about existing methods. Use bounded unary responses for normal text and image data. No new agent HTTP route, large read stream, client-streamed text write or buffer setting is needed.

| RPC | Request and result |
| --- | --- |
| `Stat` | `(filesystem_id, scope_id, locator, content_check)` returns resolved Node, true node kind, readonly provenance, storage/agent representation kind, readable byte size, revision token, exact representation fingerprint and available LF/SHA-256 metrics. `content_check=true` requires current `scope.read_content` and is used before serving content cache hits. A metadata-only stat never authorizes bytes. |
| Existing `ListNodes` | Locator-complete directory/file-owned child listing, existing cursor semantics and truthful child kinds. Return current artifact readonly ancestry. No content bodies are loaded to discover mounts. |
| `ReadTree` | `(filesystem_id, scope_id, root: Locator, depth?, cursor?, limit, max_bytes)` returns actual descendant paths and stat-equivalent metadata in deterministic path/ID order, explicit completeness and next cursor. Default cap 10000 entries/4 MiB serialized output; lower caller limits are valid. Bind cursors to subject kind/ID, scope, bound root, traversal root, depth and last path/ID. This is live keyset pagination, not a durable snapshot. |
| `ReadText` | `(filesystem_id, scope_id, locator, selection, expected_fingerprint?)` returns selected bytes, selected span, total readable size and the matching stat/token from one read snapshot. TEXT returns text; blobs return the metadata representation below. A raced expected token returns conflict, not bytes from another version. |
| `TextMetrics` | Same Locator plus algorithm returns LF count and an exact lowercase representation digest. Maintain SHA-256 with TEXT; compute supported standard-library MD5/SHA digests over permitted bytes. Explicit unsupported status lets the adapter return `None` for Mirage's own fallback. Never use an object ETag as a content digest. |
| `ReadImage` | Same Locator plus expected fingerprint returns bounded PNG preview bytes, MIME, dimensions and source/output fingerprints. The source path itself selects an original-image preview; a real generated image child uses its actual child path. No synthetic preview nodes, mounts or URLs. |

Validate response ceilings on actual serialized bytes, leaving room below 8 MiB. Tree/metadata overflow is explicit, never a complete truncated response. Blob metadata containing the actual nested tree has a 4 MiB ceiling; return a clear limit error if it cannot fit and allow bounded `ReadTree` navigation of the actual children. `Stat` may return the compact tree-bound fingerprint without duplicating the whole metadata body. No native result may include source object keys, credentials or signed URLs.

`ReadText.selection` is a oneof:

| Selector | Exact semantics |
| --- | --- |
| Whole | Exact readable bytes within the response ceiling. |
| Byte range `(offset, length?)` | Zero-based byte offset; omitted length means EOF; nonnegative values; zero length and offsets at/past EOF return empty. Read bytes may split a UTF-8 code point because the wire field is bytes. |
| Lines `(start_line, line_count)` | One-based start; nonnegative count. LF delimits lines, CR before LF is preserved, and a nonempty final fragment is one line. A trailing LF adds no invented empty line. Beyond EOF is empty. |
| Head/tail `(line_count)` | Same line definition and exact bytes; zero is empty. Never cut a requested line silently to satisfy a response bound. |

LF count means byte count of `\n`, matching `wc -l`, rather than logical line count. Reject invalid selectors, negatives and overflow before reading/allocating. Resolve payload, selected bytes and representation tokens in one snapshot; close transactions/readers on cancellation and never return partial success.

## Blob metadata and real artifact hierarchy

Blob means existing binary inline/object content and object-backed text. Its ordinary read yields deterministic UTF-8 metadata JSON: source ID/name/MIME/original size/revision, processing generation/status/error and its **actual nested artifact tree**, with real child kind/name and usable relative paths. JSON size/LF count/checksum describe those JSON bytes; public Node size remains original stored size.

- Preserve `parent_id` and nested directories below the original file. A source stays a FILE in stat and still has native child nodes. There is no separate artifact ID type, projected tree, `ArtifactVFS`, sibling artifact mount or required lookup by a child ID.
- Valid forms are `/shared/docs/report.pdf/report.md` and `/shared/@<original-file-id>/report.md`, including nested paths such as `images/page.png`. Equivalent forms work under `/home` (the physical HOME used for `~`) and `/users/<user-id>`. Original-ID aliases are scoped to their current mount root. Metadata may return source-relative paths so the adapter can prepend the real mount without inventing a namespace.
- Generated children are readonly because of file ancestry, including direct ordinary-node-ID access. Current source generation, live ancestry, subtree root and read permission must all hold. Reprocessing removes stale descendants from the readable tree.
- Serialize stable keys and child order with a representation version. Fingerprints include the represented source metadata, processing state and current tree, not merely source `nodes.revision`; publication can change artifacts without bumping that revision. Representation size and fingerprint must describe the same snapshot.
- `ReadTree` retains the real hierarchy, including descendants of file nodes. Mirage commands still own how they walk truthful file kinds; test accepted explicit artifact reads and native tree output rather than rewriting commands to reinterpret all files as directories.

## On-demand image boundary

`read_file` can request `ReadImage` at the original image path through the custom `read_image` VFS call. Ordinary shell/Monty reads of that source still return metadata. Backend-only source access is for producing a permitted preview; it does not grant the agent raw blob access.

1. Authorize current content, root, liveness and generation before opening source bytes. Reuse the existing storage client internally and close/bound reads. Do not add a transfer route or persistent image-processing stage.
2. Inspect `image.DecodeConfig` before decode; reject invalid/overflow dimensions or more than 40 million input pixels. Initially support standard-library PNG/JPEG/GIF, first frame only for GIF. Unsupported formats return typed unsupported/unavailable status, without original-byte fallback.
3. Resize to at most 2048 pixels on the long edge; re-encode PNG without original ancillary metadata. Existing standard-library resampling is sufficient; do not add a dependency by assumption. Bound encoded output to 4 MiB and use two fail-fast preview slots to bound concurrent decoding.
4. Return output digest/dimensions and the current source identity/token. Recheck publication state/authority before releasing a result after processing. Bombs, cancellation, slot saturation, decoder failure and output overflow release resources and return clear errors.

## Files and callers

| Action | Files | Change |
| --- | --- | --- |
| Add | `apps/letfs/migrations/0002_inline_text.sql` | Additive TEXT fields/payload checks; verify actual next migration number before implementation. |
| Add | `apps/letfs/internal/filesystem/text_storage.go`, `text_reads.go`, `tree.go`, `representations.go`, `image_reads.go` and focused tests | Shared classification/encoding, selections/metrics, actual hierarchy, metadata tokens and bounded image reads. |
| Modify | `apps/letfs/internal/filesystem/{paths,nodes,node_writes,download,archive,copy,copy_data,scope_move,upload_publication,processing,processing_control,processing_publication,processing_uploads,enrichment,indexing}.go` | Root restriction and all bounded TEXT writers/consumers; retain large object processing. |
| Modify | `packages/contracts/proto/openlet_api/letfs/v1/letfs.proto`; `apps/letfs/internal/transport/grpc/filesystem.go`, `download.go`, `ingest.go`; add native read handlers | Extend Locator and bounded read contracts; reuse current bounded inline Download/Inventory wire variants for TEXT. |
| Modify | `packages/go/clients/letfs/{filesystem,operations,ingest}.go`; `packages/python/src/openlet/clients/letfs.py`; matching client tests | Locator-complete wrappers, typed results, response scope/root/identity validation and bytes compatibility. |
| Modify | `apps/letfs/cmd/server/main.go`, `main_test.go`, `apps/letfs/internal/config/config.go`, `config_test.go` | Admit the distinct configured `leta` service credential on narrow native methods; deny original download/archive/upload/ingest/admin/purge. Phase 4's scope enumeration remains Workspace-only; do not add text buffer configuration. |
| Modify | Existing filesystem/transport integration fixtures and `apps/letfs-ingest/tests/` affected inventory tests | Remove TEXT-as-bytea assumptions while retaining explicit binary and object fixtures. Processor changes are needed only if tests reveal an actual bounded-inline compatibility gap. |
| Modify | `docs/data-model.md`, `docs/openlet.dbml`, `docs/api-contracts.md`, `docs/operations.md` | Small TEXT/object boundary, native-only reads, root restriction, artifact paths and coordinated rollout. |

Regenerate `packages/go/gen` and `packages/python/src/openlet_api`; never hand-edit them. Shared proto/client/migration edits are serial with phases 4, 6 and 7.

## Implementation checklist

1. [x] Confirm phase 1's actual pinned source-FILE/child compatibility probe passed; record versions, paths and observed tool/shell results before implementing expensive backend additions.
2. [x] Enumerate all payload readers/writers and test fixtures above. Add regressions for small UTF-8/CRLF/NUL, inline binary, large object text, inventory bytes and alias/root escape attempts.
3. [x] Implement shared classification/encoding and additive TEXT schema. Keep current limits and original object keys/transfers; do not change processing generation for exact-byte format conversion.
4. [x] Update served readers/writers/copy/processing inventories and verify byte/hash/quota/generation behavior on ordered disposable migrations. No legacy conversion CLI under the user's accepted development-only constraint.
5. [x] Extend Locator and enforce roots in the shared resolver and all source/destination flows, including listed-artifact provenance. Exercise direct authenticated gRPC bypasses of adapter policy.
6. [x] Add bounded unary Stat/ReadText/TextMetrics/ReadImage and paginated ReadTree; regenerate clients and preserve one-RPC path stat.
7. [x] Implement deterministic blob JSON with actual nested paths/tree and processing-aware fingerprints; retain truthful FILE stat and ordinary child lookup.
8. [x] Implement backend-only bounded image decoding, preview slots, cancellation and output digest. Prove no raw original bytes/URLs in agent responses.
9. [x] Perform focused and shared-contract checks, review cross-module quota/processing/authorization behavior and update the owning docs from actual behavior.

## Validation scenarios and commands

| Scenario | Mechanical pass condition |
| --- | --- |
| Empty/multibyte/BOM/CRLF/final fragment | Read selectors equal independent literal byte slices; size/hash/LF count remain exact. |
| Inline limit at default and existing 1 MiB maximum | Last permitted final text succeeds; one byte over fails. Large original text stays object-backed and agent-visible as metadata/tree. |
| Legacy inline binary and owner object transfer | Exact bytes and current Download/Inventory variants remain valid; no new large-text reference or streaming reader is introduced. |
| Ordered disposable migrations and current writers | Fresh schemas support exact TEXT metrics while binary/object payloads remain intact; no production conversion/reset tool is introduced. |
| Root escapes through paths/IDs/cwd/aliases/moves/copies | Backend rejects foreign/out-of-root nodes and bound-root mutation, including direct RPCs. |
| File-owned nested artifact | Named and source-ID paths resolve without child-ID lookup, preserve FILE source stat and deny artifact writes. |
| Processing-only change/revoke during image work | Metadata token changes; stale artifacts/preview cannot be released as current authorized data. |
| Oversized nested metadata/tree | Explicit limit/incomplete contract; no silent flattening, missing children or complete truncated result. |
| Image limits/failure/cancel | Supported previews meet 40M/2048/4 MiB/two-slot bounds; all readers/slots close; no original URL/raw blob result. |

Commands are future execution instructions from the repository root; new named tests are deliverables, not tests run during planning:

```sh
pnpm contracts:generate
pnpm contracts:check
go -C apps/letfs test ./internal/filesystem ./internal/transport/grpc ./cmd/server
go -C apps/letfs test -race -tags integration ./internal/filesystem ./internal/transport/grpc -run 'Test(InlineText|TextRead|ReadTree|ImageRead|RootRestrictedLocator|Download|Archive|Processing|Copy|Scope)' -count=1
uv run --locked --package openlet-python pytest packages/python/tests/test_letfs_clients.py -q
go -C packages/go test ./clients/letfs ./rpc
pnpm --filter @openlet/letfs check
pnpm --filter @openlet/letfs build
pnpm --filter @openlet/letfs test:integration
```

## Migration, risks and rollback

The user explicitly confirmed there is no production data and no backup or backward-compatibility prerequisite. Apply and verify the schema only in owned disposable test/development environments; do not add legacy-reader support, production conversion choreography or a backup gate. All served writers/readers must agree on TEXT before enabling the variant. Binary inline and object payloads remain supported product behavior. A full rollback for disposable development state recreates that owned state from the selected code/schema; no production deployment or reset of an existing user environment is implied.

- [x] Small TEXT, binary and object paths pass real consumer tests, and ordered migrations are verified on disposable PostgreSQL.
- [x] Typed subject isolation and backend-root/readonly/liveness/generation checks pass directly through gRPC.
- [x] Artifact and image paths match the accepted design without a projected namespace or raw blob escape.
- [x] Pending pinned runtime compatibility and processing-aware cache tokens are reported honestly; no source-only runtime success claim remains.
