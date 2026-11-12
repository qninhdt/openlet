# HTTP JSON qua Envoy và gRPC error contract

Cập nhật 2026-11-12. [API contract](api-contract.md) là inventory/bindings đã chốt; ownership theo [workspace resources](workspace-service-redesign.md). Chưa có proto/runtime/Envoy mới. [Thiết kế chính](design.md) chỉ có application gRPC ở Platform/LetFS. Leta HTTP/SSE ngoài phạm vi đổi error contract này.

## 0. Khảo sát: service nào cần HTTP server?

Đã đọc archived Account/Workspace routers và main entrypoints, LetFS entrypoint và ingest worker entrypoint. Account/Workspace HTTP phục vụ CRUD/onboarding và live/ready; không thấy incoming webhook/OAuth callback bắt buộc trong các routers này. LetFS còn HTTP grpc-gateway listener song song native gRPC. Ingest hiện là Temporal worker, đã không có inbound HTTP server.

| Process/luồng | Thiết kế cuối | Có cần app HTTP server/Gin? |
|---|---|---|
| Platform | Native gRPC APIs + standard grpc.health.v1, Temporal worker | Không |
| LetFS | Native gRPC APIs + standard grpc.health.v1, Temporal worker | Không |
| Ingest CPU/IO | Outbound poll Temporal; gRPC client LetFS; signed S3 HTTP client | Không; cũng không cần inbound gRPC server |
| Public JSON | Envoy native transcoder | Chỉ Envoy mở HTTP |
| ZIP | LetFS gRPC stream HttpBody, Envoy trả ZIP bytes | Không thêm HTTP listener ở LetFS |
| Blob/Range transfer | Signed URL, S3 native HTTP | S3/provider server, không app listener |
| Telemetry | OTLP outbound + JSON stdout; infra metrics endpoints native | Không app /metrics listener |
| Health | Standard gRPC health ở hai API; worker process supervision + native Temporal poller/SDK metrics | Không worker health webserver |
| Leta | Giữ HTTP/SSE hiện tại | Có, ngoài scope bỏ HTTP |

API/transport cụ thể Leta tiếp tục hoãn. Async owning cleanup được phép theo architecture mới nhưng không stop-ACK barrier hoặc readiness/hot-path dependency. Không thêm listener/proto Leta trong bước này; public HTTP/SSE hiện có giữ nguyên.

gRPC dùng HTTP/2 dưới transport nhưng không đòi viết Gin/net/http business server hoặc REST router trong ứng dụng. Go net/http vẫn dùng làm HTTP client cho external APIs/SDK; không có mục tiêu xóa standard-library HTTP khỏi code.

Xóa khỏi implementation dependencies/boot paths mới: Gin, otelgin, grpc-gateway runtime, HTTP business handlers và HTTP listen/readiness config của Platform/LetFS. Ingest không thêm FastAPI/Uvicorn/server chỉ để health/metrics. Không dựng webhook/endpoint mới trước nhu cầu.

Worker lỗi startup/fatal phải thoát để supervisor restart. Không dùng heartbeat file/HTTP ping giả worker vẫn poll được; readiness/poller diagnostics lấy từ Temporal/native worker metrics khi triển khai monitoring. Chưa verify actual new containers/Envoy health probes.

## URL và routing hiện tại

Workspace-scoped resources đề xuất dùng /v1/workspaces/{workspace_id}/storages/{storage_id}/...; quota /v1/workspaces/{workspace_id}/storage-quota. Các request route thẳng LetFS, không qua Platform. Workspace ID là tenant context, owning SQL đối chiếu actual parent; không extra Platform membership RPC.

Transcoder cấp listener dùng annotations và native gRPC route sau rewrite: /openlet.platform.v1.PlatformService/ → Platform, /openlet.letfs.v1.LetFSService/ → LetFS. Giữ match_incoming_request_route=false; không regex router/resource proxy. Internal services không nằm public routes/services allowlist và không HTTP annotations.

Full RPC/field/HTTP inventory ở [API contract](api-contract.md); Leta concrete routes chưa chốt.

## 1. Success response

Envoy dùng google.api.http để ánh xạ HTTP path/query/body tới generated RPC. Response JSON là ProtoJSON của protobuf response, không custom success/data/error envelope.

Ví dụ minh họa file header, chưa phải descriptor implementation:

```http
HTTP/1.1 200 OK
Content-Type: application/json

{
  "id": "ea685227-3bec-4a54-87da-10420311753c",
  "name": "report.pdf",
  "fileType": "FILE_TYPE_BLOB",
  "version": "7",
  "sizeBytes": "4096"
}
```

Giữ ProtoJSON mặc định: field names lowerCamelCase, int64/uint64 thành decimal strings, bytes thành base64, enum thành symbolic name; fields unset/default có thể được bỏ. List response dùng items/nextPageToken nếu proto định nghĩa các field đó; không dựng pagination envelope ngoài protobuf.

Unary thành công thông thường trả HTTP 200. HTTP annotation không tự tạo semantics 201 cho create hoặc 202 cho workflow admission. Admission trả workspace.state=provisioning/deleting trong protobuf response; không thêm adapter chỉ để giữ HTTP status cũ. Empty protobuf response thường serialize thành {}, không mặc nhiên 204.

## 2. Application error

Bật convert_grpc_status: true trong native Envoy transcoder config. Khi upstream gRPC trả lỗi trước response body, Envoy chuyển google.rpc.Status từ grpc-status-details-bin, hoặc dựng Status từ grpc-status/grpc-message nếu chưa có rich details.

