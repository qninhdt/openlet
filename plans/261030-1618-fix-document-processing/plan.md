---
title: Repair real-document processing
status: completed
priority: P1
branch: main
tags: [bugfix, processing]
created: 2026-10-30
---

# Repair real-document processing

Status: completed. Scope: Python processor and its existing callers, tests and owning documentation. No schema, workflow, storage protocol or product-limit changes. Results and limitations: [implementation report](../reports/implementation-261030-1618-document-processing-fixes.md).

## Outcome and acceptance

Preserve visible PPTX text/pictures currently hidden in OOXML compatibility branches; write referenced images once per document; process eligible documents within existing worker/output bounds; preserve bounded diagnostics and classify resource failures correctly. Reuse the 23 original public documents under `/tmp/openlet-real-world-ct8qw6sf`, without adding downloaded files or corpus scripts to the repository. Keep atomic artifact publication, original bytes, OCR, section/slide order, readonly children, and existing cancellation/resource cleanup behavior.

## Execution

1. [x] Scout conversion, exporter, supervisor, worker, tests, commands and observed failures.
2. [x] Diagnose installed Docling APIs, OOXML compatibility selection, image decoding and PDF memory behavior; preserve failing regressions before fixes.
3. [x] Apply cause-aligned processor changes with focused tests, retaining size/pixel/output/time limits.
4. [x] Run Python regressions/parser checks, the real-document API corpus, required repository checks and affected workflow/recovery checks.
5. [x] Review final changes, update the smallest owning docs, and record measured before/after results and remaining limits.

Dependencies are sequential. Evidence baseline: `/tmp/openlet-real-world-ct8qw6sf/report.md`, `results.json`, `artifact-audit.json`, `native-iit-comparison.json` and `diagnostics/`. Eighteen operations succeeded, three unexpectedly failed, two correctly exceeded configured limits. Job success alone does not prove content preservation.

## Constraints and rollback

Use pinned dependencies and public APIs where available. Do not implement a replacement Office parser, proxy object bytes, silently omit content, lift safety caps merely to pass, or alter user-selected filesystem/artifact semantics. Back up affected source outside the repository before edits; rollback restores those files and rebuilds the prior image. No database changes are planned. Downloaded inputs and scripts remain temporary; durable test findings belong in `plans/reports/`.

## Investigation result

NIST succeeded under the actual activity worker after bounding PDF pipeline queues and batches. Its original precise allocator cause was not independently established; do not claim that cause as proven.

## Verification results

Deeper DOCX audit confirmed another concrete upstream loss: plain table-cell detection overlooks inline content controls, then python-docx `cell.text` omits their visible characters (`Global` becomes `lobal`, `Place` becomes `lace`). Route these cells through Docling's existing rich-cell walker and verify a multi-cell reproducer plus the same real DOCX inputs. A one-cell table does not reproduce the defect because it follows a different upstream path.

NOAA's prior image decoding failure is repaired. Independent complete conversion now proves its outputs total 355,654,111 bytes, above the unchanged 256 MiB budget. Retain an explicit `RESOURCE_LIMIT`, original bytes and no partial artifacts; do not increase the budget to meet the initial success expectation.

The new focused regressions failed against the prior implementation. All 26 Python tests and `make verify GO=/usr/local/go/bin/go` pass. The first full-worker recheck completed all 23 documents. Processing/ZIP/query-bound/retry-exhaustion/kill-restart acceptance and eight history replays also passed before the additional Word-only fix.

The host rebooted at 19:38 and cleared `/tmp` evidence, including the last unfinished acceptance observation. Final verification persists outside the repository under `/home/qninh/.cache/openlet-document-verification-261030-1940`. The same six public URLs were downloaded again; Apple's SHA-256 matches the original corpus. All six real inputs pass API upload, processing, original-byte comparison, artifact readback and image-reference checks: 504 artifacts and 63 valid image references. Both previously missing Victoria phrases are present; its body-paragraph audit flags fell from two to zero. Apple produced 312 nonempty Markdown files and four valid images, with five independently selected source facts retained. Final four-format/ZIP/query-bound acceptance and six processing/export history replays pass. Owned containers, networks and fresh volumes were removed after collecting logs and database backups.

Purdue contains 633 fallback ink pictures. Correct extraction must honor the existing configurable output bound: the unchanged default of 512 should reject it explicitly, rather than silently publish ten text-only slides. Also verify full extraction separately with a sufficiently large existing configuration; do not lift the default.

The test image reuses the prior pinned image's identical model files because the normal Docker build stalled while re-downloading them. Dependencies are still installed from the same lockfile; no production Dockerfile/model/dependency change is made.
