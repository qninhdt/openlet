# Implementation Leta và observability

Bắt đầu 2026-11-13 theo yêu cầu người dùng. Dùng hai owning plans hiện có;
evaluation hoãn. Không dùng archive implementation/tests, compatibility wrappers,
skills hoặc subagents. Pyright kiểm Python gồm ingest và SDK.

## Các phần thực thi

- [x] Core: owning provisioning/cleanup activities, bỏ visibility mutation, shared queues/contracts.
- [x] Python: typed SDK/ingest, Pyright gate.
- [ ] Observability: Alloy/Cloud wiring, shared provider/Langfuse, Go RAG/ingest observations.
- [ ] Leta: fresh schema, config/auth, resources, inbox/history/HITL/schedules.
- [ ] Leta: Temporal workflows/activities, native graph/checkpoints/compaction/tools/VFS.
- [ ] API/events: HTTP/SSE, bounded bootstrap/replay, ingress.
- [ ] Integration: Compose/migrations/config/build/CI/backup/docs, focused checks.

## Ranh giới vận hành

Không thay database hiện hữu; backup trước schema/data execution. Core open Temporal
executions cần kiểm trước deploy; không giữ legacy activity để làm compatibility.
Prompt content vẫn draft, chưa publish Cloud. Cloud credentials là đầu vào deployment.

## Verification

Core/storage và ingest/SDK focused checks đã qua; shared E2E có workspace cleanup,
ingress và ingestion/search đã qua. File journey đã bỏ case visibility mutation
retired; chưa rerun full E2E sau thay đổi test đó.

Leta hiện là implementation dở dang, chưa có API, native runtime runner hoặc
worker startup/integration. Không xem các file hiện có là service đã hoàn tất.

Theo correction của người dùng: đã xóa runtime `tool-schemas.json`, dependency
`jsonschema`, validator, dynamic StructuredTool binding và generic tool/VFS
business dispatcher. Dùng native `@tool`/`ToolRuntime`, inferred inputs, direct
feature calls và Mirage native dispatch. Root 28/Leti 22; tools riêng root không
expose cho Leti. Hai focused tests kiểm actual compiled ToolNode + Mirage shell,
injected runtime và native invalid-input response đã qua. Pyright toàn workspace
và Ruff Leta đã qua. Chưa kiểm real-provider/DB/Leta end-to-end hoặc Cloud export.

Không có background process của phiên cần giữ.
