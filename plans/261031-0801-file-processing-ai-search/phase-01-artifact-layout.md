---
title: "Phase 1: Artifact Layout and Exporter"
priority: P2
effort: 3d
depends_on: []
---

# Phase 1: Artifact Layout and Exporter

## Objective

Replace the current positional exporter with a 0/1/2-level semantic content layout selected before files are written. Preserve all text, media, and tables, and create a README for every folder. This phase does not call AI or change the publication contract.

## Files

- Modify `/home/qninh/projects/openlet/services/letfs/processor/src/openlet_processor/exporters.py` and `/home/qninh/projects/openlet/services/letfs/processor/src/openlet_processor/convert_child.py`; create `/home/qninh/projects/openlet/services/letfs/processor/src/openlet_processor/text_split.py` as the shared token-estimate/splitting helper.
- Modify `/home/qninh/projects/openlet/services/letfs/processor/src/openlet_processor/activity.py` only if layout configuration must be passed to the parser subprocess; do not mix enrichment into the parser activity.
- Modify `/home/qninh/projects/openlet/services/letfs/processor/pyproject.toml`, `/home/qninh/projects/openlet/services/letfs/processor/uv.lock`, `/home/qninh/projects/openlet/deploy/compose.yaml`, `/home/qninh/projects/openlet/docs/setup.md`, processor fixtures, and processing E2E cases under `/home/qninh/projects/openlet/tests/e2e/`.

## Tasks

- [x] Pin standalone `langchain-text-splitters` and a character-based length function (`ceil(len(text)/4)`, approximate) in `text_split.py`; validate `MIN_LEAF_TOKENS` and `SPLIT_TOKENS` when the worker starts. Reuse this helper for phase 2 sampling and phase 3 chunking without adding LangChain chains, agents, or Document abstractions.
- [x] Separate outline/token-distribution analysis from export. Select one layout for the entire document: level 0 when total text does not exceed `split_tokens` or the outline has no useful boundary; level 1 as the default split layout; level 2 only when two meaningful structural levels exist, most main sections exceed the split threshold, and most have at least two substantive subsections.
- [x] Merge adjacent small sections using `min_leaf_tokens` while preserving original headings and content ownership: preamble belongs to the root README, group introductions belong to the group README, and leaf bodies belong to leaf Markdown. Do not create empty files or duplicate content.
- [x] Structural sections/chapters/parts and sheet folders use `<index>-untitled`, preserving source order. Other generated files use `untitled-<index>.<ext>`, including images and CSV tables. Within each container, maintain the structural counter and independent counters per other file type/extension; never share a counter between images, CSV, and structural nodes. Compute minimal ordinal width for each counter (`1..9`, `01..99`). Place media in the nearest semantic container; do not create `images/`, `text/`, or `tables/` directories. All relative links must resolve before publication.
- [x] Level 0: root `README.md` contains all document content, with independent media/CSV files beside it. Level 1: root README plus Markdown/media leaves. Level 2: root README plus semantic folders, each with its own README and leaves; keep the folder shape even when a group has one leaf.
- [x] Excel always creates one `<index>-untitled` folder per sheet and one README per sheet, including empty sheets. Put all outside-table text in the sheet README, export tables as `untitled-<index>.csv` using the sheet's CSV counter, and preserve sheet name plus cell/table coordinates. Preserve literal formulas or labeled cached evidence when available; do not calculate formulas or interpret merged cells.
- [x] PPTX temporarily exports one root `README.md` with slide boundaries in the body. Remove the current per-slide branch at `services/letfs/processor/src/openlet_processor/exporters.py:39`; do not claim full visual-layout representation.
- [x] Preserve current preflight/resource bounds, subprocess isolation, and output checks at `services/letfs/processor/src/openlet_processor/convert_child.py:24` and `services/letfs/processor/src/openlet_processor/convert_child.py:67`. Parser output continues through the existing uploader/publication path; original bytes are never rewritten.

## Acceptance

- [x] PDF/DOCX fixtures cover levels 0/1/2, wrapper headings, a single long chapter, small-section merging, and independent no-loss/no-duplication inventory checks.
- [x] Excel fixtures cover empty sheets, outside-table prose, singleton/uncovered cells, `untitled-<index>.csv` files, image placement, and provenance; PPTX fixtures prove one README with slide boundaries.
- [x] Mixed-content fixtures prove independent structural/image/CSV counters, both placeholder naming forms, and minimal padding computed separately per counter.
- [x] Every folder has a README, every relative link resolves, and no hard-coded `001` width or `images/` directory remains.
- [x] Existing parser failure/resource behavior, output limits, and original source checksums remain unchanged.

## Validation

```bash
make test-unit SERVICE=processor
uv run --project services/letfs/processor --locked pytest services/letfs/processor/tests -m parser
make test-e2e TEST=processing
```

## Risks and Rollback

- **High:** regrouping loses or duplicates content. Mitigation: produce a source-item-to-output manifest and fail tests unless every item has exactly one owner.
- **Medium:** flattened media links break. Mitigation: build the final placeholder path map before rendering and resolve every target in fixtures.
- Roll back to the previous exporter and regenerate development artifacts as needed. This phase has no database migration and never deletes source bytes.

## Execution Evidence

- Implemented shared character-based token estimates (`ceil(len(text)/4)`) following the user's revised decision; removed the tokenizer dependency and cache setup.
- Layout tests cover PDF/DOCX levels 0/1/2, wrapper headings, tiny-section merging, one long chapter, a single-subsection group, per-container media ownership, structural/media padding, and no-loss text inventories.
- Real parser tests cover PDF OCR, DOCX rich cells, PPTX compatibility content, Excel prose/formulas/empty sheets/images, and unchanged image pixels.
- `make test-e2e TEST=processing` passed after the character-estimate change, including original-byte equality and artifact read-only behavior. The harness removed its containers on exit.
- A scoped simplifier reviewed the exporter and fixed single-subsection introduction ownership. Focused tests and Ruff passed afterward.
