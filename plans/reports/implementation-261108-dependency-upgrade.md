# Openlet dependency upgrade

Verified on 2026-11-08. Scope: repository-owned runtimes, dependencies, build tools, Docker images, fixtures and CI. Existing identity migration and early Leta work were preserved; the Leta feature implementation remains paused. No commit, deployment or existing database migration was performed.

## Selected versions

| Surface | Selected stable version |
| --- | --- |
| Python / Go | 3.14.10 / 1.27.3 |
| Node / pnpm / uv | 26.13.0 / 12.18.0 / 0.13.7 |
| Docling / CPU Torch / CPU TorchVision | 2.148.0 / 2.15.0 / 0.29.1 |
| Instructor / OpenAI | 1.17.0 / 3.3.0 (accepted compatibility constraint) |
| Pydantic / LangChain / LangGraph | 2.14.3 / 1.4.9 / 1.2.20 |
| Temporal Python / PostgreSQL checkpointer | 1.35.0 / 3.2.0 |
| Mirage / AG-UI LangGraph | 0.0.8 / 0.0.47 |
| Ruff / pytest / pytest-asyncio | 0.17.4 / 9.2.0 / 1.4.1.post1 |
| Go pgx / gRPC / protobuf / testcontainers | 5.12.0 / 1.85.0 / 1.36.12 / 0.45.0 |
| Go OpenTelemetry / instrumentation | 1.47.0 / 0.72.0 |
| OpenAPI generator / Buf | 0.30.0 / 1.75.0 |
| Playwright / TypeScript / Turbo | 1.65.0 / 7.0.2 / 2.11.10 |
| PostgreSQL / Temporal / SpiceDB | 18.6-trixie / 1.32.2 / 1.57.0 |
| Envoy / Qdrant / Redis test fixture | 1.40.2 / 1.20.0 / 8.10.3-trixie |
| MinIO / Goose | RELEASE.2025-10-15T17-29-55Z / 3.29.0 |
| Debian bases / distroless | trixie / static-debian13 |
| GitHub Actions runner | ubuntu-26.04 (upstream GA) |

Exact dependency versions and container digests remain owned by the manifests, lockfiles, Dockerfiles and fixtures. Qdrant, MinIO, Goose and Go were already at the latest checked stable release; applicable base images/digests were refreshed. CI actions were checked individually and pinned to their current release tags.

## Registry evidence and constraints

Versions were queried from PyPI JSON metadata, the PyTorch CPU index, the Go module proxy, npm, official GitHub release APIs, Node's release index and OCI manifest indexes. No version was selected from memory. Temporary raw inventories under `/tmp` were lost when the execution environment restarted; the selected versions and exact digests remain in the repository manifests and lockfiles.

