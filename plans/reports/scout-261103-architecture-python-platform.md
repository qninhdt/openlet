# Khảo sát kiến trúc Python và nền tảng

Ngày: 2026-11-03, Asia/Ho_Chi_Minh. Phạm vi chỉ đọc: letfs-ingest, wheel Python, contracts/codegen, Envoy/Compose và topology e2e. Không sửa production. CodeGraph được dùng trước tìm kiếm mã; cây làm việc sạch ở lần kiểm tra đầu. Các đường dẫn Go dưới đây ghi theo source lúc scout; controller đã di chuyển `internal/grpc`→`internal/transport/grpc`, `internal/temporal`→`internal/jobs` và clients→`internal/clients`. Khi triển khai dùng đường dẫn mới. Plan điều phối: `plans/261103-architecture-service-boundaries/plan.md`.

## Kết luận triển khai

Đóng gRPC công khai ở Envoy là thay đổi nhỏ, độc lập với protocol ingest nội bộ. Python đã có wheel generated độc lập; phần thiếu là ranh giới application/transport trong `activity.py`. Giữ gRPC backend, trực tiếp signed URL đến object storage, Temporal workflow/activity names và payload hiện tại. Không cần đổi Python↔letfs sang HTTP hay viết SDK HTTP mới để đáp ứng HTTP-only public API.

## Nguồn và ranh giới hiện tại

- `docs/architecture.md`: owner letfs là HTTP/gRPC; ingest chỉ có service credential và signed URLs, không có DB/S3 credentials. `docs/api-contracts.md:3,109` và `packages/contracts/rpc-surface.md` hiện chủ động mô tả public filesystem gRPC.
- `packages/python/pyproject.toml:1-20`: wheel `openlet-python`, namespace `openlet_api`, chỉ chứa generated account/letfs RPC; phụ thuộc grpcio/protobuf/googleapis-common-protos, không kéo parser/Temporal vào shared wheel.
- `packages/python/tests/test_wheel.py:13-59`: build hai wheel, chứng minh app không chứa generated namespace, shared wheel không chứa app, cài vào venv độc lập và import bằng `-I`.
- `scripts/contracts/generate.py:19-54,74-88`: Go/OpenAPI qua Buf, Python qua descriptor-set + grpc_tools, tạo `_pb2`, `_pb2_grpc`, `.pyi`; khi generate xóa toàn bộ `packages/python/src/openlet_api`. Không đặt handwritten client/error/DTO dưới namespace này: sẽ bị xóa.
- `apps/letfs-ingest/Dockerfile`: build/cài riêng hai wheel vào image, models offline; CPU/I/O dùng cùng artifact với role khác nhau. `pyproject.toml` app giữ parser/AI/Temporal/HTTPX/telemetry; không cần tách thêm wheel parser chỉ vì refactor kiến trúc.
- `apps/letfs-ingest/src/letfs_ingest/semantic.py`, `indexing.py`, parser/layout/exporters đang không import generated application protobuf. Semantic/indexing nhận metadata dict/bytes; `indexing.py:16-28` đã có `VectorSpace` dataclass độc lập transport.

## Protobuf/gRPC đang rò sang application ở đâu

| Nguồn | Hiện trạng | Thay đổi tối thiểu đầy đủ |
|---|---|---|
| `activity.py:15,120-142` | Import `pb`, tạo `ProcessingGeneration`, chuyển protobuf inventory thành dict | Dùng một value object generation và DTO inventory độc lập; mapping PB tại adapter duy nhất |
| `activity.py:167-396` | Activities tạo requests, đọc `WhichOneof`, `HasField`, giữ generated message làm state; enrichment updates là PB | Client ingest có method rõ nghĩa, trả DTO; activities chỉ orchestration/error policy |
| `activity.py:398-624` | Process/upload sở hữu PB request, scope/receipts/limits và string method dispatch | Giữ byte transfer ở app nhưng chuyển request/response conversion sang adapter; không để PB lọt qua signature |
| `ingest_rpc.py:43-95` | Có transport config/channel/retry nhưng `call(method, request)` public và trả PB; ném Temporal `ApplicationError` | Thay bằng client method được dùng thực tế (prepare/complete/fail/upload); generic invoke chỉ private. Trả lỗi app có code/retryable; Temporal conversion ở activity boundary |
| `tests/test_activity.py` | Test business orchestration dựng PB và fake `call` theo tên RPC | Chuyển sang DTO/client fake; giữ assertions replay, upload reconciliation, shutdown và last-attempt failure |
| `tests/test_ingest_rpc.py` | Real gRPC server chứng minh retry/error details | Giữ PB ở adapter tests; cập nhật vị trí/names nếu di chuyển |

