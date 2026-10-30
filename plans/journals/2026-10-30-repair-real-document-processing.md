---
title: Repair real-document processing
date: 2026-10-30
summary: "Preserve Office content, bound PDF memory, and verify real-file artifact readback."
---

# Repair real-document processing

## What happened

Real documents exposed repeated whole-document image encoding, large PDF pipeline queues, PowerPoint compatibility shapes skipped by python-pptx, and Word content controls misclassified as plain table cells. The processor now reuses Docling's existing walkers, writes each image once, bounds stage batches, and reports typed failures without logging document text.

## Verification

Twenty-six Python tests and make verify passed. The original 23-file recheck, processing/ZIP/recovery acceptance and history replay were recorded before a host reboot erased temporary evidence. Final verification was rebuilt outside the repository under /home/qninh/.cache/openlet-document-verification-261030-1940. All six final real PDF/DOCX journeys passed with unchanged originals, 504 retrieved artifacts and 63 valid image references. The two lost Victoria phrases are present; Apple produced 312 nonempty Markdown files and four valid images. Current processing/ZIP acceptance and six history replays passed. Owned processes and disposable infrastructure were cleaned up after backups.

## Decisions and limits

Keep the existing 512-entry and 256 MiB output budgets: Purdue and NOAA explicitly exceed them, rather than succeeding with missing artifacts. Remaining Docling layout/footnote comparison flags and five empty DOCX table-heading sections are documented in plans/reports/implementation-261030-1618-document-processing-fixes.md. Live R2/Clerk and full visual equivalence were not rechecked. AgentWiki publish skipped; this journal stays local.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
