# Phase 06 execution checkpoint

Status: complete. Phases01–06 are complete (6/19). Stable creation IDs, atomic native text mutations, directory-chain creation, empty-directory trash and their Go/Python/gRPC boundaries are implemented and verified. Continue phase07. No user approval is pending. The full accepted goal remains active.

## Implemented slice

- Private `CreateNodeRequest.node_id` optionally chooses a UUIDv7, validated at Store admission. Omission keeps normal server allocation. The same ID participates in the existing creation request fingerprint/receipt; there is no new receipt table or operation registry.
- Creation never adopts a conflicting ID/name. After receipt expiry the caller verifies its known live ID using current resolution; recreating the occupied resource remains a conflict. Phase12 still owns persisting `boxes.home_node_id` before external creation and checking the exact home binding on retry.
- Go's generic `CreateNode(NodeCreation)` accepts a complete root-restricted parent Locator, optional node ID and optional InlineFile. Existing directory/file helpers delegate to it. Python's existing creation methods add optional `node_id`; both languages reject a mismatched response ID. Protobuf/generated Go/Python clients were regenerated. Public HTTP creation still generates IDs.

## Verification

- Real PostgreSQL/SpiceDB node-write integration passed10.249s with `-race`, including stable key replay, receipt expiry, exact live-ID inspection, cross-scope duplicate ID, unrelated same-name occupant, UUIDv4 refusal and unchanged accounting after failures. Existing quota/receipt/tree cases in that test passed too. Log `/tmp/openlet-leta-phase06-stable-create-filesystem.log`.
- Authenticated native Leta gRPC integration passed9.663s, including the new generic Go creation client, full root Locator, chosen ID and repeat key. Its aggregate command initially failed compiling the filesystem test because of one reused short declaration; corrected `:=` to `=` and reran the filesystem group above. The original log is retained at `/tmp/openlet-leta-phase06-stable-create.log`.
- Shared Python suite49 tests passed, including stable directory/file request mapping and rejected mismatched response ID. Go LetFS/RPC clients passed.
- Final generated-contract check, LetFS formatting/vet/unit checks, Ruff check/format and diff whitespace checks passed. All owned test sessions completed; no persistent server or test service is needed.

## Native mutation and directory slice

- Unary WriteText/AppendText/PatchText/TruncateText use an existing observation (Locator, positive revision, optional fingerprint) or explicit guarded absent creation. Exact UTF-8, no NUL, bounded inline result, byte overwrite, literal replacement cardinality and shrink-only truncate are enforced before commit. No-ops retain revision/generation only after every observation passes. New native text creation bypasses binary filename/MIME heuristics and reuses the existing create-node receipt with distinct native-text input; no new table.
- Mutations derive bytes inside the existing filesystem/scope transaction, updating quota, text metrics, processing invalidation and revision atomically. TEXT enters text processing even with a blob-like filename; CSV retains CSV format. Service dispatch occurs after commit through the current pending-processing path.
- CreateDirectories atomically creates relative components beneath an observed root-restricted parent. Empty-directory TrashNode checks ordinary kind and emptiness under the same lock as child creation. Owner HTTP retains normal trash behavior; all Store/Service callers and generated/handwritten clients are coherent.
- The narrow Leta credential now admits these unary methods, retaining raw blob/upload/archive/ingest/admin/purge denial. Go/Python clients preserve target observations/creation keys/root guards and validate response identity. No text streams, new ledger, lease, outbox, retry worker or compound-command exactly-once mechanism.

## Current validation

- Unit byte tests cover CRLF/multibyte exactness, overwrite/EOF extension, gaps/overflow, literal cardinality/nonoverlapping replacement, truncate UTF-8 cuts/growth, NUL and bounded final size. They first failed because the new implementation did not exist, then passed.
- Real PostgreSQL/SpiceDB mutation+directory integration passed16.629s; expanded mutation cases including exact64-byte native creation, absent/no_create/offset guards, text-only scope controls and TEXT processing selection passed with directory tests17.535s. A test initially used a NUL buffer for a size-only assertion; replaced the fixture with valid text so it actually exercises the final-size guard.
- Authenticated Leta gRPC passed9.930s with real backend/storage: all four mutations, native directory creation/trash, direct malformed admission, binary edit refusal, root-limited artifact copy and response-loss injected after a committed append. Retrying its old revision fails and the body contains one append. The expanded fixture initially omitted copy limits and used a nonexistent local pointer helper; corrected the fixture and reran. Final log `/tmp/openlet-leta-phase06-native-grpc-final.log`; failed earlier runs are not success evidence.
- Full final LetFS `test:integration` passed with race detection: filesystem283.997s, Temporal50.404s, gRPC130.718s, HTTP26.562s and server28.064s. This includes existing copy/trash/processing/scope regression and the new mutation/directory/fault cases. Final log `/tmp/openlet-leta-phase06-full-integration.log`.
- Shared Python50 tests passed7.15s; Go LetFS/RPC clients passed including rejected unrelated mutation responses, generated-contract verification passed, full LetFS unit suite passed, and formatting/vet (integration/workflow tags), Ruff and whitespace checks passed. Logs `/tmp/openlet-leta-phase06-unit.log`, `/tmp/openlet-leta-phase06-clients.log`, `/tmp/openlet-leta-phase06-python.log`.
- Conditional gpt-6.1-sol/xhigh simplification review was read-only and found no defect or additional useful simplification. Parent removed the single duplicate classify/hash computation before final tests. No delegate edits or independent test claim.

## Immediate next work

1. Continue phase07 search and phase08 Mirage adapter in order. Search admission intentionally waits for root-aware search. Native conditional fixtures now exist; actual Mirage mapping is still phase08 work. No production build/deploy is implied.
2. Pinned Mirage0.0.8 sdist was downloaded from `uv.lock`, SHA-256 verified (`76ec7c766ea2cddfc7182bcf9a18409058a5c5dd95d89862a46de9b8c6cc5b14`) and unpacked at `/tmp/openlet-mirage-source/mirage_ai-0.0.8`. `mirage/vfs/base.py::files_containing` line742 / `lines_containing` line781 confirm literal-superset and intact-line contracts; ordinary bytes are allowed and no streaming backend is required. The old temporary source checkout referenced by phase07 no longer exists. Refetch from the locked sdist if the new temporary copy disappears.
3. Phase07's stale backup prerequisites were corrected to the explicit no-production/no-backup constraint. Its Store query/candidate-line baseline has now started; [phase07 checkpoint](phase-07-execution.md) owns that continuation. No index/benchmark or search admission has been added. Preserve the real default-planner GIN performance gate rather than treating a forced-index diagnostic as success.

No persistent database mutation/reset, production migration, paid inference, commit, push or deployment. Existing user/lab processes remain untouched. Keep all plan/report text in English and respond to the user in Vietnamese.
