---
title: Upgrade Openlet dependencies and runtimes
date: 2026-11-08
summary: Refresh repository versions and resolve Instructor and OpenAPI compatibility.
---

# Upgrade Openlet dependencies and runtimes

## Changes

Upgraded repository Python, Go dependencies, JavaScript tooling, container images and CI tools against live upstream metadata. Preserved pre-existing identity and Leta work; feature implementation remains paused.

## Compatibility

The user selected Python 3.14.10. Instructor 1.17.0 remains with OpenAI 3.3.0 because newer OpenAI releases conflict on jiter. Native JSON Schema is handled by Instructor. Generated HTTP errors reuse the canonical Problem JSON contract after the OpenAPI generator upgrade.

## Evidence

See [the upgrade report](../reports/implementation-261108-dependency-upgrade.md) and [independent review](../reports/review-261108-1322-dependency-upgrade.md). All 35 API E2E tests passed. The report tracks the final race-suite result and other verification.

## Boundaries

No commit, deployment, existing database mutation, host Docker restart or paid-provider inference. AgentWiki publish skipped.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
