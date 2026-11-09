---
title: Implement Leta persistence and scope discovery
date: 2026-11-08
summary: "Completed domain persistence and continued Phase04 with canonical binding, private storage candidates and current permission-filtered user/Leta scope discovery."
---

# Implement Leta persistence and scope discovery

## Work completed

Reconciled the human-only identity migration with existing upgrade evidence and completed Phase03 persistence/migrations/readiness. Continued Phase04 with private LetFS scope candidate listing, canonical Workspace-only Leta binding, owned TLS/health listener, generated bindings, validated Go clients and one current-rights scope discovery implementation for humans and Leta. Added the public Workspace route and its real client/config/Compose wiring.

## Evidence and corrections

The full Leta suite passed87 tests. Subsequent deadline coverage passed its focused tests. Shared RPC/contracts and independent wheels passed. Workspace current-rights discovery passed real PostgreSQL/SpiceDB cases and one focused real-service E2E journey through Envoy and native LetFS. Required scoped simplification ran clean. Early checks caught protobuf response naming and two test helper/order mistakes; corrected them and reran affected checks.

## Continuation

The19-phase goal remains active: phases01–03 complete, phase04 partial. Continue its seven native Workspace methods, personal-owner grants and acknowledged home/default provisioning using existing authority/discovery helpers. No new user decision is pending. Full engine/runtime/streaming/deployment remains ahead. Preserve the dirty worktree; no commit, push, deployment, paid inference or existing-data reset occurred. See the Phase04 execution report for exact remaining work and final verification. AgentWiki publish skipped.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.

## Native resource continuation

Implemented the remaining seven Workspace native methods and Go/Python clients, exact service/actor admission, canonical home/default provisioning, resource-owner personal grants and direct lifecycle cleanup. Existing WorkspaceChanges/idempotency storage handle ordinary retries; no new table or coordination service was added. Workspace now owns a private TLS/health listener and the existing bootstrap/Compose route supplies its Leta credential. TLS environment names are consistent across the services.

Real SQL/SpiceDB/native tests, actual Temporal timeout/queue tests, shared destination-client/wheel checks and one rebuilt Envoy scope-discovery E2E passed. Scoped review identified five real retry/validation defects, corrected with regressions. The phase04 execution checkpoint contains the current evidence and replaces the earlier partial continuation instructions above. The full19-phase goal remains active; native LetFS text/read implementation follows. No commit, deployment or existing-data mutation occurred.
