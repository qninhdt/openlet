# Active real-corpus evaluation checkpoint

User requested 15 authentic files per supported type, varied lengths and sources, real pipeline and real semantic search. Use OpenRouter credential from ../pycil env, GPT-6 Luna with reasoning disabled; choose embeddings/reranker. No commit or deployment. Vietnamese conversation; English plans/reports. Preserve existing uncommitted changes and notes.md.

## Confirmed configuration
- Model: openai/gpt-6-luna, reasoning effort none. Live smoke returned reasoning_tokens 0.
- Embeddings: openai/text-embedding-3-small, 1536 dimensions.
- Reranker: cohere/rerank-v3.5. All three APIs live-verified.
- Credential privately loaded from ../pycil/.env LLM_API_KEY (LLM_BASE_URL is OpenRouter). Stored in ignored .local/real-corpus/openrouter_api_key and mounted secret; never print secrets or signed URLs.
- Added optional OPENROUTER_REASONING_EFFORT in AISettings, validation, Instructor extra_body reasoning.effort, compose, .env.example, docs/setup.md. Focused test_semantic.py 13 passed.

## Corpus and harness
All under ignored .local/real-corpus/ (absolute /home/qninh/projects/openlet/.local/real-corpus).
- manifest.json: selected 120 inputs, exactly 15 PDF/DOCX/XLSX/PPTX/TXT/MD/CSV/image, authentic downloaded bytes, URLs, sizes and SHA-256. downloaded-manifest.json includes extras. files/ holds corpus (193 MB).
- Collection scripts and logs retained. PDF pages: swebok 335 and git-pro 501 exceed existing 200-page limit; retain and report their expected resource-limit outcomes. Other PDFs 2-74 pages.
- evaluate-corpus.py: upload actual public API, handles 16-outstanding backpressure, polls processing, downloads original/artifacts, verifies hashes, README and links/levels, reconstructs evidence point IDs and checks actual Qdrant. Uses stat to hydrate metadata because list DTO omits context; follows redirects to read S3 content. Atomic JSON result writes.
- watch-results.py: concurrent observer only, imports harness and audits completed files while uploader waits for slots.
- audit-content.py: offline DOCX paragraph edge retention, PPTX text run retention, XLSX cell value and sheet retention. Run via uv run --project services/letfs/processor --locked python .local/real-corpus/audit-content.py after outputs complete.
- search-corpus.py: handwritten queries based on original documents/images; evaluates rank@1/@5/@20, real reranking, unique originals, filename search. Run inside evaluator container. Initial 60 direct-file queries: 57 top1, 60 top5, 60 top20, no degraded responses/errors. Need final rerun with all successful files and add Vietnamese cross-language queries if useful.
- results/: uploads.json, status per source, inspection per source, points per source, artifacts/group/source/path, search-results.json + search-summary.json. session-private.json contains synthetic test identity IDs only, no JWT saved.

## Running owned infrastructure
Docker Compose project openlet-real-evaluation; command wrapper bash .local/real-corpus/dc.sh. Isolated new Postgres/S3/Qdrant/Temporal/app services. Existing test issuer used solely for identity and S3 forwarding. Letfs + processor explicitly use https://openrouter.ai/api/v1 and real credentials, NOT test AI routes.
- Wrapper combines deploy/compose.yaml + compose.test.yaml + .local/real-corpus/compose-real.yaml. State .local/real-corpus/.local/test.
- All migrations went through /migrate.sh with pre-change database backups.
- Two real processor replicas, max one activity each, 2 CPU / 4 GB each. Host 12 CPU /14 GB RAM (10 GB available before scale).
- SeaweedFS test default 8x64 MB volumes filled during real corpus; confirmed No writable volumes and no free volumes. Evaluation-only override raised volume max to32 and volume size256MB; restarted same persistent store. No application resource limits changed. A few source/artifact transfers got500/502 and should be retried after storage recovery. Capture initial faults as environment issues.
- Active uploader container entrypoint /app/.venv/bin/python -u /corpus/evaluate-corpus.py. Current log evaluation-resumed.log; exec session59985. Old session66299 was stopped.
- Active observer command /app/.venv/bin/python -u /corpus/watch-results.py. Log inspection-resumed.log; exec session53478.
- Inspect exact names using docker ps with project/service labels and docker inspect only Cmd/Entrypoint, not Env (secrets).
- Original full log evaluation-full.log had signed URLs in old httpx error strings; do not print it raw. Harness now summarizes transfer status; sanitize any log via regex removing URL query strings before output. Editing a running script does not reload it; restart only owned evaluator containers when needed.

## Current progress at checkpoint
101 files uploaded;61 fully inspected (60 direct files + temporary certificate DOCX), inspected source hashes/point identities clean; completed DOCX level0 with8artifacts. Other Office stages progressing; all PDFs still queued for upload behind Office. Failed source uploads Cornell systems architecture and cloud lecture2 remain absent from uploads.json and must be retried by restarting uploader after current pass. Current uploader retries RESOURCE_LIMIT backpressure only, failed transfers are recorded and skipped.

## Remaining work
1. Let uploader/observer finish; monitor meaningful progress and give concise Vietnamese updates at least every60s.
2. Re-run uploader for missing manifest entries after transfers failed. Inspect all actual failures; use public processing-retry per stage for storage-induced terminal failures. Resource limits (200 PDF pages, etc.) are legitimate evaluation findings; do not change thresholds to force passing.
3. Fix concrete product bugs revealed (scope includes evaluation; avoid speculative changes), add focused regression and rerun affected real cases if needed.
4. Run offline content audit and inspect representative README/trees across 0/1/2 levels, images, CSV outputs, chunk boundaries.
5. Run final semantic/filename query suite over all successful inputs; report unavailable inputs separately, not hidden passes.
6. Write concise English report in plans/reports/test-261031-1013-real-file-processing-evaluation.md plus per-file CSV if useful. Update active plan acceptance.
7. Run focused lint/tests for reasoning setting and any repairs; git diff --check. Stop owned evaluator and Compose containers with dc.sh down (preserve volumes and corpus).

