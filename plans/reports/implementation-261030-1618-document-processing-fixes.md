# Document processing repair — 2026-10-30

Status: completed within the existing resource/output budgets. All six final real-file API checks passed. This records measured results, not a guarantee of document-layout equivalence.

## Cause and changes

- PDF conversion inherited Docling's large stage queues and four-page batches. Apple reproduced native allocation failures under the worker bounds. One-page batches and a two-item stage queue allow Apple 121 pages and NIST 80 pages to finish in the same 4 GiB worker. The original NIST failure's precise allocator cause was not independently established.
- Section export called `save_as_markdown` repeatedly. The installed implementation copied the whole document and re-encoded every picture on every call. Export now writes each picture once, installs relative image references, and exports section text. The existing empty `images/` directory contract is preserved; the ZIP acceptance test caught its initial accidental removal.
- python-pptx skips shape-level OOXML `mc:AlternateContent`. A narrow Docling backend extension selects supported text/math branches or the embedded fallback before its normal conversion. This reuses Docling's math parsing and does not rewrite the uploaded document.
- Deeper DOCX inspection proved that Docling treated table cells containing content controls as plain text. python-docx `cell.text` excludes those controls, dropping visible letters (`Global` became `lobal`, `Place` became `lace`). A narrow backend override routes these cells through Docling's existing rich-cell walker. Ordinary body controls already worked; a multi-cell table is required to reproduce the defect.
- Docling Core's default 20 MiB image decoding limit conflicted with the existing image/output budgets. Its limit now follows those budgets; existing pixel, output-byte/count, input, memory and time bounds remain active.
- Native allocation/resource failures previously became `DOCUMENT_INVALID`. Resource failures now map to `RESOURCE_LIMIT`; unexpected converter exceptions map to `PROCESSING_FAILED`. The supervisor drains stderr with an 8 KiB tail and logs only a validated typed diagnostic, never raw dependency output or document text.

No database, workflow definition, upload/download protocol, dependency version or default product limit changed.

## Real-document evidence

Baseline: `/tmp/openlet-real-world-ct8qw6sf`. Recheck: `/tmp/openlet-real-world-fixed-q_azkdei`. The same 23 unmodified public documents from 15 hosts were uploaded through the actual API, Temporal and Python worker. Their source URLs and SHA-256 values were recorded in `sources.json` at execution. All 23 originals downloaded byte-for-byte intact. Those temporary files were later lost in the host reboot; the final six-file verification is preserved separately below.

| Case | Before | After |
|---|---|---|
| Apple annual report, 121 PDF pages | Allocation failure, incorrectly `DOCUMENT_INVALID` | Succeeded in the same 4 GiB worker. Final full readback: 312 nonempty Markdown files + four images, no broken image references, original bytes intact; 484.94 s including paced retrieval. |
| NIST incident handling, 80 PDF pages | `DOCUMENT_INVALID` | Succeeded, 117 artifacts, 234.94 s; sampled worker peak about 2.40 GiB |
| CMU introduction, 69 physical / 66 visible slides | 304.70 s | 24.78 s; all visible-slide paragraphs retained |
| Productivity Commission DOCX, 99 sections | 174.36 s | 46.94 s in the first fixed run; 61.22 s in final verification with paced retrieval and the Word override. Same remaining paragraph-audit flags. |
| IIT math presentation | Most body text missing | 29 Markdown files; independent per-slide check found all 356 significant source text runs, including editable math |
| Purdue ink presentation | Success with all 633 picture occurrences missing | Default limit rejects explicitly. Separate check with the existing configurable limit set to 1,024 produced 10 Markdown + 633 images; all 632 source media matched decoded pixels. |
| NOAA 75.15 MiB presentation | Docling 20 MiB image error | Image error fixed; complete conversion creates 355,654,111 output bytes (339.18 MiB), exceeding the unchanged 256 MiB cap. Reports `RESOURCE_LIMIT`, with no partial publication. |
| Five eligible XLSX inputs | 265,951 meaningful cells across 47 sheets | Same 265,951 cells, zero missing values; these inputs contain no formula cells |

Durations include polling and API artifact retrieval; they are single-run observations, not controlled converter benchmarks. Hardware/container limits and original inputs were retained. The full recheck recorded 19 successful operations and four limit rejections. Besides NOAA and Purdue, the original 492-page PDF and 10.57-million-cell workbook still exceed existing limits. Apple's full artifact retrieval subsequently passed with safe GET pacing/backoff; gateway rate limiting stayed enabled.

