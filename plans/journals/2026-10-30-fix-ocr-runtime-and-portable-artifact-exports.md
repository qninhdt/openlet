---
title: Fix OCR runtime and portable artifact exports
date: 2026-10-30
summary: "Install Docling RapidOCR runtime, preserve picture-child section boundaries, and validate all twenty real documents."
---

# Fix OCR runtime and portable artifact exports

## Cause and repair

The pinned Docling installation configured RapidOCR without its optional ONNX runtime. Three real PDFs failed as invalid documents. Enable `docling[rapidocr]==2.144.0`, regenerate `uv.lock`, and import the actual runtime before connecting the activity worker to Temporal.

Markdown image links used absolute worker scratch paths. Pass Docling a relative `Path("images")` so published links resolve inside the hybrid artifact tree.

After OCR worked, the handbook exposed another exporter bug: section indices omitted picture children, while Docling's serializer includes them. Match enumeration and serialization with `traverse_pictures=True`. All three regressions failed before their corresponding repairs and pass afterward. No workflow, database, upload protocol, model selection, or formula-enrichment change was needed.

## Verification

- Native Python suite: 16 passed, including generated image-only PDF OCR, relative image resolution, picture-child text and section boundaries, and fail-fast ordering before Temporal connect.
- Final `make verify`: passed formatting, Go/Rust/Python unit checks, vet, clippy, lint, configuration and contract checks. Four upstream Docling/Pydantic deprecation warnings remain in the full parser run.
- Rebuilt activity image: `sha256:f643ea2a7b492acd6dd690529371f3fe607049f6a083b814b870275d9a72a76e`.
- Final isolated Compose `TestProcessing`: passed four formats, actual relative-path image retrieval/pixels, readonly artifacts, original bytes, and bypass cases. Fresh four-format ProcessFile histories passed Rust replay.
- Reused the same twenty independently downloaded documents: 5 PDF, 5 PPTX, 5 XLSX, 5 DOCX. All 20 processed, all original bytes matched, and 69 artifacts were retrieved through APIs. Independent checks found zero broken links across 15 relative image references, preserved all 249 spreadsheet cell values (including cached formula results), and matched five Office image outputs pixel-for-pixel with their embedded sources.
- The handbook's raw-PDF word recall improved from approximately 63% to 99.8% after the section fix. For the multilingual newspaper, a direct Docling full export comparison found no native output words missing from the split files; raw PDF concatenates words, so raw word recall alone is not a content-loss oracle.
- Simplifier/review found no additional changes necessary. All temporary test containers, networks and fresh volumes were removed.

## Limits and evidence

Downloaded documents, corpus scripts, output trees, detailed results, independent audit, logs, and generated histories remain outside the repository under `/tmp/openlet-internet-docs-final-rupfoqy0`. Pre-fix evidence remains in `/tmp/openlet-internet-docs-k2odhkd6`; the intermediate run in `/tmp/openlet-internet-docs-fixed-b6hc3zvs` exposed the section issue. `/tmp` is temporary storage.

These checks used local SeaweedFS and a local authentication issuer. Live R2 and Clerk were not retested. PDF formula enrichment remains intentionally disabled. No production deployment, commit, or publication was performed.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