## Recovery update at 10:47 local
- All 120 sources now uploaded. Fixed harness multipart upload: no global checksum at/above16MiB; use returned part_size_bytes. Missing3 files successfully uploaded with upload-missing.py.
- Only watcher remains (session75737, inspection-final.log); stopped original uploader and old watcher to remove duplicate audits. Watcher retries429 via new harness api helper; all outputs retained.
- Three processor replicas now, each2CPU/4GB; baseline image still original, fixes below not loaded in baseline. All containers owned by project openlet-real-evaluation.
- Current87 inspected (60 direct,14DOCX,10XLSX,3PPTX). Git Pro501pages reached RESOURCE_LIMIT as expected; SWEBOK335expected too.
- DOCX genuine defects: LinkedTables did not mark rich-cell subtrees visited => duplication across CSV+MD. Fixed exporter; regression failed before/passed after. WordBackend plain-cell shortcut missed w:ins => missing12 tracked-insertion paragraphs in WA tier2. Extended existing rich-cell wrapper detection to sdt|ins; parameterized test failed before/passed after. Offline real-source repair outputs under repaired/docx; recheck-word.py verifies actual tracked text.
- Metadata prompt originally described README/file listings. Updated folder/root synthesis instruction; full real FRED UNRATE tree re-enriched locally through actual Luna and now root correctly describes monthly U.S. unemployment1948–2026. Saved metadata-full-tree-recheck.json.
-32 focused tests passed;64nonparser passed. Full processor suite running session3208, log processor-tests.log, DOCLING_MODELS_PATH=.local/processor-models. Ruff clean after formatting word.py.
- Chunk audit initial false gaps due pathlib.read_text newline normalization for CRLF Gutenberg files; now read raw bytes.decode and zero uncovered text in100indexed bodies at first recheck.
- Markdown regex preliminary flags were false (C++array/operator pattern across lines; titles beginning Untitled CSV). audit-markdown-links.py uses MarkdownIt AST and exact placeholder pattern;87sources558relative links zeroissues. Rerun at end, it replaces preliminary regex flags in saved inspections.
- DOCX retention audit now unescapes HTML, excludes nested paragraph duplication, normalizes formatting. Twelve unmatched WA tier2paragraphs are genuine tracked insertions (fixed). Others checked now0missing. audit-docx-retention.py.
- XLSX coordinate audit reconstructs CSV cell positions fromREADME range links, compares every nonempty source cell, compares cached values for formulas (formula handling deferred). sheet-values-audit.json. Earlier raw-formula mismatches were expected cache differences. Run again after all XLSX complete.
- summarize-results.py writes durable per-file CSV under plans/reports and evaluation-summary.json. Need final report after all120terminal + final search-corpus.py and search-vietnamese.py.
- Need rebuild processor image with repairs, rerun representative real files through full pipeline (replace existing source with same original bytes via ordinary upload locator/revision, preserve baseline evidence), then search final and stop stack.

## Update at 10:59 local
- Baseline finished:117successful,3parse failures (Git Pro501pages/SWEBOK335pages resource limits; NASA Artemis74pages native converter segfault). All3failed source hashes verified unchanged and0Qdrantpoints in failed-source-audit.json. NASA bounded offline reproduction shows native allocation failures near3.8GiB RSS; unbounded-thread reproduction segfaults; no input-limit increase.
- All117baseline point identities/source hashes inspected. Chunk audit510text bodies0uncovered nonwhitespace; MarkdownIt audit1531relative links0broken. XLSX coordinate audit15files980394nonempty cells/11012formula cells:1unsupported ArrayFormula objectrepr atT25 ofUKelectricity5.2 Calculation, formula handling explicitlydeferred.
- PPTX audit now includesCSVtablecells and excludes typedfooter placeholders; no unmatched5+word body text runs in completed15PPTX.
- New measured layout defect: headings nested inrich tablecells cutdocument intoemptysections. Addedregression failedbefore; layout.py now collects structuralheadings outsideTableItemsubtrees. Fullprocessor76passed/4warnings;ruffclean. Rebuildingimage again toincludeit (session14737).
- First repairedpipeline attempt failed BEFORE anyreplacement because harness putrevision inbody; APIcorrectlyrequiresIf-Matchheader. Fixedharness. FSSformCbaselineinspection/points/artifacts alreadyarchived underbaseline/docx/name; restorebyrerunning same script. No target source replacedyet.
- Currentprocessor2replicas newfirstrepairimage; idle. Awaitsecondbuild thenrecreateprocessor2replicas, rerunrerun-repaired-files.py. It archivesbaseline, replaces3sources usingoriginalbytes/sameIDs, thenpolls+inspects.
- Databasebackupbefore3replacementoperations:before-repair-replacements.dump6.7MB, restorelistingverified insidepostgrescontainer (hostpg_restore absent).
- Remaining: repairendtoend3files; finalsemantic117queries+8Vietnamese; repeatfinalauditsandfileCSV; reporttest-261031-1051-real-file-processing-evaluation.md; markevaluationplan; stopComposeincludingoneoffcontainers.
- Observepossible remainingWordnestedtabledata duplicationbetweenouterCSVandinnerCSV. Needverifyactualfinalresult andreport; don'textendadvancedlayoutscope speculatively. Realcorpus0/1layoutsobserved;2-levelselectorverifiedbyunitfixturesonly.
