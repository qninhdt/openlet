# Service boundaries and shared packages

Status: superseded by [accepted final decision](../261103-1348-service-refactor/tmp-refactor-decision.md). This earlier proposal is historical; its app/jobs choices are not implementation authority.

## Outcome

Public HTTP and private gRPC have independent adapters. Business operations use native language values and transport-independent errors. Each service owns its SQL and Temporal execution. Go and Python share protobuf contracts, not database models or business implementation.

## Constraints and non-goals

Preserve existing features, authorization, transactional/accounting invariants, bounded transfers, cancellation, retries and recovery. The workspace started clean. No database schema/data changes, deployment, dependency upgrades, generic repository framework, new services or public feature additions. Keep Go/uv/pnpm commands usable. Existing historical workflow histories may need regeneration when cross-service execution changes; no live migration is requested for this greenfield project.

## Design and trade-offs

Prefer cohesive feature packages with SQL next to operations, explicit transport/http and transport/grpc, service-owned jobs, and clients for external adapters. A full domain/application/repository hierarchy would require many forwarding interfaces without independent implementations; it fails first on maintenance cost at current feature size. Merely moving directories leaves HTTP calling gRPC and protobuf in Python activities, so it fails the requested isolation. Recommended approach retains real transaction boundaries while moving orchestration into application services where needed. Better approaches: none; transport isolation with pragmatic feature packages fits the observed code.

## Phases and dependencies

1. Scout all applications, contracts, shared packages and infrastructure; record evidence in reports. In progress.
2. Establish consistent layout, neutral errors and shared HTTP/RPC support; isolate Go HTTP from gRPC. Depends on 1.
3. Isolate Python processing from protobuf, remove duplicate shared infrastructure, and use gRPC for cross-service communication. Depends on 2.
4. Enforce import boundaries, update docs and run unit, workflow, integration and API checks; review the full change. Depends on 2–3.

## Acceptance

- All four applications adopt a documented coherent structure.
- HTTP does not depend on a gRPC server implementation or generated RPC messages.
- Feature/application code does not import grpc/status/codes or generated application contracts.
- Python processing consumes native models through explicit client methods.
- Only HTTP is routed at public ingress; internal gRPC remains authenticated.
- Shared packages contain contracts and infrastructure only; no shared service persistence models.
- Existing behavioral checks and new architecture regression checks pass, with unavailable external-provider checks explicitly recorded.

## Validation and rollback

Use native focused Go/Python tests first, then pnpm build/check/test, workflow/integration tests and fresh API journeys as the environment permits. No live writers or databases are modified. Source rollback is git restore of this isolated clean-start change after user review; never reset databases or remove volumes.
