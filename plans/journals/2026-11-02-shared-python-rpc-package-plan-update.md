---
title: Shared Python RPC package plan update
date: 2026-11-02
summary: Moved planned Python codegen to an independent shared package and propagated packaging and cutover gates.
---

# Shared Python RPC package plan update

## What changed

Updated plans/261102-1059-go-grpc-filesystem-authorization after user approval. Generated Python messages, client stubs and server interfaces belong to packages/python/src/openlet_api in an independent openlet-python wheel, rather than the ingest app. The contracts remain in packages/contracts; future Python services can consume or implement their own RPC contracts without importing ingest.

## Integration and checks

Phases 1/2 own shared-wheel proof, uv workspace/dependency registration, Turbo ordering and Docker/CI inputs. Phase 5 consumes the package; Phase 6 renames ingest without moving codegen. Verification requires installation outside the checkout, no app-vendored stubs and a real generated client/server RPC. Handwritten shared infrastructure requires a concrete common need.

Plan validate/parse and the whole-plan links/fences/whitespace/dependencies/stale-target sweep passed. All seven phases remain pending with 65 remaining phase tasks. No application code, infrastructure or data changed; codegen, wheel and runtime tests remain implementation gates. Original review reports remain history. AgentWiki publish skipped; local journal only.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
