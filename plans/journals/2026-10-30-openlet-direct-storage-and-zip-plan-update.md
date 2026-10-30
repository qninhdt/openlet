---
title: Openlet direct storage and ZIP plan update
date: 2026-10-30
summary: "Expanded the existing implementation plan to five pending phases for direct storage, artifacts, processing, ZIP export and recovery."
---

# Openlet direct storage and ZIP plan update

Updated the existing artifact-processing plan after the user accepted caller-selected inline/object transport and ZIP export. Object bytes transfer directly with S3; inline remains bounded bytea. Removed physical staging-to-final copying and backend storage reclassification requirements.

Added direct-storage and ZIP phases, preserving hybrid lifecycle, attempt fencing and quota invariants. Normal folder exports stop at files and exclude attached artifacts; explicit artifact exports use the same archive worker. One ProcessFile workflow/activity and one ExportArchive workflow/activity remain the background transforms.

Validated plan structure, thirteen local links, sequential dependencies and seventy-five existing source anchors. All ninety-nine phase tasks and five acceptance items remain pending. Runtime/provider checks were not run. Start implementation at the direct-storage phase when requested; recheck disk before builds/models/containers.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
