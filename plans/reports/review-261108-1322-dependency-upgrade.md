# Dependency upgrade review

Reviewed the dependency-specific delta against `/tmp/openlet-before-dependency-upgrade.patch`, excluding the existing identity/Leta migration. This was a read-only source/configuration review; no application files were edited or heavy tests run.

## Finding

### Resolved P2: Generated HTTP error response contradicted the implemented contract

`packages/contracts/generated/letfs.openapi.json:46` now declares a default error response with `application/json` and `google.rpc.Status`. That schema requires an integer `code` when present. The implemented route goes through `apps/letfs/internal/transport/http/router.go` and `packages/go/httpapi/problem.go:11`, which emits `application/problem+json` with a string application code, `detail`, `status`, and request context. A real error such as `{"code":"NOT_FOUND",...}` therefore contradicts the newly generated reference.

This comes from the upgraded generator: `connectrpc.com/protoc-gen-connect-openapi@v0.30.0/internal/converter/googleapi/paths.go:347` unconditionally inserts the gRPC-transcoder error shape. Its `disable-default-response` option controls the successful 200 response only, and its `override` option overrides components only.

The public OpenAPI remained correct and only consumes component schemas from the generated document, so this was a regression in the generated HTTP transport reference and consumers of that reference, not a runtime transport change.

The controller fixed generation in `scripts/contracts/generate.py` by copying the canonical public Problem schema and default response into generated output. These remain generated copies of one handwritten authority, with local references that avoid changing the Go OpenAPI loader. Reviewed the resulting source and output; the Problem schema has no additional nested references to copy. Invoked the focused `test_generated_http_errors_match_problem_transport` regression assertion directly and independently asserted exact equality between both generated definitions and their canonical public definitions; all passed. No remaining finding.

## Other observations

- Direct Python pins agree with registry snapshots except the explicitly accepted OpenAI and CPU TorchVision constraints. Instructor validation/retry remains in place and the changed HTTP test covers an invalid first response followed by a valid retry.
- All 151 dependency versions found in the four Go manifests agree wherever shared, with matching sum entries. The OpenAPI tool module rename is coherent.
- Container image tags/digests agree with the supplied registry evidence, including the Go/Python Debian base changes, Redis fixture, Temporal, PostgreSQL, SpiceDB and Envoy pins.
- Node manifests agree with the workspace lockfile. The removed system `protoc` step is supported by generation through locked Buf and `grpc_tools.protoc`.
- No substantive behavior-preserving simplification was identified; additional refactoring would add review scope.

Verification relied on source, generated output, manifests, lockfiles, registry snapshots, the focused regression assertion described above, and the controller's reported test evidence. Full E2E/recovery and LetFS integration were still in progress when this review was requested; no live paid-provider calls were made.

Status: DONE
Summary: The sole concrete generated OpenAPI error-contract regression was fixed and checked during review. No unresolved dependency-specific defect or substantive simplification found in the reviewed scope.
