# Cấu hình chung và thư viện cho implementation

Trạng thái: non-secret ở YAML, secret ở dotenv, tham chiếu bằng ${ENV_VARIABLE}. Bỏ thiết kế secret files. Source/tests cũ đã archive; loaders Go/Python đã có, deployment còn đang implementation. [Plan](plan.md) theo dõi phần còn lại.

## 1. Một file cấu hình cho mỗi môi trường

Mỗi deployment có đúng một `openlet.yaml`, được mount readonly vào Platform, LetFS, Leta API/worker và ingest CPU/IO. Tất cả đọc đường dẫn từ `OPENLET_CONFIG`; không dò nhiều đường dẫn hoặc trộn nhiều nguồn cấu hình.

Chung YAML không có nghĩa chung runtime dependency: Platform/LetFS/ingest không đọc/validate `services.leta`, `models.leta`, Redis hoặc các queue Leta, và không cần credentials của chúng. Các section đó chỉ được owning process/deployment đọc khi bật tích hợp Leta. Core phải khởi động và chạy được khi Leta không được triển khai. Concrete Leta API/cleanup transport tiếp tục hoãn; không thêm callback target hoặc `leta_bridge` vào required settings của core trong đợt API Platform/LetFS.

[Mẫu đầy đủ](openlet.example.yaml) chia thành tám section. Mẫu được giữ tại plan sau archive infra cũ; vị trí active khi implement là infra/config/openlet.example.yaml theo [infra design](infra-testing-ci-cd.md).

| Section | Sở hữu |
|---|---|
| `runtime` | Môi trường, log level, shutdown timeout |
| `grpc` | Application gRPC message limit; MVP dùng private network |
| `telemetry` | Đề xuất OTLP/gRPC endpoint, trace sampling và metrics export interval theo [telemetry design](telemetry.md) |
| `auth` | Clerk JWT/API configuration |
| `dependencies` | PostgreSQL host/port, Temporal/queues, SpiceDB, S3, Qdrant, Redis |
| `models` | Provider, embedding/dimensions, reranking, enrichment, Leta catalog/default |
| `services` | Listen/target, database riêng, policy và worker options của từng service |
| `deployment` | Bootstrap-only settings và secret references cho native datastore/admin tools |

`grpc_listen` là socket process bind; `grpc_target` là địa chỉ các caller kết nối, có thể khác do DNS/proxy/port mapping. Platform/LetFS không có HTTP listener. Leta dùng native gRPC clients của hai service; concrete owning cleanup API/transport review sau, chưa thêm inbound listener/config. Async cleanup không là dependency startup/readiness. Leta HTTP/SSE phục vụ consumer của Leta; `services.leta.http_target` chỉ dùng cho optional gateway route, không được Platform/LetFS/ingest load. Gateway có HTTP listener riêng.

Các giá trị trong mẫu là điểm xuất phát implementation, chưa phải thông số đã benchmark. Endpoint `.invalid` phải thay trước khi chạy. MVP application gRPC chỉ dùng mạng private giữa trusted processes, không service Bearer credentials. Production mTLS được bổ sung bằng native gRPC/Envoy khi triển khai; chưa thêm certificate/CA fields trước. TLS/auth của dependencies vẫn theo native client, độc lập với application gRPC.

Model catalog nằm ngay trong `models.leta`, thay cho `leta-models.json`. Leta giữ `ModelCatalog` và validation hành vi hiện tại, nhận dữ liệu YAML thay vì đọc JSON riêng. Embedding model/dimensions/collection chỉ khai báo một lần để LetFS query và ingest index dùng cùng cấu hình. Đổi embedding space cần reindex, không tự động coi vector cũ là tương thích.

## 2. Secrets ở dotenv, YAML chỉ tham chiếu ENV

File dotenv ở repo/deployment root giữ secret values và được ignore khỏi Git/Docker context. Non-secret chỉ nằm trong openlet.yaml. Không tạo secret directory, một file mỗi credential hoặc mount/secret-file resolver.

Ví dụ YAML:

