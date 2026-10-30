> Historical report. Implementation recommendations are superseded by the [2026-10-29 researched plan](../261029-1220-openlet-backend-mvp/plan.md); not current architecture authority.

# Temporal Rust SDK Feasibility for Openlet

Research date: 2026-10-29 (Asia/Ho_Chi_Minh)


## Decision

Native Temporal Rust is feasible for `letfs`; there is no evidence of an actual SDK blocker. Use `temporalio-sdk` `1.1.0` for a small implementation spike, pin the public SDK crates to their compatible `1.1.x` line while respecting the manifest's exact Core dependency, and keep workflow/activity DTOs deliberately language-neutral. Do not introduce a Go sidecar unless the spike finds a concrete Rust or interop failure.

This is a documentation/source assessment only. Nothing was compiled, installed, connected to a Temporal server, or tested at runtime.

## Evidence

- Temporal's Rust guide links native Rust Workflow, Activity, Worker, Client, and Child Workflow guides. The quickstart shows a Rust worker connecting to a Temporal service, registering a Workflow and Activities, and starting the Workflow.
- The SDK README describes native Rust APIs: `#[workflow]`/`#[workflow_methods]`, `#[activities]`/`#[activity]`, `Worker`, deterministic Workflow primitives, signals, queries, updates, child Workflows, replay, and testing support.
- The `1.0.0` release explicitly declares the Rust SDK generally available and says it aims to avoid backwards-incompatible changes. `1.1.0` is the latest non-prerelease Rust SDK tag found on 2026-10-29.
- `crates/sdk/Cargo.toml` at `v1.1.0` declares Rust `1.92.0`, edition 2024, and exact Core dependency `temporalio-sdk-core = 0.10.0`; the SDK's other Temporal crates are on the `1.1.x` line. This is a real toolchain/dependency constraint for the planned Rust service.

## Capability and Server Requirements

| Need in Openlet | Documented support | Server implication |
|---|---|---|
| Rust-native Workflows and Activities | Supported by the Rust guide and SDK README | Standard Temporal service connection, namespace, and task queue; no special server feature is documented for the basic path |
| Rust Worker in `letfs` | `WorkerOptions`, registration, polling, graceful shutdown documented | Worker and client must use the same namespace/task queue contract as Go workers |
| Child Workflows | Rust `start_child_workflow`; parent-close policy documented | Uses normal child-workflow service events; choose the policy explicitly |
| JSON DTOs | Rust default converter uses `serde_json`; Go default converter uses JSON | Both emit/read `encoding = json/plain` for ordinary JSON values, but exact DTO interop remains untested |
| Worker versioning overrides | Added in Rust `1.1.0` | Pinned/auto-upgrade routing requires Temporal Server `1.28.0+`; one-time routing and experimental child override require `1.32.0+`. Exclude this from the first spike. |

The Rust client documentation uses a normal gRPC endpoint such as `localhost:7233` and a namespace such as `default`. It does not state a Rust-specific minimum Temporal Server release for ordinary Workflows/Activities. Therefore, do not invent one; verify the deployed server version separately before enabling newer optional features.

## Go/Rust Interop

### Payload conversion

The Temporal default-converter documentation says SDKs serialize ordinary values as JSON unless a more specific converter applies. The Go source's default JSON converter uses Go `encoding/json` and labels the payload `json/plain`. Rust `v1.1.0` uses a composite converter (well-known wrappers followed by `serde_json`) and also labels JSON payloads `json/plain`.

This supports a small common DTO contract, not arbitrary type compatibility:

- Use one explicit request/response struct per Activity or Workflow operation.
- Give every field an explicit wire name: Go `json:"openlet_user_id"`; Rust `#[serde(rename = "openlet_user_id")]`.
- Prefer strings, booleans, bounded numbers, arrays, and nested objects. Avoid relying on Go/Rust default field naming, time/date encodings, map ordering, numeric-width behavior, language enums, or binary values.
- Keep binary/file content out of Workflow inputs and history; pass an object key or small reference instead.
- Use the default converter on both sides. Custom codecs, encryption, compression, or custom converters require the same configuration on both workers and were not assessed here.

The Rust converter treats some well-known values specially (for example `Vec<u8>` as `binary/plain`), so a DTO containing bytes is not a safe first interop case even though both SDKs support byte payloads.

### Workflow, Activity, and Child Workflow names

Temporal routes task execution by string type names. Go registration defaults to the function name but supports an explicit alias through `RegisterWorkflowWithOptions`; Go child-workflow calls resolve the registered type name. Rust's macro-generated Workflow definition defaults to the Rust type name, while `#[run(name = "...")]` can override it. Rust Activities similarly default to the method name and support `#[activity(name = "...")]`.

For any Go/Rust boundary, define stable names in the contract and set them explicitly on both sides. Do not rely on Go package/function names or Rust type names. The same rule applies to Activity names and signal/query/update names.

There is no primary-source Rust/Go compatibility matrix or exact cross-language child-workflow example in the sources checked. Same `json/plain` metadata and matching string type names establish a plausible protocol path, not tested interop.

## Maturity and Options

