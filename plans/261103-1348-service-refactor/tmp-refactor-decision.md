# Quyết định refactor đã chốt

Được người dùng yêu cầu triển khai ngày 2026-11-03. Đây là quyết định hiện hành, thay thế phương án app/jobs và client nội bộ nằm riêng trong từng ứng dụng.

## Outcome

Refactor cả module lẫn code của Account, Workspace, letfs và letfs-ingest. Được xóa code, gộp/tách file và viết lại. Không chấp nhận chỉ move/rename. Loại dead code, legacy adapter, abstraction và chuyển đổi dữ liệu thừa; giữ đầy đủ hành vi nghiệp vụ và bảo đảm dữ liệu hiện có.

## Cấu trúc

- Go: cmd/server; internal/config; package nghiệp vụ user/workspace/filesystem; internal/temporal; internal/transport/http và grpc; internal/clients chỉ cho external providers; migrations.
- Python worker: worker.py, config.py, temporal/activities.py, processing/, parser/, clients/ cho model/search providers.
- Không có app hoặc jobs. Nghiệp vụ không import HTTP framework, protobuf/gRPC hay Temporal SDK. Interface khởi chạy công việc được định nghĩa tại phía nghiệp vụ; adapter Temporal triển khai. Activity gọi bước nghiệp vụ, không gọi lại entrypoint khởi chạy workflow.
- Workflow điều phối, activity thực thi, worker đăng ký và quản lý tài nguyên. Không dựng nhiều file rỗng; tách theo quy trình thật khi lớn.
- packages/contracts: proto, public OpenAPI, authz và fixture kiểm tra chung. Giữ namespace proto/version và generation paths hiện có khi không cần phá hợp đồng.
- packages/go: gen, clients/account|workspace|letfs, identity, authz, rpc, httpapi, apperr, config, telemetry, temporal, testfixture.
- packages/python: generated openlet_api riêng với handwritten openlet; clients/account|workspace|letfs, identity, authz, rpc, httpapi, errors, config, telemetry, temporal. Go/Python tương đương về năng lực/hành vi, idiomatic implementation riêng. Không chỉ cung cấp Python stub.
- Client dùng chung theo service đích; native input/output, không chia sẻ model SQL/nội bộ service. Protobuf chỉ trong generated bindings, shared clients và gRPC server adapter.

## Giao tiếp và quyền

Public HTTP; internal gRPC authenticated, method allowlist, TLS/deadline, trace propagation. Workflow từng service sở hữu, hoạt động remote qua local activity và shared gRPC client. Go letfs workflow có thể gọi CPU/I/O Python activities thuộc cùng hệ thống processing. Async admission dùng stable ID và reconciliation; không giả định DB + Temporal atomic. Service caller khác acting user; chỉ caller được phép delegate mới được truyền actor. Resource owner luôn thực thi quyền, không tin client-side check.

## Constraints và non-goals

Không schema/data changes, deploy, commit hoặc thêm service Agent. Preserve authorization, quota, idempotency, generation fences, bounded transfers, cancellation, cleanup và recovery. Không generic repository framework. Không compatibility shim cho mã cũ trong greenfield; historical Temporal histories cần tạo lại nếu workflow thay đổi.

## Acceptance

1. Không còn app/jobs hoặc duplicate internal clients ở app.
2. HTTP, nghiệp vụ và workflow/activity không dùng protobuf/gRPC types/status.
3. Go/Python shared clients và cơ chế auth/identity/authz/config/errors/telemetry/Temporal dùng được bởi service mới.
4. Public ingress HTTP-only; service calls đi qua internal gRPC, giữ quyền và fencing.
5. Native build/check/unit/workflow/integration và API journeys được kiểm tra theo môi trường; ghi rõ provider checks không chạy.
6. Review code-level deletion/simplification và cập nhật owning docs, commands, config, tests, fixtures; không dead branches/legacy wrappers.

## Execution

- [x] Hoàn thiện shared packages và neutral client contracts.
- [x] Refactor Go nghiệp vụ, transport và Temporal; xóa app/jobs/duplicate code.
- [x] Refactor Python processing/Temporal và bổ sung shared parity.
- [x] Wiring/codegen/import-boundary checks, docs, review và verification.

## Kết quả

Đã hoàn tất trên cả 4 service và hai shared package. [Bản kiểm chứng](verification.md) ghi các lỗi đã sửa, kết quả kiểm tra native và parser, 33 API journeys, một recovery journey và replay history mới của cả 3 Go service. Không commit/deploy hoặc thay đổi schema/dữ liệu môi trường hiện có. Live external-provider checks và compatibility với history của kiến trúc cũ nằm ngoài phạm vi đã chốt.
