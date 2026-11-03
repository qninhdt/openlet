# Go services simplification report

## Delivered

- Added native shared Go clients in `packages/go/clients/account`, `workspace`, and `letfs`; shared clients depend only on generated contracts and shared transport/error packages.
- Letfs now has native DTOs and full current RPC-family coverage: storage administration; filesystem reads and mutations; path resolution and batch stat; copy and processing; trash; uploads; downloads and archive streaming; lexical/semantic search; and the complete parse, enrichment, index, and output-upload ingest lifecycle.
- Removed Account/Workspace app-local cross-service client implementations. Workspace maps its internal storage model at the business boundary instead of leaking it into the letfs client.
- Rewired Account onboarding from a cross-service child workflow to an owner-local Activity that calls the shared Workspace gRPC client and polls the durable Workspace admission result.
- Added Workspace's authenticated administration gRPC server, health service, listener/TLS configuration, Account credential allowlist, and Account-side dialing.
- Rewired HTTP handlers, Temporal Activities, and server composition through `user.Service` and `workspace.Service`; retained owner-local Workspace child workflow for durable deletion.
- Replaced duplicated Temporal error/tracing setup with `packages/go/temporal`, and rewrote workflow tests around owner-local activities instead of obsolete remote Temporal bridges.

## Verification

Passed:

- `go test ./...` in Account, Workspace, and `packages/go`.
- `go test -tags workflow ./internal/temporal -count=1` in Account and Workspace.
- `go vet -tags integration ./...` and `go build ./cmd/server` in Account and Workspace.
- Integration-tag compile for both applications (`go test -tags integration -run '^$' ./...`).
- Live Docker-backed Account and Workspace integration suites (`go test -tags integration ./...`).
- `git diff --check` for owned paths.

## Final controller verification

- Root composition/config supplies Workspace RPC port 9090, `ACCOUNT_SERVICE_TOKEN`, `WORKSPACE_RPC_ADDRESS`, and transport settings in dev/E2E.
- Full native integration passed across all modules. The final 33-test API suite passed with current sources, including HTTP-only ingress, internal native gRPC, revocation and independent owner workflow recovery.
- Fresh Account, Workspace and letfs histories from that API run replayed successfully: all three native replay targets passed.

Status: DONE
Summary: Account and Workspace use native shared gRPC clients and owner-local durable workflows; composition, transport, integration and fresh-history replay are verified.
Concerns/Blockers: Live external-provider acceptance remains an operational check.
