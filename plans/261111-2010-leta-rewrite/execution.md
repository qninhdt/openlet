# Implementation Leta và observability

Bắt đầu 2026-11-13 theo yêu cầu người dùng. Dùng hai owning plans hiện có;
evaluation hoãn. Không dùng archive implementation/tests, compatibility wrappers,
skills hoặc subagents. Pyright kiểm Leta, ingest, SDK và operational scripts.

## Phần đã triển khai

- Core owning provisioning/cleanup activities; bỏ storage visibility mutation.
- Typed Python SDK/ingest và Pyright gate.
- Leta fresh domain schema, native checkpoint migrations, resource/inbox/history/HITL/schedules.
- Sáu Temporal workflows, 22 activities, ba queues trong một worker process.
- Native `create_agent`, inferred `@tool`/`ToolRuntime`, inbox middleware,
  summarization, synchronous checkpoint/projection và native keep_latest pruning.
- Mirage/Monty, native Redis content/index cache, LetFS hooks và home/mount containment.
- HTTP JSON/SSE API; native AG-UI event validation, bounded snapshot/replay suffix.
- Alloy/Grafana Cloud config, dashboards/alert bodies, Go RAG observations,
  native Langfuse callbacks/provider wrapper và managed-prompt linkage/cache.
- Docker/Compose profiles, migrations, backup/restore, shared E2E và CI/release wiring.

Các phần này đã có code và local integration proof; **Cloud/deploy và prompt-content acceptance còn mở**. Không coi việc
thêm test hoặc build image là bằng chứng toàn bộ runtime đã hoạt động.

## Commit boundaries

- `258fa87`: typed ingest/SDK và Python checks.
- `0ef375a`: core activity ownership.
- `8e66a3c`: native tracing/metrics/log correlation.
- `eb78a03`: retrieval observations và managed ingest prompts.
- `5220e2f`: Leta persistence/orchestration foundation.
- `80423ee`: native inferred agent tools; bỏ runtime JSON-schema catalog,
  custom validator và generic dispatcher theo correction của người dùng.
- `f845773`: native runtime/checkpoints/VFS, durable lifecycle và events.
- `d869953`: HTTP/SSE API.
- `df5c965`: Cloud collector, dashboards và native metric configuration.
- `02a99ca`: refresh mounts sau HITL result.
- `32a5d89`: service profiles/migrations và shared integration delivery.
- `c7c0e8d`: trả final storage provisioning ZedToken tại onboarding.
- `8f9eb65`: native workflow initialization trước Update-With-Start admission.
- `ff003a5`: format gates, Pyright strict cho source/tests và generated async SDK types.
- `3027d0d`: một lazy Mirage Workspace/Session mỗi lần thực thi runtime activity,
  reuse qua tool batches và đóng tại activity exit.
- `0462872`: gộp Leta vào shared API E2E, bỏ suite/project riêng.
- `d69be44`: xóa cancellation marker không còn caller.

## Đã kiểm

- `make check` pass: Pyright strict 0 errors/warnings, Ruff lint/format,
  Prettier, TypeScript, Go vet, protobuf lint và shell syntax. `make format`
  không tạo diff mới khi chạy lại; `make generate` không tạo generated drift.
- 26 Python tests pass, gồm sáu focused Leta checks. Native tool schemas chỉ
  expose model arguments; ToolNode thực sự inject runtime và validate input.
- Go tests cho Platform, LetFS và SDK pass. Native gRPC telemetry test xác nhận
  duration histogram đơn vị giây và cùng trace qua client/server.
- Sáu workflow definitions nạp thành công trong native Temporal sandbox.
- Native Temporal server proof với workflow Agent thật xác nhận cancel rồi nhận
  inbox mới, pause/resume giữ run ID và Continue-As-New khi activity còn chạy;
  cancellation được settle trước rotation. Test activities thay domain/runtime
  trong orchestration proof này; crash recovery của full stack được kiểm riêng bên dưới.
- Native PostgreSQL checkpoint proof pass: restart/resume giữ pending graph work;
  keep_latest còn một snapshot, reopen giữ đúng message state. Dùng disposable DB
  được pg_dump trước native schema setup, không thay database hiện hữu.
- TypeScript E2E typecheck, shell syntax, ShellCheck và actionlint pass.
- Leta Docker image build và Compose bake target pass.
- Config/Compose/Alloy validate cho cả `observability` và `leta,observability`.
  Redis scrape chỉ bật cùng Leta; Python/Go Temporal durations cùng đơn vị giây.
