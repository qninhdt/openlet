# Implementation Leta và observability

Bắt đầu 2026-11-13 theo yêu cầu người dùng. Dùng hai owning plans hiện có;
evaluation hoãn. Không dùng archive implementation/tests, compatibility wrappers,
skills hoặc subagents. Pyright kiểm Python gồm ingest và SDK.

## Các phần thực thi

- [ ] Core: owning provisioning/cleanup activities, bỏ visibility mutation, shared queues/contracts.
- [ ] Python: typed SDK/ingest, Pyright gate.
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

Chưa chạy checks cho implementation. Không có background process của phiên cần giữ.
