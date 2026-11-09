# Service contracts and source evidence

Current planning baseline: [accepted design](../design-contract.md), [human migration](../phase-02-user-agent-migration.md) and [Workspace resource interfaces](../phase-04-workspace-resource-access-and-scope-view.md). All final user reviews are incorporated. This report distinguishes inspected current code from proposed contracts; no migration/service/provider experiment ran while writing it.

## Inspected code and consequences

| Current source | Observed contract | Required change |
| --- | --- | --- |
| apps/account/migrations/0001_initial.sql and internal/account/{store,service,relations}.go | Mixed accounts include managed-agent ownership and self/owner tuples. | Human-only users preserving UUIDs; remove managed account APIs/Temporal and owner/type fields. Existing package/deployment name may remain. |
| packages/contracts/proto/openlet_api/account/v1/account.proto | Workspace-only Account summaries/verified-email lookups. | Human UserSummary/GetUserSummaries without bot type/owner. Generate both language consumers. Do not add EnsureManagedAccount. |
| apps/workspace/internal/workspace/service.go | Membership admission/removal assumes account identity. | Migrate human fields/callers to user; do not admit Leta as member or role. |
| apps/workspace/internal/workspace/relations.go | Owns scope defaults/grants; rebuild preserves discretionary direct state. | Typed user/leta subjects, ordinary resource home/defaults, owner-approved foreign access and exact received-grant cleanup. Preserve absent/revoked grants. |
| apps/workspace/internal/temporal/relationships.go | WorkspaceChanges serializes updates; Mutate currently allocates a fresh key. | Preserve supplied ordinary retry key; no permanent command ledger/infinite retention. |
| apps/workspace/internal/workspace/mutation_receipt.go | Existing idempotency_keys with ordinary completion expiry. | Reuse existing mechanism/retention; MutationReceipt is a Go representation, not a new receipt table. |
| apps/workspace/internal/temporal/deletion.go | Workspace teardown is serialized and currently knows only existing storage/member resources. | Stop canonical Leta resources before storage; admitted callbacks must not enqueue back into the held WorkspaceChanges lock. |
| apps/letfs/internal/filesystem/provisioning.go and deletion.go | Ordinary independent scopes; deletion enumeration has lifecycle effects. | Reuse CreateScopes; add private read-only candidate ListScopes using existing index for user/Leta accessible views. |
| packages/go/authz/client.go | Fully consistent BulkCheck validates identity/order and accepts up to100 resources per action. | Page/filter candidates with separate bounded metadata/content/write checks. |
| packages/contracts/authz/schema.zed | Existing mixed account policy and exact schema verification. | Coordinated user/leta policy migration, create_leta, creator-gated resource/home read; no arbitrary rolling schema overwrite. |
| packages/python/src/openlet/{rpc,identity,authz}.py and Go counterparts | Shared authenticated RPC/actor/gateway utilities. | Closed user/leta actors, mutually exclusive trusted headers, exact service/method delegation, human-only gateway. |
| packages/python/tests/test_wheel.py | Shared wheel owns generated bindings. | Extend generated Workspace/Leta/LetFS consumers; no app-local generated duplicates. |
| packages/python/pyproject.toml and root pyproject.toml | Supported Python3.12–3.13, Temporal1.35.0. | Add app-owned Leta dependencies and verify compatible lock. |
| infra/compose/dev.yaml | PostgreSQL18.6, Temporal1.32.1; no existing Redis deployment. | Test against actual pins; phase18 owns required private Redis and service wiring. |

CodeGraph was consulted before indexed-code exploration in the contributing reviews. Paths/symbols are source evidence, not assertions that proposed methods already exist.

## Proposed owning interfaces

Phase04 defines exact fields/actor rules for WorkspaceService GetWorkspace, ListMembers, ListAccessibleScopes, EnsureLetaHomeAccess, ResolvePersonalScope, ChangeScopeAccess and CleanupLetaAccess. LetaService GetLetaBinding is a narrow Workspace-only canonical read. Phase17 adds ListWorkspaceLeta/StopLetaForWorkspaceDeletion to existing teardown; no additional Workflow type.

Normal native actor is verified user or root Leta. Leti borrows root subject plus backend box-root restriction. Actor-free calls are only explicitly admitted service methods such as canonical binding and narrow deleting-workspace status; they do not establish a general authorization bypass. Browser payloads cannot choose actor.

Workspace's private LetFS ListScopes supplies candidate root metadata; generic public /v1/workspaces/{workspace_id}/scopes serves authenticated humans as well as authorized Leta inspection. New root storage is ordinary scope/home_of plus root editor/shared editor. Foreign personal approval grants viewer/editor to leta:L under the exact human resource owner. No creator personal default, creator foreign access inheritance or bot membership.

Phase02 owns humans-only users, trusted Clerk claim openlet_user_id/x-openlet-user-id and mutually exclusive native x-openlet-leta-id. Physical apps/account, ACCOUNT_RPC_ADDRESS and private AccountService descriptor may remain to avoid needless deployment renaming.

## Foundation and empirical gates

Phase01 pins LangChain1.4.8/create_agent, LangGraph1.2.19, PostgreSQL saver3.2.0, Temporal1.35.0, Mirage0.0.8/Monty1.4.0, AG-UI adapter0.0.47 and langchain-openrouter0.2.9 as inspected anchors. Exact uv resolution and public API compatibility remain implementation gates, not completed experiments.

That early fixture must prove async runtime with sync checkpoint durability, typed input/cursor recovery, public compaction, Mirage source FILE plus named/original-ID nested artifact paths, Monty isolation, Redis backend/cache hooks and event serialization. Phase08 repeats filesystem behavior with actual LetFS. Actual query/default-planner GIN benefit, native scheduling and full restore have owning later gates.

Phase18 integrates existing Compose/bootstrap/gateway/CI/recovery: one API/worker image, two task queues, dedicated domain/checkpoint DB, required private Redis, exact caller credentials and coordinated schema/claim rollout. No production data inventory or conversion has been performed. Existing managed rows, if any, require explicit disposition before a destructive migration; preserve human IDs and real grants.