Đề xuất layout cụ thể, không áp đặt framework: một module DTO/port của ingest và một adapter `ingest_rpc.py` (hoặc di chuyển nguyên adapter vào thư mục infrastructure nếu whole-repo đã chốt layout tương ứng). Chỉ tạo các DTO dùng thật: generation, parse input, inventory/content, upload/transfer/receipt, enrichment update và vector-space/preparation. Mộtof “complete/input”, “inline/signed URL” và optional field phải thành variant rõ nghĩa hoặc `None` với kiểm tra đầy đủ; không chuyển protobuf sang dict bằng serializer rồi để protobuf semantics rò tiếp. Python `bytes`/`int` và empty inline bytes phải được giữ nguyên.

Shared wheel hiện tại là ranh giới contracts tốt. Không thêm Temporal, parser, OpenRouter hay Qdrant vào wheel chỉ để đạt tên “shared”. Nếu whole-repo thật sự chuyển reusable config/transport/telemetry sang shared wheel, thêm namespace handwritten riêng (ví dụ `openlet`) trong cùng distribution và khai báo cả hai namespace ở hatch; codegen chỉ quản lý `openlet_api`. Thêm isolated-wheel check cho namespace mới, giữ test anti-duplication và không thêm `PYTHONPATH` trong production. Client ingest domain-specific vẫn có thể ở app; không có người dùng thứ hai hiện được xác minh.

## Retry, timeout, idempotency và lifecycle cần giữ

1. `ingest_rpc.py:11-15,81-95`: tối đa 3 lần RPC, timeout 30 giây mỗi lần, delay 0.25/0.5 giây; chỉ UNAVAILABLE/DEADLINE_EXCEEDED/INTERNAL retry. Lỗi khác terminal; `_reason:18-40` lấy `google.rpc.ErrorInfo` domain `openlet`, bounded uppercase reason, fallback code, không lộ server detail. Đây là contract đã có real transport tests. Không bỏ hoặc nhân thêm retry khi tách adapter.
2. `apps/letfs/internal/temporal/processing.go:24-44`: 3 Activity attempts, 30 phút start-to-close, 2 giờ schedule-to-close, heartbeat 30 giây; Python activity envelope 1700 giây, heartbeat mỗi 5 giây (`activity.py:114-117`). Có hai tầng retry có chủ đích (tối đa 9 RPC attempts qua 3 activity attempts); bản refactor giữ con số và ownership, không thêm SDK/provider retry ngầm. `OpenRouter` đã `max_retries=0`, structured output riêng `max_retries=2` (`openrouter.py:88-95,118-122`).
3. Generation fence do Go/DB sở hữu: `apps/letfs/internal/filesystem/processing.go:41-55`; sai generation bị từ chối, replay complete không chạy converter (`activity.py:452-463`, `test_activity.py:64-71`). Service credential không thay generation/stage authority (`apps/letfs/internal/grpc/ingest.go:19-30,72-92`).
4. Upload recovery (`activity.py:565-569`) hoàn tất upload “completing/finalized” mà không gửi lại byte; test `test_activity.py:74-114`. PUT object chấp nhận 412 rồi xác minh complete; multipart nhận ETag/parts; không mất behavior khi chuyển response sang DTO.
5. Cancel parse chỉ abort khi yêu cầu cancel thật, worker shutdown để retry (`activity.py:410-414`, test `test_activity.py:117-158`). Resource/document/quota terminal có failure code phù hợp. Enrich/index chỉ report fail ở terminal hoặc activity attempt >=3, index cần vector-space preparation (`activity.py:191-205,329-345`, test `test_activity.py:193-239`). Không gộp cả ba stage bằng wrapper lỗi chung làm mất khác biệt này.
6. Channel hiện tạo/đóng mỗi activity (`Processor.connect`, ba `async with`), HTTPX storage cùng scope. An toàn cleanup nhưng churn; startup còn tạo channel rồi đóng ngay (`worker.py:28-29`) chỉ kiểm tra config, không chứng minh server readiness. Nếu refactor lifecycle: tách config validation khỏi dial; một channel/client do worker sở hữu, đóng sau worker drain, activities mượn client và không close shared channel. Đây là lựa chọn nhỏ nếu chạm lifecycle, không có đo đạc chứng minh cần pooling phức tạp.
7. Worker giữ AI client lifetime bằng `try/finally`, gỡ signal handlers, SDK graceful shutdown 20 giây (`worker.py:44-89`), Compose stop grace 40 giây. Converter child dùng môi trường tối thiểu không secrets, process group, timeout 660 giây, TERM rồi KILL sau 5 giây, drain bounded stderr (`activity.py:30-111`). Giữ các invariant này; tránh dời parser trở lại event loop.
8. Rủi ro shutdown thực: FailEnrichment/FailIndex có thể tự retry 3×30s ngoài timeout 1700s (catch nằm ngoài context), trong khi graceful shutdown 20s; AbortParse đã có outer timeout 5s. Khi chạm failure/lifecycle, nên đặt budget cleanup riêng cho hai fail report để bảo toàn graceful bound, dựa vào maintenance reconciliation khi hết budget. Thêm test real blocked RPC/cancel, không bỏ fail report.
9. Quan sát telemetry: `telemetry.py:148-155` chỉ instrument HTTPX/HTTPX2, Temporal interceptor tại 163-170. `ingest_rpc.py` truyền metadata chỉ authorization, không `propagate.inject`/gRPC interceptor. `docs/setup.md:72` nói generated gRPC calls được instrument nhưng source hiện không chứng minh trace propagation Python→letfs. Nếu shared telemetry là phạm vi refactor, thêm interception/injection đúng phiên bản installed và kiểm thử traceparent roundtrip tại real RPC; không coi docs hiện tại là bằng chứng đã có. OTLP gRPC exporter không phải instrumentation application gRPC.

