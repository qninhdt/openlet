# Heading-depth comparison — 2026-10-30

No production code or configuration was changed. Six real public documents are the same inputs used in the final processing verification. This measures file segmentation, not parser accuracy or speed.

## Definitions and result

- Current: split only at the shallowest Docling section-heading level present in each document.
- Markdown H1/H2 cap: section-header level 1 only, because the installed serializer emits `SectionHeaderItem.level + 1` hash marks. Document titles stay in the first section. This leaves all 440 Markdown files unchanged.
- Docling levels 1–2: split at section-heading levels 1 and 2, emitted as Markdown H2/H3. This creates 542 Markdown files, 102 more (+23.2%). Images are outside this comparison and remain 64.

## Per-document counts and median lengths

Lengths count Unicode characters including Markdown syntax, whitespace and table padding. Percentiles use linear interpolation.

| Document | Current Markdown | Docling 1–2 Markdown | Current median chars | Docling 1–2 median chars |
|---|---:|---:|---:|---:|
| victoria-education-annual-report.docx | 13 | 113 | 9,753.0 | 2,818.0 |
| productivity-commission-annual-report.docx | 99 | 99 | 976.0 | 976.0 |
| victoria-education-additional-information.docx | 14 | 16 | 2,057.0 | 1,423.0 |
| uk-equivalence-guidance.docx | 1 | 1 | 36,194.0 | 36,194.0 |
| uk-clinical-investigations-guidance.docx | 1 | 1 | 9,344.0 | 9,344.0 |
| apple-annual-report-2024.pdf | 312 | 312 | 561.5 | 561.5 |

## Aggregate length distribution

| Metric | Current | Docling levels 1–2 |
|---|---:|---:|
| Markdown files | 440.0 | 542.0 |
| P25 characters | 157.0 | 183.5 |
| Median characters | 734.5 | 867.0 |
| P75 characters | 2,081.0 | 2,840.5 |
| P90 characters | 5,266.6 | 6,999.4 |
| P95 characters | 11,099.0 | 15,588.3 |
| Maximum characters | 780,694.0 | 556,656.0 |

| Length in characters | Current files | Docling 1–2 files |
|---|---:|---:|
| 0 | 5 (1.1%) | 5 (0.9%) |
| 1-199 | 123 (28.0%) | 135 (24.9%) |
| 200-499 | 64 (14.5%) | 72 (13.3%) |
| 500-1999 | 134 (30.5%) | 156 (28.8%) |
| 2000-9999 | 91 (20.7%) | 135 (24.9%) |
| >=10000 | 23 (5.2%) | 39 (7.2%) |

Files shorter than 500 characters increase from 192 to 212; their share falls from 43.6% to 39.1% because the denominator grows. The five existing empty DOCX files remain. Limiting heading depth alone does not repair over-segmentation in the current PDF configuration.

## Evidence and limits

- Five DOCX inputs were parsed and re-exported with the same pinned image in an isolated container, without network access. Every current-output Markdown filename and SHA-256 matched the previously downloaded API artifacts. Both candidate policies retained the before-output token multiset for all five documents.
- Apple uses the already verified 312 nonempty Markdown outputs. The installed PDF reading-order model creates section headings with the default level 1. `heading_hierarchy_options.enabled` is false, and the disabled hierarchy stage returns the document unchanged. All emitted section headers are H2. Selecting levels 1 or levels 1–2 therefore chooses exactly the same boundaries; lengths are identical. The redundant new PDF conversion was stopped once this identity was verified, and was not counted as another successful parser run.
- Docling has an existing optional heading-hierarchy stage using bookmarks, numbering and style. It was not enabled or evaluated here; such a run would be a different experiment.
- Total raw characters change slightly at newly introduced file boundaries due to export whitespace trimming; token multisets are preserved. Character counts include potentially large Markdown table padding and do not equal prose or token lengths.
- Scripts, per-file lengths, rerendered DOCX outputs and pipeline source evidence are outside the repository at `/home/qninh/.cache/openlet-heading-comparison-261030-2020`. See `comparison.json`, `results.json`, `pdf-level-proof.json` and `run.log`.
- The owned comparison container was stopped and removed. No database or service was changed.
