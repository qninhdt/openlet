---
title: Implement native literal search and validate default GIN plans
date: 2026-11-08
summary: "Complete Leta phase07 with bounded unary search, actual PostgreSQL planner evidence and native/Mirage contract checks."
---

# Implement native literal search and validate default GIN plans

## What happened

Implemented root-restricted TextSearch over live small TEXT and blob metadata, preserving original candidate lines. Added transactional pg_trgm GIN, protobuf/gRPC, typed Go/Python clients and precise no-partial response limits. The first benchmark exposed a quadratic nested-loop plan and timed out; the real SQL now avoids a redundant kind filter and irrelevant TEXT child lookups. Final default-planner experiment passed with three selective document corpora; high-entropy logs correctly kept scans.

## Evidence and trade-offs

Rare full-scope medians improved98.718→6.106ms,94.717→3.016ms and363.772→25.671ms. The log index occupied154% of logical text; controlled16-row writer statements slowed roughly2–5×. Raw plans are gzip JSON in the plan reports, with failing original-query evidence preserved. Full LetFS integration race suite, unit/client/contracts/vet and51 shared Python tests passed. Actual pinned Mirage command-hook differential tests passed2 cases; these isolate the library from the native service and do not claim phase08 adapter integration.

## Continue

Seven of nineteen phases complete. Implement the complete invocation Mirage adapter, current scope discovery, required Redis FRESH authorization/token checks, all native hooks and tools. Repeat named/source-ID FILE artifact paths with real native LetFS and Redis. No backup prerequisite, legacy path, production reset, commit, deployment or paid inference. All owned test processes/containers exited; user-owned lab services remain.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