Recheck sources: [Python downloads](https://www.python.org/downloads/), [Go releases](https://go.dev/dl/?mode=json), [Node releases](https://nodejs.org/download/release/index.json), [Docling metadata](https://pypi.org/pypi/docling/json), [PyTorch CPU index](https://download.pytorch.org/whl/cpu/), [Temporal releases](https://github.com/temporalio/temporal/releases), [SpiceDB releases](https://github.com/authzed/spicedb/releases), [Envoy releases](https://github.com/envoyproxy/envoy/releases), [Qdrant releases](https://github.com/qdrant/qdrant/releases), [MinIO releases](https://github.com/minio/minio/releases).

Python 3.15.2 was investigated separately. A temporary Docling/Torch OCR smoke passed, but AG-UI LangGraph 0.0.47 declares Python <3.15. The user selected the latest 3.14 patch. Production OCR remains ONNX.

The [Instructor compatibility investigation](research-261108-1316-instructor-openai-compatibility.md) established the accepted exception: OpenAI 3.3.1 and later require jiter >=0.16, while Instructor 1.17.0 requires jiter <0.15. OpenAI 3.3.0 is the newest compatible stable release. Its native JSON Schema mode is now used through Instructor; manual schema prompting/validation was removed.

Other resolver-retained transitive dependencies have upstream constraints:

| Dependency retained | Owning constraint |
| --- | --- |
| huggingface-hub 1.33.0 | docling-ibm-models requires <2 |
| jiter 0.14.0 / Rich 14.3.4 | Instructor requires <0.15 / <15 |
| mpmath 1.3.0 | SymPy requires <1.4 |
| nexus-rpc 1.4.0 | Temporal pins this version |
| openrouter 0.10.8 | langchain-openrouter requires <1 |
| Monty/client/runtime 1.4.0 | Mirage pins this version |
| semchunk 3.2.5 | docling-core chunking requires <4 |
| typer 0.27.3 | docling-core requires <0.28 |
| uuid-utils 0.19.0 | LangSmith requires <1 |
| CPU TorchVision 0.29.1 | latest available in the selected CPU index; PyPI 0.29.2 is a different distribution source |

No upstream constraints were bypassed. `uv pip check` passed. The npm outdated audit returned an empty object. The active Go module audit found no newer releases among 124 modules used by the workspace/test/tool graph; unused modules retained in third-party dependency test graphs were not promoted into application dependencies.

## Compatibility changes

- Upgraded all three Python package requirements and the shared lockfile together; declared Pydantic directly in the two services importing it.
- Upgraded all four Go modules and sums, including active transitive dependencies; synchronized the workspace and genproto replacement.
- Adopted the generator's upstream module path `connectrpc.com/protoc-gen-connect-openapi`. Generated HTTP errors reuse the canonical public Problem JSON schema/response instead of the generator's new gRPC Status default. A focused regression test covers this contract.
- Updated native JSON Schema assertions in semantic extraction tests and the E2E provider boundary. Invalid initial structured output still exercises Instructor validation/retry.
- Updated Docker/Compose, disposable fixtures, recovery/performance image pins, CI and setup documentation together. Contract generation uses locked Buf/grpcio-tools instead of an unrelated system protoc package.

## Verification

- All four Go module unit suites and integration suites passed against disposable dependencies.
- All three Go workflow suites passed, including LetFS workflow tests with `-race`. The full LetFS integration suite also passed with `-race`: filesystem 237.671s, Temporal 53.623s, gRPC 124.706s and HTTP 30.928s. After the environment restart, this suite was rerun to completion; its log is `.local/upgrade-letfs-race.log`.
- Python ingest: 101 regular tests and 11 real parser/OCR tests passed.
- Shared Python and scripts: 68 tests passed, including isolated wheel and wire-boundary coverage.
- Leta tests: 40 passed; the remaining time-skipping compatibility test initially hit the SDK's five-second server startup deadline, then passed unchanged on a focused rerun.
- All 35 real API E2E tests passed, including native gRPC authorization, parser recovery, outage handling, uploads and isolated backup/restore.
- Two E2E environment lifecycle tests passed on rerun after a cold-image startup timeout. The separate backup/restore lifecycle test also passed. No assertions or timeouts were weakened.
- `pnpm build`, `pnpm check`, TypeScript checks, contract regeneration/check and the focused generator tests passed. The generator change was followed by another full `pnpm check`.
- Fresh Go histories were exported by the upgraded E2E run. Account, Workspace and LetFS replay tests passed with `OPENLET_HISTORY_DIR` pointing to `.local/api-e2e/histories`. An initial root replay command omitted that variable and failed on missing history files; this is not counted as a pass.
- [Independent upgrade review](review-261108-1322-dependency-upgrade.md) found no unresolved upgrade-specific issues after the OpenAPI correction.

## Boundaries

Host Docker Engine/Compose/Buildx were not replaced or restarted; unrelated `durable-chat-*` containers were left alone. Repository image/tool pins were upgraded. Paid-provider inference and a hosted GitHub Actions run were not performed. Local model-boundary tests verify the native structured-output request contract, not support by every provider/model.

Existing database volumes were untouched. Disposable test resources are cleaned by their harnesses. Preserve backups and follow the existing migration/restore procedure before applying the separate identity migration to a deployment.
