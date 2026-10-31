# Real file processing evaluation

Status: evaluation complete; remaining findings are listed below.

The corpus contains 120 authentic downloaded files: 15 each of PDF, DOCX, XLSX, PPTX, TXT, Markdown, CSV and images, totaling 201,067,163 bytes. The first complete run processed and indexed 117 files; three PDFs failed parsing. Original bytes were retained for every input, including the failures.

Generation and vision use OpenRouter `openai/gpt-6-luna` with `reasoning.effort=none`; the live smoke response reported zero reasoning tokens. Embeddings use `openai/text-embedding-3-small`, 1,536 dimensions, and reranking uses `cohere/rerank-v3.5`. All three endpoints were called live. The isolated stack uses the existing test issuer for identity and storage forwarding; generation, embeddings and reranking call OpenRouter directly. Credentials were read privately from the requested sibling environment.

[Per-file results and provenance](test-261031-1013-real-file-processing-files.csv) include source URLs, sizes, hashes, stage outcomes, layout, artifact counts and vector counts. The downloaded corpus, original manifests, scripts and detailed outputs are retained under [`.local/real-corpus`](../../.local/real-corpus/).

## Processing outcomes

| Type | Selected | Indexed | Failed | Observed layout |
| --- | ---: | ---: | ---: | --- |
| PDF | 15 | 12 | 3 | 4 compact, 8 single-level |
| DOCX | 15 | 15 | 0 | 8 compact, 7 single-level |
| XLSX | 15 | 15 | 0 | Sheet folders |
| PPTX | 15 | 15 | 0 | Single README with extracted assets |
| TXT | 15 | 15 | 0 | Direct source |
| Markdown | 15 | 15 | 0 | Direct source |
| CSV | 15 | 15 | 0 | Direct source |
| Image | 15 | 15 | 0 | Direct source |

## Output and layout

PDF/DOCX outputs exercised compact README layouts and indexed Markdown sections. Excel retained one numbered folder per sheet, a README in every folder, table CSVs and outside-table prose in the sheet README. PPTX retained one README with slide markers plus extracted image/CSV files. Direct text, Markdown, CSV and image sources created no artifact tree.

The real corpus exercised levels 0 and 1. Level 2 is covered by parser-layout regression fixtures, but has not been demonstrated by a successful real-corpus input. The two downloaded books with the strongest long-document coverage exceed the current page limit.

The artifact audit verifies README presence, child metadata fields, renamed paths, uniform structural leaf depth, relative Markdown links, source hashes, and current Qdrant point identities. Retired points from replacement jobs are counted separately: existing cleanup waits 15 minutes, while search validates the current job against PostgreSQL.

## Repairs found by this evaluation

- Rich DOCX cell text was emitted into both CSV and Markdown. The CSV-link serializer now marks the cell subtree as consumed. A focused regression failed before the repair and passed afterward.
- Tracked insertions inside otherwise plain DOCX cells disappeared. The Word backend now routes those cells through the rich walker. The real Western Australia annual-report template retained all 42 checked paragraphs containing inserted text in the local recheck.
- Headings inside table cells were selected as document boundaries and produced empty Markdown sections. Structural layout now keeps those headings inside the owning table.
- Folder/root metadata sometimes described README navigation instead of the underlying material. The generation prompt now synthesizes subjects from children. The full FRED unemployment workbook recheck correctly identified the U.S. monthly unemployment series and its 1948–2026 range.

Three affected DOCX files and the FRED unemployment workbook were replaced through the ordinary upload API with identical original bytes and stable source IDs. All four completed Temporal processing, enrichment and indexing again. The final DOCX audit found all 4,298 checked nonempty paragraphs in the output, and no empty section files remain. Baseline artifacts are retained separately for comparison.

## Remaining findings

- PDF math extraction is incomplete with formula enrichment disabled: 19 `formula-not-decoded` placeholders appear across Bitcoin (4), Attention Is All You Need (6), LoRA (6), and Retrieval-Augmented Generation (3). Parsed-text chunk coverage does not measure these missing equations.
- Nested DOCX tables still duplicate some text across the enclosing CSV and an extracted inner-table CSV. In the repaired Tier 2 report, “Incidence of work-related injury or illness” appears in both `agency-annual-report-disclosures-2026.csv` and `work-health-and-safety-measures-and-targets.csv`. The repair above removes the separate Markdown leak; nested-CSV ownership still needs an exporter change.