## Toàn bộ gRPC công khai và HTTP-only ingress

Đọc JSON và proto bằng script xác minh có đúng **2 route RPC và 27 method**:

- `infra/config/envoy.template.json:135-153`: exact `/openlet_api.letfs.v1.FilesystemService/StreamArchive`, route cluster `letfs-rpc`, timeout 1815s, idle 120s, thay authorization bằng gateway credential.
- Cùng file `154-171`: prefix `/openlet_api.letfs.v1.FilesystemService/`, timeout 120s, cùng credential replacement.
- Cluster `letfs-rpc` ở `414-436`: private letfs:9090 + upstream HTTP/2. HTTP cluster letfs:8080 tại `389-412` là độc lập.
- Proto `packages/contracts/proto/openlet_api/letfs/v1/letfs.proto:9-43`: GetFilesystem, GetBucketUsage, CreateNode, ListNodes, GetNode, ResolveNode, BatchStat, UpdateNode, ReplaceContent, CreateCopy, GetCopy, GetProcessing, ReprocessNode, TrashNode, ListTrash, GetTrash, RestoreTrash, PurgeTrash, CreateUpload, GetUpload, GetUploadParts, CompleteUpload, AbortUpload, SearchFiles, SemanticSearch, GetDownload, StreamArchive.
- AccountService, IngestService, StorageAdministrationService không có public ingress route; default route `/` trả 404. Không có chứng cứ public gRPC listener riêng. Envoy public :8080; dev publish localhost:8080; e2e publish dynamic configured localhost gateway port. App RPC :9090 không publish.
- Dev ingest→letfs:9090 ở `infra/compose/dev.yaml:282-336`; e2e tương tự `infra/compose/e2e.yaml:292-318`; backend network e2e internal tại 329. Giữ các địa chỉ và allow-plaintext chỉ backend profile; không xóa TLS/service-token knobs chỉ vì public HTTP-only.

Thay đổi ingress tối thiểu: xóa đúng hai route trên và cluster `letfs-rpc`; giữ HTTP archive route `112-123` (1815s), HTTP filesystem/bucket route `124-134`, JWT stripping/RBAC/rate limit và default 404. Generated dev và e2e cấu hình đều lấy cùng template (`scripts/bootstrap/configure.py`, `e2e/setup/environment.ts:155-160`), nên không cần hai implementation routing. Không cần tắt HTTP/2 trên public listener: HTTP-only public API vẫn có thể chạy HTTP/2; cấm service RPC path là invariant.

## Callers, tests, docs phải cập nhật cùng nhau