The first retrieval captured 1,005 artifact files excluding Apple's interrupted readback. Gateway rate limiting was kept enabled. Its 429 is retained as test-client evidence and is not hidden by changing server configuration.

The host rebooted at 19:38, clearing the temporary corpus and raw `/tmp` logs. The observations above were recorded before that loss. Current evidence is stored persistently outside the repository at `/home/qninh/.cache/openlet-document-verification-261030-1940`: six fresh downloads from the same public URLs, source hashes, API results, outputs, test logs, histories and database backups. Apple's downloaded SHA-256 matches the original corpus. The earlier unfinished run cannot be claimed as verified after the reboot. A preceding rerun also hit a temporary client `FileNotFoundError` because its output parent directory was missing; the final client creates parents explicitly and paces/retries safe GET requests.

## Verification

- New exporter/parser/error regressions failed against the previous implementation before repair. The empty-image-directory regression also failed before restoring the ZIP contract.
- Final Python suite rerun after reboot: 26 passed, with four upstream OCR deprecation warnings. Log: `python-tests.log` under the persistent evidence directory.
- Final `make verify GO=/usr/local/go/bin/go` rerun after reboot: passed (`verify.log`). The absolute Go path is required by this session's PATH.
- Fresh actual four-format processing, ZIP, query-bound, retry-exhaustion and kill/restart checks passed before reboot. All eight corresponding processing/export histories replayed successfully. After the Word override, final four-format/ZIP/query-bound acceptance and six processing/export history replays passed again (`run.log`, `processing-replay.log`, `export-replay.log`). Worker retry logic did not change with the Word override; its earlier kill/retry checks were retained.
- All five final real DOCX API journeys passed, with original-byte equality and all 188 artifacts downloaded. No broken image references were found. Victoria's two lost content-control phrases are restored, and its body-paragraph audit flags fell from two to zero. The other DOCX paragraph flags remain at 25/0/3/0 after normalizing Markdown links; they are comparison flags, not independently proven loss.
- Final Apple verification passed with all 316 artifacts downloaded and the original SHA-256 preserved. Across all six files: 504 artifacts and 63 valid local image references. All raster outputs passed image decoding validation. `apple-audit.json` also records five source facts present in the artifacts: a business-description phrase, the consolidated-operations heading and the financial values 391,035, 93,736 and 364,980. An exploratory expected phrase, “Revenue Recognition”, was absent from the original PDF itself; its invalid probe is retained in `apple-audit-initial.json` and excluded from the five valid source facts.
- Reviewed the source changes against saved pre-change files, plus new backend/tests and affected documentation. No unrelated source edits, staging or commits were made. The repository was already entirely untracked.

The first extra acceptance run exposed the empty-directory regression and a temporary runner setup error: it omitted `CREATE EXTENSION pg_stat_statements`, which the canonical runner performs. Both were corrected before rerunning.

Raw failed-run logs in `/tmp` were subsequently lost in the reboot; the recorded failures above remain part of this report. The pre-change processor source was recovered from the retained `openlet-processor:before-real-fix` image into `before-source.json`; `source.diff` records the reviewed processor delta.

The final runner exited successfully. Owned containers, networks and fresh volumes were removed; no task processes remain. Fresh test PostgreSQL was backed up before migrations and again before disposable-volume cleanup. No development database was modified. Local artifacts, scripts and private backups remain outside the repository in the persistent evidence directory.

## Limits and follow-up

The comparison audits are detectors, not visual certification. DOCX paragraph flags include combined textboxes, duplicated compatibility branches and table/footnote formatting; the two confirmed content-control omissions were fixed separately. The remaining flags are not independently proven missing-content defects. Some DOCX table-heading sections remain empty. PDF anchor comparisons can differ around tables, layouts and parser normalization. CMU repeated footer text is still omitted by upstream conversion. Unselected fallback media and hidden slides are not expected to appear as duplicate outputs.

The default 512-entry and 256 MiB output budgets intentionally remain unchanged. Purdue requires a larger existing output-count configuration for complete processing; NOAA requires a larger output-byte budget or a separate image-export policy decision. Neither limit was raised just to pass the corpus.

Live R2/Clerk, production deployment and visual inspection of every page were not performed. The normal image build stalled while downloading models, so the test build reused the prior pinned image's identical model files; the same lockfile and dependency versions were installed. The production Dockerfile was not changed. Final test image: `sha256:17c2a882b88f3d576ee329508ff38a0a8a9db0a66f8b8e56435bd2258327567e`.

Downloaded originals, corpus scripts, local database backups and detailed evidence stay outside the repository. Temporary `/tmp` evidence may disappear on reboot or cleanup.
