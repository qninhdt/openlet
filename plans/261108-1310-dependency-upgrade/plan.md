# Repository dependency upgrade

## Outcome and boundaries

Upgrade all Openlet Python and Go dependencies, JavaScript tooling, container images and CI tools to registry-verified stable releases. Keep all Python services on the latest Python 3.14 patch, as explicitly selected by the user. Resolve dependency/API conflicts and verify affected behavior. Preserve existing uncommitted Leta/identity work. Do not deploy, commit, mutate existing databases or expand the accepted engine design.

## Execution

- [x] Inventory canonical manifests, embedded test images and tool pins; record live registry evidence.
- [x] Upgrade Python manifests/lockfile and resolve conflicts; validate native imports, parser and service tests.
- [x] Upgrade all Go modules/tools coherently; regenerate contracts if necessary and fix API incompatibilities.
- [x] Upgrade Node tooling, Docker base/runtime/infra images and CI actions; keep fixtures and docs consistent.
- [x] Run focused checks followed by shared builds, lint, tests and disposable integration checks; review the final upgrade diff.

## Acceptance

All direct dependencies and managed infrastructure/tool versions have been checked against upstream registries. Remaining compatibility constraints, if any, have concrete evidence and are recorded explicitly. Lockfiles match manifests; relevant checks pass without weakening assertions. Runtime/infra configuration agrees with test fixtures. The main Leta implementation remains paused outside changes necessary for the upgrade.

## Current findings

Python 3.15.2 is available, but the user selected Python 3.14.10. Docling 2.148.0 with Torch OCR passed a Python 3.15 CPU/OCR smoke test in a temporary environment, but AG-UI LangGraph 0.0.47 declares Python <3.15. The repository retains its ONNX OCR backend on Python 3.14.

The user approved Instructor 1.17.0 with OpenAI 3.3.0 after the [compatibility check](../reports/research-261108-1316-instructor-openai-compatibility.md). Newer OpenAI releases conflict with Instructor's jiter constraint. The compatible pair is now locked; Instructor uses native JSON Schema, replacing the interim manual schema prompting and validation. The E2E model boundary consumes the same native response format.

The Go OpenAPI generator moved to `connectrpc.com/protoc-gen-connect-openapi`. Generation now preserves the canonical HTTP Problem JSON contract instead of the new generator's gRPC status default; a regression test covers this. [Upgrade review](../reports/review-261108-1322-dependency-upgrade.md) has no unresolved findings.

Version evidence, upstream constraints and verification are recorded in the [upgrade report](../reports/implementation-261108-dependency-upgrade.md). LetFS race integration/workflow tests, all three Go replay suites and all 35 API E2E tests passed. Test-owned containers were cleaned up. Host Docker daemon/CLI plugins are outside the repository changes and have not been replaced or restarted.

The working tree already contains the authorized human identity migration and early Leta implementation. Previous tests under Python 3.13 do not establish compatibility after this dependency upgrade.