```yaml
dependencies:
  postgres:
    host: postgres
    port: 5432
    sslmode: disable
  s3:
    endpoint: https://s3.example.invalid
    bucket: openlet
    access_key_id: ${S3_ACCESS_KEY_ID}
    secret_access_key: ${S3_SECRET_ACCESS_KEY}
services:
  platform:
    database:
      name: platform
      user: platform
      password: ${PLATFORM_DB_PASSWORD}
```

`${NAME}` là tham chiếu trọn một scalar tới một biến môi trường. Parse YAML trước, rồi resolve đúng secret fields mà role cần. Không chạy shell/envsubst trên raw YAML: secret chứa dấu hai chấm, quote, dollar hoặc newline vẫn là string value, không thay đổi YAML structure. Không default expression, recursive expansion, custom YAML tags hoặc DSL interpolation. Non-secret uppercase strings không bị đoán thành ENV references.

Host/port/database name/user nằm trong YAML; password lấy ENV. Dùng native pgx/psycopg connection settings, không tự nối secret chưa escape vào URI. Redis cũng tách address/database/password. Mẫu MVP dùng chung một PostgreSQL instance cho các database; chưa thêm per-database endpoint override.

Compose nạp root dotenv qua --env-file, rồi environment chỉ truyền secret variables cần cho từng process và OPENLET_CONFIG. Non-secret vẫn từ YAML mount readonly. Compose đọc dotenv không tự inject mọi variable vào container; dùng native environment mapping. Không mount dotenv hoặc mọi credential vào mọi app chỉ để load được cùng YAML.

Chạy trực tiếp ngoài container: dùng dotenv CLI/library chuẩn ở dev launcher để nạp cùng file trước khi chạy command, không tự parse dotenv hoặc dò parent directories trong service. Service chỉ đọc process environment cho đúng tên YAML tham chiếu. Không thêm env overrides cho non-secret.

Ingest CPU không resolve hoặc yêu cầu Clerk/database/S3 admin/model secret; nó dùng signed URLs. IO thêm model/Qdrant credentials. Platform không nhận LetFS DB password; app không nhận bootstrap administrator credentials. Shared YAML có unresolved references của role khác vẫn hợp lệ.

Các giới hạn ingest nằm trong YAML mẫu: `services.letfs_ingest.cpu` giữ layout, số thread và giới hạn PDF/Office/XLSX/output; `models.provider.timeout_seconds` giới hạn provider calls; `models.enrichment` giữ evidence budget và resize/nén ảnh. CPU chuẩn bị model bằng `python -m letfs_ingest.models prepare`, rồi kiểm tra native pipeline offline trước nhận job. Converter subprocess chỉ nhận môi trường hệ thống và đường dẫn YAML, không kế thừa model/database credentials từ worker.

Thiếu/empty ENV cần cho role đang chạy báo startup error với field path và variable name, không dump value/config. Dùng precedence native của dotenv runner, không thêm engine override. Không sửa hoặc in file secret thật trong bước thiết kế. Rotate bằng đổi ENV/dotenv rồi restart.

## 3. Cách load

Go dùng `go.yaml.in/yaml/v3`; Python dùng `PyYAML.safe_load` và Pydantic hiện có. Đưa dependency đang dùng thực sự thành direct dependency, pin bằng module/lockfile. Không dùng Viper, OmegaConf, Hydra, custom YAML parser hoặc config framework.

Shared helper chỉ đọc YAML/chọn section và resolve ${ENV_VARIABLE} cho secret fields role cần. Struct Go/Pydantic model của owning service nhận đúng section/dependency cần dùng. Không dựng hai bản typed model của toàn workspace ở Go và Python, không generate schema/config classes hoặc chuyển config qua RPC.

Validate một lần lúc startup: required field, type, unknown key trong section được dùng và quan hệ thực như chunk overlap nhỏ hơn chunk size, manifest vừa message budget. Sau đó truyền settings/concrete clients vào code. Không `getenv` trong handler, activity hoặc provider module; không lặp validation ở mọi lớp.

CI kiểm tra mẫu qua settings validation của từng owner để bao phủ các section mà một service không dùng. Thiếu secret chỉ kiểm tra khi khởi động role cần nó; lint mẫu không cần production credentials.

Chỉ có một lần đọc lúc khởi động, không watcher/hot reload, remote config hay merge `base + dev + prod + local`. Development/CI/production dùng một file hoàn chỉnh riêng ở từng deployment. Test dùng file tạm, không chỉnh config development.

