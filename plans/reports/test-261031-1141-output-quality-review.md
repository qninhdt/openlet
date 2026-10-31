# Direct artifact quality review

Reviewed locally without AI requests. This review reads retained output and selected original evidence; it does not change parser behavior.

## Scope

Eleven sources were read directly: British Columbia related-party declaration, Dijkstra's The Humble Programmer, Bitcoin, IRS Form 1040, WHO Hand Hygiene, NIST AI RMF, FSS survey appendix, Bath safety handbook, FRED INDPRO, ONS BICS, and UK electricity Table 5.2. The first three were inspected in the preceding sample review; eight were added here. Selected source evidence included a rendered Dijkstra scan page, original DOCX chart XML, Bath paragraph styles, and WHO image crops.

## Concrete defects with recoverable evidence

| Finding | Direct evidence | Assessment |
| --- | --- | --- |
| Form/table text duplicated into Markdown | British Columbia CSVs already contain Yes/No controls and signature labels; README repeats them as detached blocks. FSS survey table labels are similarly repeated after the CSV link. | Export ownership defect. Can fix without semantic inference. |
| Chart percentage formatting lost | FSS chart1.xml caches 0.53, 0.9, 0.93, 0.97 and declares formatCode 0%. Output labels the column Percentage but emits those fractions without the format. | Preserve the source format or explicitly identify proportions. The source contains the necessary information. |
| Prose converted into table artifacts | ONS BICS Read me sheet emits CSVs for notes and a one-column contact email block at A17:A18. FRED README metadata is also split into CSVs. | Table-region detection is too broad in these examples. Single-column structures can be ambiguous generally, but these obvious prose blocks are improvable and conflict with the intended prose-in-README behavior. |
| Placeholder names leak into generated metadata | NIST produces 03-table-of-contents-for-untitled-csv.md. UK electricity Cover Sheet context explicitly mentions untitled-1.csv despite final renamed children. | Generated text uses temporary implementation names. Can remove that evidence from generation and validate output. This is not missing source meaning. |
| Known metadata is lost on the way to root | FRED sheet context contains monthly seasonally adjusted industrial production, 2017=100; root context says units and date range are not specified. Actual observations include dates. | Evidence/summarization loss. Forward or derive required facts if the root is expected to include them. A bounded summary will still omit some details by design. |
| Empty heading and mid-word slugs | Bath first section begins with an empty ##. Bitcoin and Bath filenames end mid-word at the slug length limit. | Deterministic serialization/naming cleanup. |
| Noisy dot leaders | IRS 1040 README emits hundreds of isolated dot lines between labels and field numbers. | Presentation noise can be reduced using layout evidence. Do not strip decimal points or meaningful dotted syntax globally. |

## Problems that can improve but cannot be guaranteed on arbitrary documents

| Finding | Direct evidence | Where uncertainty comes from |
| --- | --- | --- |
| Wrong image descriptions | WHO image named line-drawing-of-a-person-washing-a-dish.png shows hands under a tap. illustration-of-a-mechanical-assembly.png also shows handwashing under a tap. | Cropped line art lacks surrounding captions; vision inference is fallible. These two labels are wrong, not equally valid readings. Parent topic and nearby captions can improve them, without a universal correctness guarantee. |
| Reading order and image-caption association | WHO hand-hygiene steps, numbers and captions are interleaved; the tail instructions about towel/faucet appear after a Hand care section. IRS dependents and digital-asset text interleave. | PDF uses two-dimensional layout. A layout-aware reader can improve ordering; some layouts have no single canonical linear order. Preserve page/crop evidence instead of promising a faithful form in plain Markdown. |
| OCR corruption on scans | Dijkstra source page 2 is visibly legible; output loses words and emits random-looking fragments. | Better OCR/rasterization may recover this source. Inspection did not establish the cause. No OCR method can recover genuinely missing or illegible marks reliably; this sample is not proven irrecoverable. |
| Semantic section boundaries | Bitcoin Conclusion file begins with calculation output from the previous topic. File 09 combines original sections 9 and 10. | The calculation attachment is a concrete bad boundary that source order/headings can improve. Combining short neighboring sections is consistent with the design. For weak or inconsistent headings, choosing the best grouping is partly subjective. |
| Broad or weak titles | Isolated numeric fragments, covers and contents sometimes receive generic or navigation-focused titles. | Title choice has several valid answers, especially when the fragment has little local meaning. Better parent evidence helps; missing source meaning cannot be inferred reliably. |
| Table-versus-prose ambiguity | Some one-column lists are useful datasets; others are notes. Spreadsheet blocks can mix titles, values, footnotes and headings. | A generic detector cannot always infer author intent. Explicitly preserve ambiguous material rather than silently dropping it. This does not excuse exporting the obvious ONS contact block as a dataset. |

## Source characteristics that should be preserved

- Bath includes department-name placeholders and authoring instructions. Source paragraphs use TOCHeading for instruction text. Preserving the placeholders is correct; treating every styled paragraph as a semantic chapter is not reliable.
- Original page numbers in tables of contents refer to the source document. They are not broken artifact links. Replacing them with artifact navigation is a product choice.
- Diagram labels can be useful searchable text even when an image is retained. Their detached presentation is poor, but unconditional deduplication against images would lose searchable evidence.
- Blank form cells and missing department names contain no values to recover. Metadata should identify the source as a template rather than invent an organization or completed responses.

## Conclusion

No inspected defect has been demonstrated to be inherently impossible to improve. Deterministic ownership, formatting, naming and evidence-loss bugs should be fixed. Semantic interpretation, OCR, layout linearization and title quality need best-effort handling and preservation of original evidence; a universal exact answer is unavailable for some inputs. Truly absent source information cannot be reconstructed as fact.

## Evidence

Retained output is under `.local/real-corpus/results/artifacts/{group}/{original-name}/`. Originals and provenance are in `.local/real-corpus/files/` and `manifest.json`. Concrete sample paths:

- `docx/fss-research-fss-guidance-research-report-appendix_1.docx/README.md`
- `pdf/who-hand-hygiene.pdf/README.md`
- `pdf/irs-1040.pdf/README.md`
- `pdf/nist-ai-risk-management.pdf/03-table-of-contents-for-untitled-csv.md`
- `docx/bath-safety-health-and-safety-handbook-2026-27-2-.docx/01-department-health-and-safety-handbook-template.md`
- `xlsx/ons-business-file.xlsx/01-business-insights-and-conditions-survey-data-wave-166/README.md`
- `xlsx/us-industrial-production-fredgraph.xlsx/README.md`

Review limitations: these are eleven selected samples, not a manual review of all 120 sources. No parser repairs, new OCR runs or AI regeneration were performed in this review.