- Local OTLP → Alloy → HTTP sinks proof: Tempo bỏ AI content, giữ model metadata;
  chỉ Go retrieval vào nhánh Langfuse, không duplicate Python spans.
- Shared API E2E **5/5 pass, 53,2 giây** trên một stack: gateway, collaboration,
  file operations, ingestion/search và Leta runtime. Journey Leta gồm native
  agent/tools, file/shell qua nhiều tool batches, SSE, Box/Leti, ask/answer,
  schedule sau khi human owner rời workspace và cleanup.
- Native Langfuse OTLP payload từ runtime thật có model/tool parentage, ba
  generations cùng prompt `leta/root` version 1 và usage provider fixture
  120 input/20 output/140 total mỗi generation. Invocation sau có trace mới,
  cùng agent session. Đây là local export proof, chưa phải Cloud ingestion.

## Integration bổ sung

Redis allowlist đã được người dùng duyệt và shared API E2E đã pass sau khi
áp dụng. Mirage workspace/session là objects trong worker, không phải OS
process. Cwd/env là override từng tool call; không hứa shell exports tồn tại
qua các call. Không mở thêm network commands hoặc Python socket callbacks.

Smoke bổ sung với services thật đã pass:

- Cùng native workspace/session qua các call; read → custom edit → read thấy
  nội dung mới qua native Redis invalidation.
- HITL cấp editor cho private storage; refresh thêm mount và đọc được file.
  Revoke chặn native LetFS; cache đã warm vẫn đọc được trước khi refresh bỏ
  mount, đúng bounded-cache policy đã duyệt.
- Cùng message ID/payload trả cùng admission; khác payload trả HTTP 409.
  Input lúc pause chạy tiếp sau resume, latest checkpoint còn một snapshot.
- DeleteWorkspace workflow hoàn tất cả owning cleanup và Leta archived.

Lượt đầu gặp PERMISSION_DENIED ngay sau provisioning. Probe xác nhận cùng thời
điểm `fully_consistent` có quyền còn `minimize_latency` chưa nhìn thấy quyền mới.
Smoke chờ permission visibility tại setup; không đổi production policy hoặc
thêm retries vào application. Root home lấy root_node_id từ GetStorage, không
dùng nullable box home_node_id làm root locator trong test.

Full-stack crash proof cũng đã pass: sau khi hai tool results được checkpoint,
provider fixture trì hoãn model call kế tiếp; host gửi SIGKILL tới Leta worker
rồi khởi động lại container. Temporal heartbeat timeout/retry đưa activity về
native PostgreSQL checkpoint. Run ID không đổi; kết thúc có đúng ba tool results,
một final note và một latest checkpoint. Hai tools đã hoàn tất trước crash
không bị gọi lại; tool batch còn lại tiếp tục được. Đây là kiểm chứng crash tại
một boundary có checkpoint, không hứa exactly-once cho arbitrary shell bị kill
giữa side effect và checkpoint. Sau đó workspace cleanup vẫn hoàn tất.

## Acceptance còn lại

1. Deployment Cloud cần endpoints/credentials thật để kiểm ingestion/auth,
   dashboard rendering, notifications và usage. Chưa thực hiện deployment.
2. Nội dung system prompts vẫn draft, chưa được duyệt/publish. Test prompt
   fixtures chỉ phục vụ deterministic CI, không phải production prompts.
3. Cache-friendly compaction chưa đạt: callback hiện tại đổi system prompt,
   flatten messages thành XML và không giữ tools; current time cũng được ghi
   lại trong system tại mỗi boundary. Cần sửa request theo owning design và
   kiểm actual wire prefix/cache usage; các proof checkpoint/pruning trước đó
   không xác nhận phần này.
4. Provider-owned catalog, một model reference có effort suffix, manual pricing,
   model-list API và ba output modes là scope tiếp theo, chưa có implementation.
   [Source review và đề xuất retry](../reports/design-261113-2202-provider-catalog-compaction-retries.md)
   phân biệt phần người dùng đã chốt với retry policy còn đề xuất.

## Ranh giới vận hành

Không thay database cũ/production; disposable integration databases được backup
trước migration. Native checkpoint tables nằm trong Leta PostgreSQL backup;
Redis disposable không backup. Core open histories cần drain/recovery trước
cutover; không giữ legacy activities để tương thích. Không publish prompt,
push image hoặc deploy Cloud trong lượt này.

Không còn background server/container test do phiên này khởi động cần giữ.
