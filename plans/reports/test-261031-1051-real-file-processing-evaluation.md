# Real file processing evaluation

Status: final repaired-file runs and search evaluation are in progress.

The corpus contains 120 authentic downloaded files: 15 each of PDF, DOCX, XLSX, PPTX, TXT, Markdown, CSV and images, totaling 201,047,096 bytes. The first complete run processed and indexed 117 files; three PDFs failed parsing. Original bytes were retained for every input, including the failures.

Generation and vision use OpenRouter `openai/gpt-6-luna` with `reasoning.effort=none`; the live smoke response reported zero reasoning tokens. Embeddings use `openai/text-embedding-3-small`, 1,536 dimensions, and reranking uses `cohere/rerank-v3.5`. All three endpoints were called live. The isolated stack uses the existing test issuer for identity and storage forwarding; generation, embeddings and reranking call OpenRouter directly. Credentials were read privately from the requested sibling environment.

[Per-file results and provenance](test-261031-1013-real-file-processing-files.csv) include source URLs, sizes, hashes, stage outcomes, layout, artifact counts and vector counts. The downloaded corpus, original manifests, scripts and detailed outputs are retained under [`.local/real-corpus`](../../.local/real-corpus/).

## Output and layout

PDF/DOCX outputs exercised compact README layouts and indexed Markdown sections. Excel retained one numbered folder per sheet, a README in every folder, table CSVs and outside-table prose in the sheet README. PPTX retained one README with slide markers plus extracted image/CSV files. Direct text, Markdown, CSV and image sources created no artifact tree.

The real corpus exercised levels 0 and 1. Level 2 is covered by parser-layout regression fixtures, but has not been demonstrated by a successful real-corpus input. The two downloaded books with the strongest long-document coverage exceed the current page limit.

The artifact audit verifies README presence, child metadata fields, renamed paths, uniform structural leaf depth, relative Markdown links, source hashes, and current Qdrant point identities. Retired points from replacement jobs are counted separately: existing cleanup waits 15 minutes, while search validates the current job against PostgreSQL.

## Repairs found by this evaluation

- Rich DOCX cell text was emitted into both CSV and Markdown. The CSV-link serializer now marks the cell subtree as consumed. A focused regression failed before the repair and passed afterward.
- Tracked insertions inside otherwise plain DOCX cells disappeared. The Word backend now routes those cells through the rich walker. The real Western Australia annual-report template retained all 42 checked paragraphs containing inserted text in the local recheck.
- Headings inside table cells were selected as document boundaries and produced empty Markdown sections. Structural layout now keeps those headings inside the owning table.
- Folder/root metadata sometimes described README navigation instead of the underlying material. The generation prompt now synthesizes subjects from children. The full FRED unemployment workbook recheck correctly identified the U.S. monthly unemployment series and its 1948–2026 range.

The affected two DOCX files and the FRED workbook are being replaced through the ordinary upload API with their identical original bytes and stable source IDs, then processed through Temporal, enrichment and indexing again. Baseline artifacts are retained separately for comparison.

## Remaining findings

- `swebok.pdf` has 335 pages and `git-pro-book.pdf` has 501; both return `RESOURCE_LIMIT` against the existing 200-page ceiling. They remain in the corpus and failure denominator.
- The 74-page, 36.9 MB NASA Artemis plan crashes the native converter. A local reproduction shows native allocation failures near 3.8 GiB RSS; another reproduction exits with a segmentation fault. The source remains readable and has no published vectors.
- The Excel coordinate audit found one unsupported array-formula representation at `Calculation!T25` in `uk-electricity-et_5.2_sep_26.xlsx`: the README contains an OpenPyXL object representation. Formula evaluation and merged-cell interpretation remain deferred.
- Some isolated numerical table fragments receive low-information titles such as “Untitled CSV with 39 numeric-labeled columns.” Parent and root metadata provide broader context, but fragment titles remain weak.

## Validation

The full processor suite passed 76 tests, including actual PDF/OCR and Office conversion, with four dependency warnings. Ruff and formatting checks passed for the changed processor files.

Final artifact, chunk, search and cleanup measurements will be added after the repaired runs finish.