Temporal workflow không đọc file hoặc environment. Queue/timeouts cần thiết được lấy trước khi start rồi truyền qua workflow input tối thiểu hoặc native activity options có tính deterministic. Không đưa toàn YAML/secrets vào workflow history. Leta giữ tên workflow và semantics hiện tại; thay đường lấy settings ở boundary.

## 4. Những gì là cấu hình

Endpoint, database credential reference, queue, model, quota/member policy, TTL, text/blob limit, parser/worker concurrency và processing budget nằm trong YAML. Không để hidden business defaults ở loader, Compose, entrypoint và implementation cùng lúc. Thiếu setting bắt buộc thì báo lỗi. Default của thư viện được giữ nếu hệ thống không cần tùy chỉnh; chỉ khai báo option khi thực sự dùng.

Theo [architecture đã chốt](workspace-service-redesign.md), storage visibility private/public và public mặc định viewer là invariant, không thêm per-storage public-role knob. Các quy tắc `text | blob`, text chỉ PostgreSQL, artifact readonly, một `files.version`, stage names, public/internal RPC separation, SpiceDB relations và consistency policy vẫn ở code/proto/schema. Không biến invariant hoặc thuật toán thành knobs. Build metadata và các hằng số protocol cũng không phải deployment configuration.

Giá trị policy tạo resource, như quota mặc định, được dùng khi tạo resource và lưu ở database. Thay YAML không âm thầm đổi quota hoặc immutable storage options đã lưu.

## 5. Hạ tầng native

Envoy, Temporal server, PostgreSQL và SpiceDB server không hỗ trợ schema YAML của Openlet. Giữ native configuration của chúng; script bootstrap render những giá trị cần từ cùng `openlet.yaml` sang format native. Đây là build/deployment output, không phải config thứ hai để sửa tay.

Compose giữ topology, pinned images, mounts, resources và healthcheck commands. Nó mount YAML readonly và inject secret ENV theo role từ dotenv; bỏ bản sao app endpoint/model/quota/TTL/task queue trong environment. Application env gồm OPENLET_CONFIG và secrets được YAML tham chiếu. Không rewrite Compose thành deployment DSL.

Chỉ render các file hạ tầng cần thật: Envoy config, Temporal server config và bootstrap database/namespace settings. Template vẫn chứa cấu trúc native của tool; source values lấy từ YAML. Không sinh bộ config con cho từng app. Generated output có secret được đặt trong thư mục private ignored, không log hoặc commit.

Infra credentials cũng lấy dotenv/ENV; deployment trong YAML chứa native bootstrap settings và ${ENV_VARIABLE} references. Chỉ bootstrap/native datastore process nhận chúng. Không phân phối PostgreSQL administrator/Temporal datastore credentials cho app. Native output nếu phải chứa resolved credential vẫn là ignored deployment artifact, không secret-file contract mới của application.

## 6. Thư mục

```text
infra/
  compose.yaml                # topology/build/mounts dùng chung local/VPS
  compose.test.yaml           # native override cho isolated test stack
  config/
    openlet.example.yaml       # mẫu duy nhất được commit
    envoy.template.yaml        # native structure, values từ YAML
    temporal.template.yaml
scripts/
  configure.py                 # đọc YAML, chuẩn bị native deployment outputs
  bootstrap.py                 # init/native migrations, không config framework
packages/
  sdk-go/
    config.go                  # YAML section + secret ENV reference
  sdk-python/
    src/openlet_sdk/
      config.py                # cùng trách nhiệm cho Python
apps/
  platform/cmd/platform/config.go # settings/validation cho Platform
  letfs/cmd/letfs/config.go        # settings/validation cho LetFS
  leta/src/leta/config.py      # đổi nguồn settings, giữ model/runtime semantics
  letfs-ingest/src/letfs_ingest/config.py
.local/
  openlet.yaml                 # một file thật của môi trường local, ignored
  generated/                   # native infra output, ignored
```

Go settings nằm cạnh entrypoint; không thêm package chỉ để giữ một struct. Shared loader chỉ xuất hiện ở SDK vì cả hai Go apps/hai Python apps thực sự dùng, không tạo package config đa ngôn ngữ riêng.