- `swebok.pdf` has 335 pages and `git-pro-book.pdf` has 501; both return `RESOURCE_LIMIT` against the existing 200-page ceiling. They remain in the corpus and failure denominator.
- The 74-page, 36.9 MB NASA Artemis plan crashes the native converter. A local reproduction shows native allocation failures near 3.8 GiB RSS; another reproduction exits with a segmentation fault. The source remains readable and has no published vectors.
- The Excel coordinate audit found one unsupported array-formula representation at `Calculation!T25` in `uk-electricity-et_5.2_sep_26.xlsx`: the README contains an OpenPyXL object representation. Formula evaluation and merged-cell interpretation remain deferred.
- Some isolated numerical table fragments receive low-information titles such as “Untitled CSV with 39 numeric-labeled columns.” Parent and root metadata provide broader context, but fragment titles remain weak.

## Validation

The full processor suite passed 76 tests, including actual PDF/OCR and Office conversion, with four dependency warnings. Ruff and formatting checks passed for the changed processor files. The spreadsheet audit compared 982,990 nonempty cells across all 15 workbooks, using cached results for 11,012 formula cells; the single array-formula mismatch is listed above.

The final audit checked 482 indexed text bodies with zero uncovered non-whitespace text, and 1,508 relative Markdown links with zero broken targets. All 15 PPTX files retained their slide counts and checked body text runs, including table CSV text; typed footer placeholders were excluded from the comparison.

Chunking uses `RecursiveCharacterTextSplitter`, prioritizing paragraph, line, sentence and word boundaries, with character-based token estimates. Ninety text bodies needed multiple chunks. Pride and Prejudice produced 214 chunks across 763,082 characters, with observed overlap of 440–512 characters. RFC 9110 produced 142 chunks across 502,907 characters, with overlap varying from 39 to 512 characters at structural boundaries.

The final 117-query search rerun found the expected original at rank 1 for 109 queries (93.2%) and within the top 5 for all 117. All returned matched-file IDs and breadcrumbs belonged to the current artifact trees, and filename search found all 117 indexed sources plus the three failed PDFs. Eight additional Vietnamese queries found their expected English-language sources at rank 1. No API response reported degradation or an error. Eight harness breadcrumb flags came from the excluded ONS node remaining in the test database; all were resolved by checking its retained artifact tree, with raw results preserved and retrieval ranks unchanged. These are handwritten, corpus-aware retrieval checks, rather than a held-out relevance benchmark.

Corpus quality review rejected `ons-population-file.xlsx`: although downloaded from the official ONS endpoint, it contained only the cell “Title”. Its original bytes and evidence are preserved under `.local/real-corpus/rejected-corpus/`. It was replaced in the selected 120-file corpus by the actual FRED monthly industrial production series (`INDPRO`), containing monthly observations from 1919 onward plus metadata. The old uploaded node remains in the isolated test database and is excluded from selected-corpus counts. Source diversity is uneven: Markdown favors technical READMEs, images favor NASA, and some CSVs are common public teaching datasets. Vietnamese documents and phone scans are not represented.

Final English-query latency was 2.123 seconds median and 3.038 seconds at p95, measured sequentially through the real API including reranking.

The owned `openlet-real-evaluation` Compose stack and one-off containers were stopped and removed. Corpus files, results, database backups and Docker volumes were preserved. `git diff --check` passed.

## Direct output review after the automated audit

Reading three retained samples directly found additional defects. The earlier structural and text-coverage checks do not establish readable or correctly grouped output.

- **Layer 0, Dijkstra, The Humble Programmer:** the README contains severely corrupted OCR, including “as far as I have unn u en nn”. The rendered second page of the original scan is legible and contains the missing sentence (“been able to trace, I was the first Dutchman in my country”). The successful parse/index state therefore includes materially damaged content. No API calls were used for this inspection.
- **Layer 0, British Columbia related-party declaration:** Yes/No checkbox values and Entity Name/Name/Title/Signature/Date signed labels occur in the CSVs and again as detached Markdown blocks after their table links. The rich-table repair did not eliminate this remaining form duplication. The form is readable but the output is not clean.
- **Layer 1, Bitcoin:** file 09 contains original sections 9 and 10, which is consistent with merging short sections, but file 11 begins with the “Solving for P less than 0.1%” calculation block from the preceding topic before the Conclusion. This is an incoherent section boundary. The generated title and description of the Conclusion file also incorporate that calculation material. Diagram labels are emitted as detached lines after image links, degrading reading flow. Some filenames end mid-word at the slug-length cutoff (e.g. catchin.md).

These samples invalidate a blanket claim that layer 0/1 content is correct. The observed tree shapes pass structural checks; OCR quality, table ownership and semantic section boundaries still need repairs and direct review.

An expanded [direct output review](test-261031-1141-output-quality-review.md) inspected eight additional sources and separates recoverable implementation defects from semantic uncertainty and source characteristics. It found further percentage-formatting, spreadsheet prose segmentation and temporary-name leakage defects.