| Option | Architectural fit | Complexity | Maintenance/adoption risk | Performance |
|---|---|---:|---|---|
| Native Rust SDK `1.1.0` in `letfs` | High: matches the required Rust/Axum service boundary | Medium | Medium-high: GA is recent (`1.0.0` on 2026-09-04; `1.1.0` on 2026-10-06) and the pre-GA tag history is short | Direct worker, no language bridge |
| Go Temporal sidecar for `letfs` workflows | Low-medium: adds a worker/service boundary to a Rust-owned domain | High | Lower SDK maturity risk in Go (`v1.50.0`), but higher Openlet integration and operational risk | Extra RPC/DTO hop and another process |

The ranked choice is native Rust first. The Go SDK is materially more established, but that is not enough to justify a sidecar when the Rust SDK is GA and already exposes the needed native worker model.

## Recommended First Spike

Build the smallest disposable integration test, without production domain logic:

1. Start one Temporal development server and one Rust Worker on a dedicated task queue.
2. Register a Rust Activity with an explicit stable name, accepting and returning a small `serde` DTO with explicit field renames.
3. Start a Rust Workflow from the Rust client and verify the Activity result.
4. Start or execute the same Workflow/Activity from the Go SDK using the exact same type name, task queue, and JSON DTO.
5. Add the reverse direction: a Go Workflow schedules a Rust Activity (or starts a Rust child Workflow), then verify the Rust worker receives and returns the DTO.
6. Record payloads and failures only as non-sensitive test fixtures; test missing fields, `null`, empty arrays, and a name mismatch.

The spike should pin Rust `1.1.0`, Go `1.50.0`, and the Temporal server image/version used. Its acceptance criterion is successful bidirectional execution with explicit names and DTOs; it must not be treated as proof that arbitrary Go/Rust types interoperate.

## Untested Risks and Limits

- No compile, integration, replay, or live Temporal-server check was performed.
- Exact Rust `1.1.0` versus Go `1.50.0` payload behavior for Openlet DTOs was not exercised.
- No test was made for cross-language child-workflow completion, cancellation, parent-close policy, retries, signals, updates, or failure conversion.
- Rust SDK adoption/community size and production usage were not independently measured; the maturity conclusion is limited to official release status and repository history.
- The repository currently has no application `Cargo.toml`; there is no local dependency or server configuration to validate.

## Sources

Primary sources, retrieved 2026-10-29:

1. Temporal Rust developer guide: <https://docs.temporal.io/develop/rust.md>
2. Rust quickstart: <https://docs.temporal.io/develop/rust/quickstart.md>
3. Rust Worker guide: <https://docs.temporal.io/develop/rust/workers/worker-process.md>
4. Rust Activity guide: <https://docs.temporal.io/develop/rust/activities/basics.md>
5. Rust Child Workflow guide: <https://docs.temporal.io/develop/rust/workflows/child-workflows.md>
6. Rust SDK README, pinned tag: <https://github.com/temporalio/sdk-rust/blob/v1.1.0/crates/sdk/README.md>
7. Rust SDK Cargo manifest, pinned tag: <https://github.com/temporalio/sdk-rust/blob/v1.1.0/crates/sdk/Cargo.toml>
8. Rust SDK `v1.0.0` GA release: <https://github.com/temporalio/sdk-rust/releases/tag/v1.0.0>
9. Rust SDK `v1.1.0` release: <https://github.com/temporalio/sdk-rust/releases/tag/v1.1.0>
10. Rust default data converter, pinned tag: <https://github.com/temporalio/sdk-rust/blob/v1.1.0/crates/common-wasm/src/data_converters.rs>
11. Rust Workflow name generation, pinned tag: <https://github.com/temporalio/sdk-rust/blob/v1.1.0/crates/macros/src/workflow_definitions.rs>
12. Temporal default/custom data converters: <https://docs.temporal.io/default-custom-data-converters.md>
13. Go default JSON converter, pinned tag: <https://github.com/temporalio/sdk-go/blob/v1.50.0/converter/json_payload_converter.go>
14. Go converter metadata constants, pinned tag: <https://github.com/temporalio/sdk-go/blob/v1.50.0/converter/metadata.go>
15. Go SDK module and release, pinned tag: <https://github.com/temporalio/sdk-go/blob/v1.50.0/go.mod> and <https://github.com/temporalio/sdk-go/releases/tag/v1.50.0>
16. Go Child Workflow guide: <https://docs.temporal.io/develop/go/workflows/child-workflows.md>

## Unresolved Questions

The implementation plan resolves spike scope: cross-language Activities, Go parent/Rust child completion/cancellation, restart and replay are mandatory. Use the durable PostgreSQL-backed Compose stack for recovery tests, rather than an ephemeral development server.

Exact Temporal Server image/digest remains a phase-1 technical verification choice. Select a compatible stable release, pin it, and record the tested matrix. This is not a pending product question.

Status: DONE
Summary: Official sources show native Rust Temporal support is feasible and GA, with a young but usable `1.1.0` release. JSON and named-type conventions make Go/Rust interop plausible, but exact Openlet DTO and child-workflow behavior remains untested.
Concerns/Blockers: None evidenced; runtime/build verification is intentionally deferred to the recommended spike.