Scripts/E2E/workflows đầy đủ theo [infra/testing/CI/CD](infra-testing-ci-cd.md). Giữ pnpm/TypeScript/Playwright cho API và browser E2E; Go/Python owners vẫn dùng native tools. Không tạo runner riêng trong từng app hoặc lớp orchestration chỉ để bọc native commands.

## 7. Dùng thư viện để bỏ implementation thừa

Repo đã có nhiều SDK native. Vấn đề cần giải quyết là các cơ chế tự viết và lớp bọc vẫn tồn tại quanh chúng. Đợt viết lại gọi concrete SDK trực tiếp; không đặt mục tiêu thêm nhiều dependency.

| Công việc | Chọn | Không viết lại |
|---|---|---|
| PostgreSQL | `pgx/v5`, SQL trực tiếp; Goose migrations | ORM/repository framework, migration runner |
| Clerk | Clerk Go SDK | REST client/request/auth/error plumbing riêng |
| gRPC/protobuf | grpc-go/grpcio, generated stubs, native status/health | DTO/client mirror, tự chế retries/transport |
| Input contract | Protovalidate khi rule nằm trong proto | Nhiều validator lặp cùng field ở handler/service/SDK |
| S3 | AWS SDK v2, native presigning/checksum/multipart/listing | SigV4, provider retry engine, copy compensation |
| SpiceDB | Authzed Go/Python SDK | ACL SQL mirror, local permission cache/invalidation |
| Durable jobs | Temporal SDK | Scheduler/retry/heartbeat/lock framework |
| Qdrant | Qdrant Go/Python clients | HTTP request/response/retry/pagination client riêng |
| YAML/settings | Go YAML v3, PyYAML, Pydantic | Parser, interpolation/merge engine |
| Document parsing | Docling, openpyxl, Python `csv` | PDF/Office parser hoặc generic CSV inference engine |
| Chunks/models | `langchain-text-splitters`, OpenAI client, Pydantic structured output | Token splitter, response repair/provider framework |
| ZIP/images | Go `archive/zip`, `image` và codec cần thực tế | Archive service/job hoặc codec riêng |
| Telemetry | Native OpenTelemetry instrumentation | Tracing protocol/exporter riêng |

Không thay Leta LangChain/OpenRouter/Mirage internals chỉ để đồng bộ dependency choice với ingest. Thư viện mới như Clerk/Qdrant sẽ được pin và smoke ở consumer; chưa coi việc chọn tên thư viện là tích hợp đã chạy.

Native telemetry theo [đề xuất riêng](telemetry.md): init một provider set mỗi process, W3C propagation qua gRPC/Temporal, logs JSON stdout và optional OTLP/gRPC traces/metrics. Không tạo framework exporter hoặc thêm app HTTP metrics listener; monitoring backend được nối sau qua Collector/native infrastructure endpoints.

SDK không giải quyết business invariants hộ ứng dụng: SQL quota, expected version, idempotency receipt transaction, live storage/mount checks và readonly artifacts vẫn cần implementation nhỏ ở owner.

## 8. Phạm vi kiểm tra

Giữ vài kiểm tra có giá trị: mẫu YAML load được ở mỗi owner; sai field/type hoặc thiếu secret cần thiết báo startup error; CPU role không đòi model/database credential. Không tạo matrix test cho mọi config key hoặc khởi stack để test YAML parser.

Đã kiểm tra cú pháp YAML và liên kết tài liệu. Source/tests cũ đã archive và kiểm hash; chưa triển khai loaders, chạy service/Envoy hoặc thay schema/data. Mẫu chưa được runtime load. Config verification dùng synthetic ENV values, không đọc dotenv thật hoặc test matrix mọi secret.

## 9. Không HTTP server ở Platform/LetFS/ingest

[Khảo sát transport](http-json.md) xác nhận Platform/LetFS chỉ cần gRPC + standard gRPC health; ingest CPU/IO là outbound Temporal workers, không HTTP/gRPC server và không listen/target riêng. Gin/grpc-gateway không nằm trong dependencies mới. HTTP clients của S3/Clerk/model vẫn cần; chúng không mở HTTP server. Leta HTTP/SSE và Envoy public HTTP giữ nguyên.
