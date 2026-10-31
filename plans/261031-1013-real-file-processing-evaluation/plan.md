# Real File Processing Evaluation

## Outcome
Run the production upload, Temporal processing, enrichment, indexing and semantic search pipeline against 15 authentic downloaded files in each supported group: PDF, DOCX, XLSX, PPTX, TXT, Markdown, CSV and images (120 files). Preserve source URLs and inspect output quality, layout and chunks per source.

## Constraints
Use OpenRouter GPT-6 Luna with reasoning disabled, text-embedding-3-small (1536 dimensions), and Cohere rerank-v3.5. Read the credential privately from ../pycil env. Use an isolated Compose project and database; back up before migrations/data writes. Preserve existing uncommitted changes and notes.md.

## Non-goals
No production deployment, commits, paid synthetic fixtures, or changing expected outputs to obtain passing results.

## Acceptance
- [x] Download and validate 15 distinct real files per group from multiple sources with varied document lengths.
- [x] Add validated configurable generation reasoning effort with a focused contract test.
- [x] Run all files through actual services and paid AI endpoints, retaining stage outcomes and original-byte verification.
- [x] Inspect every artifact tree, metadata, Markdown links, content retention, structural levels and chunk evidence; manually review representative outputs.
- [x] Run semantic queries with independently chosen expected source files, report rank/recall, reranker degradation and failures.
- [x] Report defects and validation evidence; stop owned processes.

## Execution
1. Collect a provenance manifest and real corpus under ignored .local/real-corpus.
2. Bring up an isolated real-AI stack, with existing test identity/storage boundary only.
3. Upload and process corpus, inspect output and Qdrant evidence, evaluate semantic search.
4. Investigate failures, apply scoped repairs when needed, rerun affected cases, record results in plans/reports.

## Results
117 of 120 selected files indexed. English search: 109/117 top 1, 117/117 top 5; eight Vietnamese queries all top 1. All selected originals retained unchanged. One official ONS download containing only a title cell was rejected and replaced by the real FRED INDPRO workbook. Real level 2 coverage remains absent; parser, formula and nested-table limitations are recorded in the [evaluation report](../reports/test-261031-1051-real-file-processing-evaluation.md).
