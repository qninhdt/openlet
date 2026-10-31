# Change Notes

Proposals for further investigation; not implemented.

## Onboarding and workspace creation

- Replace onboarding's internal HTTP create/status calls and polling with a direct Temporal child workflow call to the existing `CreateWorkspace` workflow.
- Keep workspace provisioning owned and executed by the workspace service on `openlet-workspace`; onboarding waits for the child result before publishing the Clerk user ID and completing.
- Use an explicit workflow name and input/output contract across services, without importing workspace implementation code.
- Preserve stable workflow IDs and idempotency; review parent-close/cancellation behavior and compatibility with existing workflow histories before implementation.

## Workspace and filesystem deletion

- Replace `DeleteWorkspace`'s repeated internal HTTP delete calls with a direct child call to the existing `DeleteFilesystem` workflow on the letfs worker (`openlet-letfs`).
- Await each filesystem deletion before advancing the workspace deletion cursor; preserve idempotency, recovery, and continued cleanup after deletion admission.
- Review the Go/Rust payload contract, existing executions, parent-close/cancellation policy, and history compatibility before implementation.

## Scope

- Reuse existing workflows; no new workflows are proposed.
- Keep filesystem creation and short bucket/filesystem RPCs unchanged.
- Keep file processing after copy independent; copy completion does not wait for processing.