Ví dụ quota error:

```http
HTTP/1.1 429 Too Many Requests
Content-Type: application/json

{
  "code": 8,
  "message": "Workspace storage quota exceeded",
  "details": [
    {
      "@type": "type.googleapis.com/google.rpc.ErrorInfo",
      "reason": "QUOTA_EXCEEDED",
      "domain": "openlet.letfs"
    }
  ]
}
```

code=8 là gRPC RESOURCE_EXHAUSTED, không phải HTTP code. HTTP status nằm ở status line. Body là Status trực tiếp, không mặc định có outer error object. Client xử lý theo gRPC code và ErrorInfo.reason; message là human-readable, không parse để điều khiển logic.

google.rpc.Status/ErrorInfo descriptors phải nằm trong generated public descriptor, gồm imports. Không gửi raw database/provider errors hoặc secrets trong message/details.

| gRPC status | HTTP mapping thường dùng |
|---|---:|
| INVALID_ARGUMENT, FAILED_PRECONDITION, OUT_OF_RANGE | 400 |
| UNAUTHENTICATED | 401 |
| PERMISSION_DENIED | 403 |
| NOT_FOUND | 404 |
| ALREADY_EXISTS, ABORTED | 409 |
| RESOURCE_EXHAUSTED | 429 |
| INTERNAL, UNKNOWN, DATA_LOSS | 500 |
| UNIMPLEMENTED | 501 |
| UNAVAILABLE | 503 |
| DEADLINE_EXCEEDED | 504 |

## 3. Không phải RFC Problem Details

Native google.rpc.Status JSON không phải RFC 9457 (thay RFC 7807). RFC Problem Details dùng application/problem+json và các members như type/title/status/detail/instance. Status dùng application/json và code/message/details; đổi Content-Type đơn thuần không biến nó thành Problem Details.

Lựa chọn đã chốt là giữ native gRPC/Envoy error contract, không thêm Problem Details mapper hoặc HTTP error implementation thứ hai. Đây vẫn là HTTP API bình thường; RFC 9457 không phải điều kiện bắt buộc để một HTTP API hợp lệ.

Chấp nhận hai dạng application error: Platform/LetFS qua Envoy dùng Status; Leta/HTTP services giữ Problem Details hoặc contract hiện có. Các API mới dùng machine-readable reasons nhất quán khi cùng ý nghĩa; không ép services hiện có đổi body/envelope. RFC 9457 chỉ quy định lỗi, không quy định success envelope.

Nếu consumer thật cần dùng cả hai dạng, decode một lần tại HTTP boundary đang dùng thành HTTP status/reason/message; không parse message để điều khiển logic. Không dựng frontend mới, SDK client mirror hoặc normalization package cho nhu cầu tương lai. Native Envoy local replies/SSE/ZIP/S3 vẫn theo giới hạn riêng ở mục 4.

Native transcoder print_options chỉ điều chỉnh cách in ProtoJSON; native local_reply_config chỉ tùy chỉnh Envoy-generated local replies, không rewrite mọi upstream body thành RFC 9457. Không có flag native duy nhất để thống nhất tất cả. Lua/Wasm mapper sẽ là code riêng phải bảo trì/test; không đưa vào đợt này.

## 4. Gateway errors và streaming

convert_grpc_status chỉ chuyển upstream gRPC errors đủ điều kiện; nó không tự normalize mọi lỗi. JWT rejection, invalid JSON, unknown route hoặc upstream connection failure có thể là native Envoy local replies với body khác. Client luôn xử lý non-2xx và Content-Type trước khi decode rich application error. Chưa xây một global gateway-error envelope hoặc Lua/Wasm translation framework.

Public services/methods được allowlist bằng routes/descriptor và HTTP annotations; auto_mapping=false. Không public native internal gRPC paths chỉ vì chúng không có HTTP annotation.

DownloadArchive trả stream google.api.HttpBody: Content-Type application/zip và raw bytes, không JSON/base64 array. Khi body đã bắt đầu stream, lỗi muộn không thể được thay toàn response bằng JSON Status/Problem Details; tải thất bại và caller retry. Signed S3 transfer responses thuộc native S3 contract, không Envoy JSON. Leta HTTP/SSE giữ contract hiện tại.

## 5. Verification

Pin Envoy image rồi smoke success ProtoJSON, rich ErrorInfo/HTTP status, local JWT rejection, internal route rejection và ZIP bytes/late stream failure. Không nhân business integration matrix qua HTTP. Chưa chạy các smoke này ở bước thiết kế.

## Nguồn chính thức

- [Envoy transcoder và arbitrary content](https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/grpc_json_transcoder_filter).
- [Envoy convert_grpc_status](https://www.envoyproxy.io/docs/envoy/latest/api-v3/extensions/filters/http/grpc_json_transcoder/v3/transcoder.proto#envoy-v3-api-field-extensions-filters-http-grpc-json-transcoder-v3-grpcjsontranscoder-convert-grpc-status).
- [ProtoJSON mapping](https://protobuf.dev/programming-guides/json/).
- [RFC 9457 Problem Details](https://www.rfc-editor.org/rfc/rfc9457.html).
- [Standard gRPC health checking](https://grpc.io/docs/guides/health-checking/).
- [Temporal Python workers](https://docs.temporal.io/develop/python/workers).
