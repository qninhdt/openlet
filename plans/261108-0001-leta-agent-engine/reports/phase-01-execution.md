# Phase 01 execution evidence

Implemented on 2026-11-08 in the existing dev worktree. Implementation remains in progress for the full 19-phase plan; this report covers foundation only.

## Delivered

- apps/leta is an independent uv/pnpm package. Engine dependencies are app-owned, pinned in pyproject.toml and uv.lock; shared Python does not acquire them.
- Strict model catalog and model_id/reasoning_effort resolution preserve explicit null and Leti inheritance. Configuration validates endpoints, secret-file precedence and TLS/development transport. Secrets are excluded from representations/errors.
- FastAPI API factory provides authenticated /v1 boundary and /live, /ready. AsyncExitStack owns database/Redis/native/authz/telemetry resources and closes them on partial startup, cancellation and shutdown. Redis is mandatory.
- Shared Temporal connect now accepts TLS explicitly. No domain schema, product endpoint, fake Workflow, alternate engine or placeholder worker was added. The real worker entrypoint is delivered with phase09 registrations; this prevents dead scaffolding.
- Independent wheel test now builds and imports Leta alongside shared/ingest wheels without repository PYTHONPATH.

## Resolved versions

LangChain1.4.8, LangGraph1.2.19, PostgreSQL saver3.2.0, Temporal1.35.0, Mirage0.0.8, Monty1.4.0, AG-UI adapter0.0.47, OpenRouter adapter0.2.9, FastAPI0.162.2, Uvicorn0.54.0, psycopg3.3.8 and Redis client8.1.0 resolve together. The engine requires langchain-core1.7.6 (previous lock1.7.3); no unrelated direct pins changed.

Integration fixtures own disposable PostgreSQL18.6 and Redis8.2.3 containers with pinned digests in conftest.py. They never load development DSNs. The Temporal fixture owns SDK time-skipping environment, not persistent restart evidence.

## Actual compatibility results

- create_agent with async PostgreSQL saver and durability="sync": a tool independently reads its persisted assistant tool call before inserting a real SQL effect. Reopening saver and resuming preserves typed messages/cursor and does not repeat the saved tool result/effect.
- Public async before-model middleware and SummarizationMiddleware compact typed working messages and reload inbox_cursor from the same checkpoint.
- Actual Mirage Workspace/tool dispatch and shell cat/ls read named and original-file-ID nested artifacts while the original source remains FileType.FILE. The fixture models backend ID resolution; real LetFS repeats this proof in phase08.
- Actual Monty reads only mounted content; host-file access, host-only environment and socket import are denied. Redis file/index caches produce real backend keys. An actual AG-UI event round-trips inside the accepted agent/run envelope through one Redis Stream.
- A sandboxed SDK Workflow executes Update-with-Start and current history/continue-as-new APIs.

One integration correction matters downstream: Mirage network=False also blocks its Redis cache connections. Use its supported backend host:port allowlist; the compatibility test allows only its owned Redis address, while Monty remains sandboxed. Phase08 must include LetFS/Redis backend destinations without exposing host credentials to Python or permitting unrestricted command egress. Python -c also requires an EXEC-capable virtual root; the fixture uses an empty RAM root plus announced mounts, never a host disk mount.

## Verification

- Python3.13.12: all41 Leta tests passed after final review.
- Python3.12: original35 tests passed including real compatibility gates; after six validation regression cases were added, all36 config/lifecycle tests passed again. Unchanged integration tests were not rerun on3.12.
- Shared Python:30 nonintegration tests passed; independent wheel integration test passed.
- Ruff check/format passed for all new app Python and modified shared files; uv lock --check passed; uv build --package leta built wheel/sdist; python -m leta.api --help passed.
- pnpm contracts:check passed after adding the installed /usr/local/go/bin to the command PATH. The first attempt failed because the shell PATH omitted Go; no contract defect was hidden.
- Required ak-cook simplification review ran using gpt-6.1-sol/xhigh. It found no useful structural simplification; six new failing-before-fix cases led to rejecting malformed provider URLs and blank/multiline credentials. Focused checks passed after correction.
- git diff --check passed. All owned test containers and SDK servers were closed; no development service was started or stopped.

No paid inference, persistent Temporal restart claim, live provider call, deployment, commit or source-data migration occurred. Later phases still own domain behavior and system acceptance.

## Execution constraints after planning

The user explicitly requested no production-data backup, backward compatibility, legacy code or dead code. Phase02 therefore replaces initial development schemas/contracts directly instead of introducing a conversion CLI, transitional policy or legacy identity support. Existing general recovery remains a product capability in phase18; it is not a prerequisite to these development edits.