- `e2e/tests/api/native-grpc.spec.ts` và `e2e/fixtures/native-grpc.py`: hiện **đòi public GetNode thành công**, dùng generated client trong image ingest-io, verify forged headers và membership revocation; phải thay acceptance thành public RPC bị chặn (Filesystem unary + StreamArchive, private Account/Admin/Ingest, health/reflection nếu được bật sau này). Dùng valid JWT để 404 chứng minh route không tồn tại; unauthenticated denial đơn thuần không đủ. Có thể HTTP/2 request test tại TS thay vì dùng CPU/IO container như public SDK runner.
- Giữ HTTP forged-header/private-resource assertions `e2e/tests/api/gateway.spec.ts`, HTTP membership revocation và HTTP streaming/ZIP trong `files.spec.ts`, `streaming.spec.ts`, processing/upload/search flows. Nếu bỏ public-native revocation test, đảm bảo cùng invariant còn được chứng minh qua HTTP.
- `apps/letfs/internal/grpc/ingest_python_integration_test.go`: embedded Python snippet import `IngestRPC` + gọi `api.call` trực tiếp; phải đổi theo adapter API hoặc giữ raw-generated contract test tách khỏi app orchestration.
- `apps/letfs/internal/grpc/ingest_worker_integration_test.go` + `apps/letfs-ingest/tests/ingest_worker.py`: real Go/Python/Temporal/provider/Qdrant pipeline; constructor/lifecycle fixture phải theo production nếu đổi injection. Test lost acknowledgement, stage replay, object publication/readiness là bằng chứng bảo toàn behavior, không xóa khi đóng public gRPC.
- `apps/letfs/internal/grpc/ingest_integration_test.go`: giữ generated Go transport authority/presence/fencing/replay coverage; chưa cần đổi vì ingress HTTP-only.
- `apps/letfs-ingest/tests/test_activity.py`, `test_ingest_rpc.py`, `test_worker.py`: cập nhật DTO/injection boundary, config validation không dial, closure khi init/shutdown failure. `test_telemetry.py` chỉ đổi khi shared telemetry/injection thay.
- `packages/python/tests/test_contracts.py`: giữ presence empty string và int64 roundtrip; client/server interface packaging. `test_wheel.py` giữ isolated wheel proof; mở rộng nếu thêm handwritten namespace, không sửa test để chấp nhận duplicate PB trong app.
- `packages/contracts/buf.gen.yaml`, `scripts/contracts/generate.py`, generated Go/Python files không cần đổi chỉ vì đóng ingress. Nếu toàn repo chủ động bỏ FilesystemService native implementation, đó là phạm vi lớn khác: nhiều native unit/integration và generated contracts đang dùng, không cần cho HTTP-only **public** API.
- Owning docs: `docs/architecture.md` diagram/auth transport/setup; `docs/setup.md:25`; `docs/api-contracts.md:3,109`; `packages/contracts/rpc-surface.md`; `packages/contracts/authz/action-resource-matrix.md:93-94`; `packages/contracts/public/openapi.yaml` description; `packages/contracts/openapi-base.yaml` description nếu đang gọi native public. `docs/testing.md` public-native assertions và README technology summary chỉ sửa phần ý nghĩa đã đổi. Internal generated transport reference vẫn dùng được nhưng phải gọi là internal protobuf reference, không public contract authority.

## Kiểm tra đề xuất khi triển khai

1. Nhanh: `uv run --locked --package letfs-ingest pytest apps/letfs-ingest/tests/test_activity.py apps/letfs-ingest/tests/test_ingest_rpc.py apps/letfs-ingest/tests/test_worker.py` từ repo root; ruff app theo package scripts.
2. `uv run --locked --package openlet-python pytest packages/python/tests -m 'not integration'`; isolated wheel integration nếu shared namespace/manifests đổi; `pnpm contracts:check` nếu contracts/codegen đổi.
3. Real Python-Go transport/pipeline: Go integration tên `TestIntegrationPythonGeneratedClientPublishesParseViaGoRPC` và `TestIntegrationPythonActivitiesProcessEnrichIndexAndReplay`, giữ cancellation/lost-ack coverage. Go tests cần Docker/actual dependencies, xem docs/testing.md.
4. E2e gateway denial + HTTP files/uploads/streaming/processing/search/revocation, vì ingress và app boundary là public contract. `e2e/playwright.config.ts` vẫn recovery-first, workers=1, retries=0; không tự ý bỏ recovery setup hoặc dựng thêm topology.
5. Static config assertion + render native Envoy validation, kiểm tra không route cluster nào trỏ letfs RPC; internal worker gRPC vẫn chạy thành công qua backend listener.

## Giới hạn và câu hỏi còn lại

Không chạy unit/integration/e2e, build image hay khởi động process; đây là scout chỉ đọc, chỉ script phân tích config/proto được chạy. Chưa kiểm tra deployment ngoài Compose hoặc credential rotation thực tế. Không có blocker từ source cho HTTP-only ingress. Cần controller chốt liệu “shared Python” chỉ là generated contracts hiện tại hay có yêu cầu đưa config/telemetry reusable vào wheel; evidence hiện chưa có app Python thứ hai.

Status: DONE_WITH_CONCERNS
Summary: Đã lập bản đồ generated Python leakage, retry/lifecycle, 27 method gRPC public, hai route Envoy và thay đổi/test/docs cần thiết; HTTP-only ingress không cần thay ingest protocol.
Concerns/Blockers: Failure-report RPC budget có thể dài hơn graceful shutdown; source chưa chứng minh Python application gRPC tracing dù docs nói đã có. Không chạy runtime tests.
