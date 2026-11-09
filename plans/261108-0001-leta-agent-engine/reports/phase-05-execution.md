# Phase 05 execution checkpoint

Status: complete. Phases01–05 are complete (5/19). Phase06 has started; continue from [its execution checkpoint](phase-06-execution.md). No approval is pending. The full accepted goal remains active.

## Implemented contracts

- Added `0002_inline_text.sql` and one shared inline classifier. Supported small UTF-8/no-NUL text uses mutually exclusive PostgreSQL TEXT with exact UTF-8 SHA-256 and LF metrics. Current inline/file limits apply. Binary inline and object payloads remain supported; large/object text stays a blob. Owner byte transfers, download/archive/copy/move and parser/enrichment inventories preserve exact bytes and quotas. Parser output classification uses bounded batches.
- Native `Locator.root_id` restricts every path/cwd/ID/alias walk to a live ordinary directory. Artifact ancestry still comes from the actual scope root. Bound roots cannot be renamed/moved/trashed. Copy/move/restore preserve independent source/destination boundaries. Listed/generated descendants preserve readonly provenance in Go/Python and direct RPC responses.
- Implemented bounded unary `Stat`, `ReadText`, `TextMetrics`, `ReadTree`, `ReadImage`, generated bindings and typed Go/Python clients. Metadata/content/fingerprints use one repeatable-read snapshot. Whole/byte/line/head/tail selections preserve exact bytes. Maintained SHA-256 needs no TEXT payload fetch; other supported digests operate on permitted representation bytes.
- Blob JSON includes actual nested artifact paths, source metadata and processing state; no original blob bytes, storage keys, signed URLs or embedding context. Sources remain FILE nodes and named/source-ID aliases reach real readonly child files. Fingerprints change with processing/artifact state. Oversized/over-depth representations fail explicitly; bounded `ReadTree` navigation remains available.
- `ReadTree` uses deterministic path/ID keyset pages and subject-kind/ID, scope, bound-root, traversal-root and depth bindings. File-owned artifact subtrees are fetched in a batch rather than per-file queries. Directory listing wrappers accept full Locators.
- Backend-only PNG/JPEG/GIF previews inspect config before allocation, enforce40M input pixels, resize to a2048-pixel long edge, strip original metadata by PNG re-encoding, cap output at4MiB and use two fail-fast slots. All slots/readers close on failure/cancellation. A fresh authorized stat rechecks liveness/source/publication before returning the preview.
- Config/main/Compose require the existing distinct `LETA_SERVICE_TOKEN` pattern, with explicit native data-method admission and root resource delegation. No per-agent JWT is introduced. Original download/archive/upload, owner blob replacement, ingest, administration and purge are denied to this credential. Search admission follows phase07 root-aware search.

## Verified evidence

| Check | Result and limits |
| --- | --- |
| Mirage compatibility prerequisite | Pinned Mirage0.0.8, Python3.14.10 source-FILE plus named/source-ID nested artifact probe passed. The actual adapter/cache remains phase08. |
| Storage/root slice | Full real filesystem/gRPC/HTTP/server race integration passed; exact BOM/CRLF/multibyte/empty/binary bytes, TEXT metric constraints, quota/copy/archive/inventory and path/cwd/ID/alias/root/artifact regressions are preserved. Previous evidence is in the storage/root journal. |
| Current full filesystem regression | Passed257.092s with `-race`; HTTP17.848s and server19.351s passed. Log `/tmp/openlet-leta-phase05-native-reads.log`. Its initial aggregate invocation failed only the gRPC Temporal startup fixture; do not call that aggregate green. |
| Temporal fixture correction | TCP could precede gRPC/namespace initialization. Isolated lifecycle rerun passed6.848s. The fixture now waits for the pinned CLI's real `operator namespace describe --namespace openlet --address 127.0.0.1:7233`. Full gRPC race group then passed84.982s; log `/tmp/openlet-leta-phase05-grpc-final.log`. |
| Native read boundary | Authenticated Leta gRPC passed all five methods/clients, root boundaries, PNG preview and raw download/upload/purge refusal. Store tests cover exact selectors, stale tokens, processing-only change, real nested paths/readonly, cursor depth/root/subject isolation and current authorization. |
| Large metadata navigation | Final native-text integration passed15.703s with10001 actual child directories: metadata fails explicitly while a bounded subtree page succeeds. No flattening/truncation namespace is introduced. |
| Image source/revocation | Real inline/object preview tests, source change and permission revocation during object read, saturation/released slots and stale-source conflict passed with `-race` (combined native text/image group16.806s). Unit cases cover resize/digest, dimension bomb before allocation, malformed/unsupported input, cancellation and encoded output bound. |
| Shared checks | Python48 tests and bootstrap7 tests passed, plus Go LetFS/RPC clients, LetFS unit tests, contracts check, formatting and vet. The later stable-ID slice has updated counts/checks in phase06. |
| Scoped review | gpt-6.1-sol/xhigh read-only simplification review found no concrete defect or worthwhile simplification in the native reads/clients. Simplifier ran clean; no edits or independent test claims. Controller reviewed snapshot/size/auth/root/artifact/blob boundaries. |

## Accepted execution constraints

No production data, backup gate, backward-compatibility or legacy conversion CLI. Fresh disposable schemas use ordered migrations; binary/object variants are current functionality. The obsolete conversion CLI requirement was removed from the owning phase. A standalone build invocation was blocked by the environment's `build` command filter; affected packages were compiled by passing Go unit/integration tests and vet. No new standalone build result is claimed.

Phase05 checkboxes were closed using `ak plan check`. No persistent database migration/reset, paid inference, commit, push or deployment occurred. All phase05 test sessions and their Testcontainers completed. Existing user/lab processes were not stopped.

## Next work

Phase06 owns atomic small-text writes and directory operations; phase07 exact native search and GIN measurement; phase08 the actual Mirage adapter/hooks/cache. Do not restart completed phases or repeat dependency research. Current runtime/API/schema source and the owning phase files remain the execution authority.
