# Shared refactor review

Status: DONE

## Findings

### Medium — unmapped gRPC codes decode as `apperr.None`

`packages/go/rpc/errors.go:111` indexes `kinds` without checking whether the status code exists. Codes such as `DataLoss`, `NotFound` alternatives like `Unimplemented` are partly covered, but any unlisted code becomes the zero value `apperr.None` while carrying an `INTERNAL` reason. This violates the native error contract and changes behavior in callers that distinguish `apperr.Internal` (for example `apps/letfs/internal/filesystem/archive.go`). Default unknown transport codes should decode to `apperr.Internal`, with a regression test for an unlisted gRPC code.

### Medium — the canonical contract check fails in the configured development environment

`scripts/contracts/generate.py:113` invokes bare `gofmt`. The repository environment exposes Go at `/usr/local/go/bin`, but does not put it on `PATH`, so `pnpm --filter @openlet/contracts check` fails with `FileNotFoundError: gofmt`. Prefixing `PATH=/usr/local/go/bin:$PATH` makes the same check pass. The canonical generation/check command should resolve the configured Go toolchain or fail with an actionable prerequisite message.

### Low — generation can leave action bindings partially updated after a later failure

`scripts/contracts/generate.py:133` writes `packages/go/authz/actions.go` and the Python action map before running Buf lint, format, protobuf generation, and drift checks at lines 142 onward. A schema or tool failure after those writes leaves the repository with new authorization bindings but old protobuf/OpenAPI outputs. Generate all artifacts in the temporary tree and publish them only after every validation succeeds.

## Verification

- `go test ./...` in `packages/go` passed.
- `go test -tags integration ./rpc -run '^TestIntegrationEnvoyPublicHTTPAndPrivateRPCIsolation$' -count=1` passed.
- `pnpm --filter @openlet/contracts check` failed because `gofmt` was not on `PATH`.
- `PATH=/usr/local/go/bin:$PATH pnpm --filter @openlet/contracts check` passed.

No correctness or public-ingress regression was found in the reviewed Envoy route removal, explicit actor delegation, HTTP problem mapping, or shared Temporal translation beyond the findings above.

## Resolution

Controller fixed the unknown-code fallback to `apperr.Internal` and added a `DataLoss` round-trip regression. Generation now validates Buf and builds all bindings before writing action artifacts. Missing `gofmt` now produces an actionable Go/PATH prerequisite; setup documents the configured toolchain path. The normal Go commands already require this PATH, so no hardcoded host path was added to generation.
