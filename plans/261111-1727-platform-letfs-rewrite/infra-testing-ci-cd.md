# Infra, E2E và CI/CD trong cùng đợt rewrite

Trạng thái: người dùng đã chốt, gồm giữ TypeScript + Playwright cho hai projects api/browser. Legacy infra/tooling/testing đã archive; Compose/configure/bootstrap/runners/workflows đã implementation; 4 API journeys và PostgreSQL recovery drill pass local, remote CI/deploy chưa chạy. Target là một VPS/VM rỗng chạy Docker Compose; domain/TLS cụ thể xử lý khi triển khai host thật, không mở thêm thiết kế provisioning trong lượt này.

[Plan](plan.md) theo dõi execution; [application design](design.md), [config](configuration.md), [YAML mẫu đã chốt](openlet.example.yaml) và [archive report](../reports/implementation-261111-1948-archive.md) là các owning references.

## 1. Kết quả và công cụ

Giữ TypeScript + Playwright hiện tại cho E2E, với hai projects api và browser. Polyglot backend không yêu cầu test runner cùng ngôn ngữ: E2E gọi HTTP/UI công khai, còn unit/integration của từng owner dùng Go/Python native. pnpm quản lý TypeScript dependencies; Make là entry point infra/native commands, Docker Compose giữ topology và GitHub Actions giữ CI/CD. Không thay Playwright bằng pytest hoặc bỏ browser khỏi thiết kế vì frontend chưa có.

| Phần | Công cụ và ranh giới |
|---|---|
| Local commands | GNU Make, recipes ngắn gọi công cụ native hoặc sáu scripts ở mục 5 |
| Go | go work/modules, gofmt, go vet, go test; integration theo native build tags |
| Python | uv workspace/lock, Ruff, pytest/pytest-asyncio; chọn package thay vì install CPU dependencies cho mọi command |
| Contracts | Buf lint/generate/build, pinned Go/Python protobuf plugins; không patch generated OpenAPI |
| Containers | App-owned multi-stage Dockerfiles, Docker Compose v2, BuildKit/Buildx cache |
| API E2E | TypeScript + @playwright/test, APIRequestContext/request fixture và native assertions |
| Browser E2E | Cùng Playwright, dùng page/context/locators và storageState khi có frontend |
| Test identity | jose ký test JWT; Envoy vẫn xác minh chữ ký/JWKS thật; không custom issuer server |
| External API fixtures | Một WireMock container cho Clerk/JWKS/model HTTP; không tự viết fake-provider/control server |
| Local/test S3 | RustFS 1.0.5 single-node/single-disk, console tắt; official image/digest tại [test Compose](../../infra/compose.test.yaml) |
| CI/CD | GitHub Actions, GHCR, native SSH/SCP, Docker Compose trên VPS |

Không thêm Kubernetes, Helm, Terraform/Ansible, Jenkins, ArgoCD, test framework, service registry, deploy controller hoặc monitoring stack. API project không launch browser. Browser project thuộc cùng e2e/ và được triển khai khi có frontend thật; không fake UI hoặc viết browser specs chạy xanh trước khi có sản phẩm.

## 2. Cấu trúc thư mục đích

```text
Makefile
package.json
pnpm-workspace.yaml
pnpm-lock.yaml
go.work
pyproject.toml
uv.lock
apps/
  platform/{Dockerfile,migrations/,tests/,...}
  letfs/{Dockerfile,migrations/,tests/,...}
  letfs-ingest/{Dockerfile,tests/,...}   # CPU/IO build targets
  leta/{Dockerfile,migrations/,tests/,...}
packages/
  contracts/{proto/,authz/,buf.yaml,buf.gen.yaml,generated/}
  sdk-go/{gen/,...}
  sdk-python/{src/,...}
infra/
  compose.yaml
  compose.test.yaml
  config/
    openlet.example.yaml
    envoy.template.yaml
    temporal.template.yaml
scripts/
  configure.py
  bootstrap.py
  e2e.sh
  deploy.sh
  backup.sh
  restore.sh
e2e/
  package.json
  tsconfig.json
  playwright.config.ts
  Dockerfile
  openlet.test.yaml
  tests/
    api/
      gateway.spec.ts
      collaboration.spec.ts
      files.spec.ts
      processing.spec.ts
      leta.spec.ts
    browser/                           # specs chỉ tạo khi frontend có thật
      authentication.spec.ts
      files.spec.ts
      leta.spec.ts
  fixtures/
    api.ts                             # authenticated request contexts/test identities
    browser.ts                         # khi browser flow cần auth/data fixture thật
    files/sample.xlsx
    wiremock/                          # static HTTP mappings/bodies thực sự dùng
.github/workflows/
  ci.yaml
  release.yaml
.local/                                # ignored outputs, không source/config authority
  generated/
  e2e/
  backups/
archive/2026-11-11/                     # không import/build/lint/test
```

Unit/integration tests nằm ở owner, E2E cross-service nằm ở e2e/. Playwright projects chia theo api/browser, không chia theo backend language/service runtime. Fixtures chỉ có owner và consumer thực; không tạo fixtures package, test SDK, generic base class hoặc một helper cho từng RPC. Generated outputs, logs và backup không nằm trong infra/ hay scripts/. Không tạo Page Objects/helpers trước khi có UI/logic lặp thực sự cần chúng.

Chỉ có hai Compose files được viết tay: một topology gốc và một test override. Release có thêm image-lock Compose override do pipeline sinh tự động, không phải file cấu hình thứ ba để sửa tay. Không compose.dev/prod/service/phase variants, không custom merge/include engine. Compose merge/anchors dùng native; mọi relative path theo base file và được kiểm bằng compose config --quiet.

Mẫu YAML hiện nằm trong plan để giữ design reference sau archive; khi implement, mẫu active ở infra/config/ theo cấu trúc trên. Mỗi môi trường có một YAML hoàn chỉnh. openlet.test.yaml là YAML của test environment, không là lớp override được service merge với development config.

## 3. Topology và config

Core Compose gồm PostgreSQL, SpiceDB, Temporal, Qdrant, Platform, LetFS, ingest-cpu, ingest-io và Envoy. Leta API/worker, Redis và Leta-specific init jobs nằm trong native Compose profile `leta`, bật khi cần chạy tích hợp. Vẫn chỉ hai Compose files viết tay; profile không thêm deployment framework. One-shot init/migration jobs dùng native tools theo dependency order. Không custom bootstrap image chứa bản sao business SDK hoặc authz coordinator.

Platform/LetFS/ingest, core migrations và health không có `depends_on`, required endpoint/secret, stop callback hoặc barrier tới Leta. Envoy có thể route Leta khi profile được chọn; route không sẵn sàng của tích hợp không làm routes core ngừng phục vụ. `compose up --wait` và bootstrap core không kéo profile Leta vào dependency graph. Chung repo/YAML/datastore instance chỉ là cách đóng gói, không làm Leta thành subsystem bắt buộc của Platform.

- Một PostgreSQL instance, database/role riêng cho Platform, LetFS, SpiceDB, Temporal và Temporal visibility; database/role Leta chỉ init khi chọn tích hợp đó. Không cross-database SQL trong business code.
- Platform/LetFS mỗi app một image. Ingest một Dockerfile với hai targets CPU/IO. Leta API/worker dùng chung một image, khác command. Không image riêng chỉ để đổi startup role.
- Envoy là entry point của application; backend/admin/datastore ports private. Base có thể bind gateway vào loopback cho local/VPS; test override bỏ host ports, runner ở cùng Docker network.
- S3/Clerk/model của môi trường thật dùng provider đã cấu hình. Local/test override thêm RustFS, WireMock và test runner; core dùng PostgreSQL/SpiceDB/Temporal/Qdrant và ứng dụng thật. Redis/Leta chỉ chạy cho suite tích hợp Leta được chọn.
- PostgreSQL/SpiceDB/Temporal/application migrations là one-shot jobs. Native readiness/dependency conditions ngăn API mở trước khi migrations thành công. Không migration retry loop vô hạn hoặc app startup âm thầm sửa schema.
- Platform/LetFS dùng standard gRPC health; Leta theo health contract đồng bộ với owner refactor. Worker dùng native startup/fatal exit và supervisor, không thêm HTTP listener/heartbeat file/lease để báo healthy. Compose running status của worker không được báo thành bằng chứng mọi queue đã được xử lý.
- Compose volumes persistent ở môi trường thật. Test project có volumes riêng và teardown chỉ xóa resources của project đó. Không down -v trên deployment thật.
- Image versions/digests và runtime dependencies được pin khi implement và verify registry. Không dùng latest hoặc tự build dependency server từ source trong mỗi CI run.

Config giữ đúng quyết định đã chốt: non-secret trong một openlet.yaml, secret trong root dotenv/process ENV, YAML tham chiếu ${ENV_VARIABLE}; mỗi process chỉ nhận secret cần dùng. Không secret directory, per-key files, generated service tokens hoặc non-secret defaults rải trong Compose/entrypoints/scripts.

Compose giữ topology/images/builds/mounts/resources/health commands. Native Envoy/Temporal configs được render từ cùng application YAML, lưu ở ignored generated/. Renderer chỉ map các fields đã biết; không config DSL, recursive interpolation, discovery, hot reload hoặc override precedence engine. Không print resolved config/Compose environment ra CI logs. Native outputs bắt buộc chứa credential là private generated artifacts, không application secret-file contract.

RustFS test service đã có trong `infra/compose.test.yaml`: một process single-node/single-disk, console tắt, volume riêng của Compose project, giới hạn 1 CPU/512 MiB và native `/health/ready`; không publish host ports. Sau khi cấp process ENV secrets của test, `OPENLET_CONFIG=e2e/openlet.test.yaml uv run --locked python scripts/configure.py --test` render `.local/generated/compose.test.runtime.yaml` chứa native RUSTFS_ACCESS_KEY/RUSTFS_SECRET_KEY theo ENV refs trong YAML. Compose dùng override này cùng test topology; không đọc dotenv thật trong CI. Base Compose và full-stack runner đã pass; lệnh trên chỉ render config, scripts/e2e.sh sở hữu full run/teardown. Test dùng volume mới, không gắn lại dữ liệu của provider cũ.

## 4. E2E và test ownership

### Môi trường

scripts/e2e.sh sở hữu Compose lifecycle; Playwright sở hữu projects/test cases/fixtures/assertions/reporters. Fixtures không tự tạo Docker stack hoặc có global setup controller thứ hai. Mỗi run có đúng một full stack, reuse giữa các tests; khởi đầu một worker, không parallel stacks. Không project recovery/setup bắt buộc làm dependency của mọi API suite.

Core gateway/collaboration/files/processing specs chạy khi không có Leta. Đây cũng là bằng chứng core độc lập: workspace CRUD, grant/revoke và delete hoàn tất khi Leta không chạy. `leta.spec.ts` là suite tích hợp được chọn riêng, bật cùng profile `leta`, không là prerequisite của core checks/release. Vẫn giữ đúng hai Playwright projects api/browser; chọn suite bằng native file selection hoặc grep/tag, không tạo project/runner mới. Khi chọn suite Leta thì dùng Leta thật, không mock để làm core giả vờ độc lập.

playwright.config.ts dùng cùng testDir và native testMatch theo api/**/*.spec.ts, browser/**/*.spec.ts. API gọi APIRequestContext trực tiếp, không sinh TypeScript SDK/DTO/client mirror cho từng RPC; private gRPC business tests vẫn ở owning Go/Python integration layer. Browser dùng page/context thật và chỉ assert user-visible flows. Hai projects có thể chạy riêng hoặc cùng run trên một stack khi frontend đã có.

API Docker target dùng Node/pnpm, không cài/chạy browser binaries. Browser target dùng official Playwright image cùng version với locked @playwright/test, chỉ build/run khi có browser suite. Một Dockerfile, không browser launcher script hoặc image riêng cho từng spec. Trước khi có frontend, CI chỉ chạy --project=api; không --pass-with-no-tests hoặc placeholder browser tests.

Runner chạy bên trong Docker network: HTTP gọi http://envoy:8080, signed S3 URLs dùng hostname s3 mà cả app và runner đều truy cập được. Không publish storage/control ports, rewrite signed hostname hoặc làm storage proxy để vá split host/container networking.

Project name local cố định theo worktree; CI dùng run/job identity native. Nếu local project đang có resources từ run khác thì báo rõ, không tự chiếm/xóa hoặc đổi port. Cleanup dùng Compose project scope/labels native, không ownership registry/lock files/lease system. Shell trap thu logs/ps rồi cleanup kể cả lỗi hoặc cancel có thể bắt được; runner bị kill cứng cần vận hành cleanup project, không xây janitor framework.

CI tạo đúng một bộ dotenv/YAML của test environment, dùng ephemeral test credentials; không đọc dotenv thật của developer. jose tạo key/token trong fixture, public JWKS và Clerk/model responses qua WireMock. Chỉ giả lập external APIs; không giả Platform/LetFS/Leta, parsing activity, authorization graph, storage, index hoặc Temporal. Browser auth sẽ dùng auth flow/test support thực của frontend; không tự coi backend JWT là một browser session.

RustFS đã pass smoke bằng native Go AWS SDK/options của LetFS: signed PUT/HEAD CRC32C, multipart FULL_OBJECT CRC32C, Range GET, conditional overwrite rejection, bad signature/checksum rejection, list và batch delete. So cùng resource limits/workload nhỏ, RustFS idle/sau smoke khoảng 21/26 MiB so với SeaweedFS 126/171 MiB; image unpacked khoảng 330 so với 755 MiB. Chi tiết và giới hạn phép đo ở [plan](plan.md). Không viết compatibility proxy hoặc tắt kiểm tra của application để test xanh. Full API E2E trên RustFS cũng đã pass; các số RAM trên vẫn chỉ là provider smoke, không chứng minh production S3 provider tương thích.

### Các lớp kiểm chứng

| Owner/lớp | Nội dung cần chứng minh | Không nhân đôi |
|---|---|---|
| App unit | Pure path/text/export/layout/index logic hoặc workflow decisions có giá trị | Không test SDK internals, deleted defensive mechanisms hoặc mọi getter |
| App integration | Real SQL/graph/storage cần cho invariant: quota/version/idempotency, readonly/mount, upload publication, move cycle | Native fixtures theo suite/owner; không boot full stack mỗi test |
| E2E gateway | JWT/bootstrap/trusted headers/internal isolation; unary ProtoJSON/Status; ZIP bytes | Vài boundary cases, không toàn RPC matrix qua HTTP |
| E2E collaboration | Onboard/invite/share/revoke và file access qua public API | Không lặp mọi ACL permutation đã có integration |
| E2E files | Một hành trình text/blob upload/download, copy/trash/restore và một số failure contracts quan trọng | Không lặp toàn CRUD/SQL concurrency matrix ở HTTP |
| E2E processing | Blob XLSX nhỏ qua CPU ParseBlob + IO EnrichAndIndex, artifacts readonly và search bằng Qdrant thật | Không mock pipeline; không OCR/PDF model suite trên mọi PR |
| E2E Leta khi được chọn | Agent dùng gRPC file/tool, events/HITL storage approval và xử lý revoke/resource đã xóa | Không core stop callback; không refactor/domain-test Leta từ infra; phối hợp owner Leta |
| Browser khi có frontend | Login/workspace, file editing/upload/status, agent events/HITL được render và thao tác đúng | Không lặp mọi API status/schema assertion qua UI |

Text không dispatch, quota/content races, duplicate append và stale processing publication được chứng minh chủ yếu tại owning integration layer. API E2E giữ vài assertions quan trọng như wrong storage/revoke, idempotent append hoặc quota rejection, không test lại mọi nhánh. Dùng expect.poll/toPass với timeout hữu hạn cho API async state; browser dùng locators/web-first assertions. Không waitForTimeout để chờ business completion hoặc polling/retry framework riêng. Không parse SSE/ZIP bằng protocol engine tự viết; dùng thư viện cần thiết khi có assertion thật.

Không bắt buộc mọi test theo một long journey phụ thuộc thứ tự. Mỗi case tạo dữ liệu qua public APIs/fixtures, browser seed dữ liệu bằng API khi phù hợp rồi assert UI. Chỉ giữ một số product journeys thật; không class hierarchy, scenario DSL, record/replay framework hoặc permission/transport matrix.

Leta tests cũ đã archive toàn bộ theo scope mới. Owner Leta viết tests cần thiết cho code refactor của họ; infra sở hữu E2E cross-service, không giữ legacy tests để ép tương thích. Workflow replay là native Temporal check khi còn lịch sử cần tương thích, không workflow framework/test project riêng; không mặc định import history cũ vào hệ thống dùng database mới.

PDF/OCR/parser fixtures nặng, live Clerk/S3/model quality và backup/restore drill chạy chủ động trước release phù hợp hoặc khi phần đó thay đổi. Không gọi model trả phí trong default PR, không recovery suite bắt buộc chạy trước mọi API test, không fault-injection/control server hay matrix mọi crash/interleaving. Không đưa Docker socket vào E2E runner chỉ để các test tự điều khiển toàn host.

## 5. Đúng sáu script files

| File | Trách nhiệm | Không chứa |
|---|---|---|
| scripts/configure.py | Parse YAML + ENV refs và render native Envoy/Temporal config; mode check cho validation | Generate credentials, sửa dotenv, merge framework, app config copies |
| scripts/bootstrap.py | Thứ tự concrete init: database/roles, native migrations, authz schema, namespace và collections cần dùng | Migration engine, graph rebuild từ SQL, operation state/journal hoặc retries riêng |
| scripts/e2e.sh | Compose build/up/wait, run Playwright api/browser project được chọn, giữ exit status, logs và teardown | Test assertions, fake providers, general environment manager |
| scripts/deploy.sh | Trên VPS nhận release bundle, pull images, stop writers, gọi backup/bootstrap, up --wait và kiểm native health | Build source trên VPS, blue/green, distributed deployment lock hoặc auto schema rollback |
| scripts/backup.sh | Dừng writers theo procedure và gọi native pg_dump cho canonical databases; ghi backup ngoài container | Custom snapshot protocol, S3 byte copy engine hoặc rebuild authority |
| scripts/restore.sh | Native pg_restore vào target trống/đã dừng được chỉ định, rồi kiểm tra dữ liệu/health | Merge hai lịch sử ghi, schema converter hoặc tự xóa deployment đang dùng |

Bootstrap là orchestration mỏng: PostgreSQL/native SDK và các native Goose/SpiceDB/Temporal tools làm việc thực sự. Scripts Python dùng dependencies nhẹ được pin; không install Docling/Leta runtime trên host chỉ để render/init. Không copy loader/recovery/generator cũ sang scripts mới.

Makefile gọi trực tiếp native commands cho generate, check, test, integration, images, up, down, logs và gọi sáu scripts trên khi cần. Focused owner commands vẫn là go/uv/pytest native; TypeScript E2E dùng pnpm exec playwright test --project=api hoặc --project=browser. CI không có command semantics riêng. Không tạo build.sh/test.sh/check.sh/wait.sh/common.sh cho các lệnh một hai dòng, không phân thư mục theo plan/phase/service khi không có boundary thật.

Buf configs sở hữu generation; Make generate chỉ gọi Buf và descriptor build. Không contracts/generate.py chỉnh OpenAPI, generate SDK mirrors hoặc scan source để tạo action registry. Chỉ generate OpenAPI khi có consumer thực; không bắt buộc trong E2E vì test hành vi thật.

Nếu script mới được đề xuất, trước hết phải chỉ ra trách nhiệm không thuộc sáu file hiện có và không thể diễn đạt gọn bằng native command. Số file không là quota phải viết đủ boilerplate; file chỉ xuất hiện khi triển khai hành vi thật.

## 6. CI: một workflow, hai jobs

ci.yaml chạy pull_request và push vào main/dev; không chạy thêm push pipeline trùng cho mọi feature branch. Job checks luôn được tạo để required check không pending do workflow-level path filters. Dùng path-filter action có sẵn, pinned SHA, với mapping vài owners rõ ràng; không tự viết affected-project graph/detector.

1. checks: native formatting/lint/build/unit và Buf generation drift khi contracts đổi; E2E đổi chạy pnpm frozen install + TypeScript check. Chỉ cài/chạy toolchain/packages của owner bị ảnh hưởng. Infra/scripts đổi chạy Ruff/ShellCheck/actionlint và native config validation. Docs/plans-only không khởi Docker stack.
2. integration: sau checks, chỉ khi runtime/contracts/infra/E2E đổi. Chạy owner integration cần thiết, rồi đúng một Compose stack và Playwright API E2E nhỏ ở mục 4. Core suites không yêu cầu Leta; chỉ bật suite/profile Leta khi kiểm consumer tích hợp thực sự bị ảnh hưởng hoặc chủ động chọn. Khi có frontend, thêm browser project cho affected UI/user journeys, bắt đầu với Chromium. Native integration fixtures chỉ boot dependencies cần cho invariant, reuse theo suite; full stack chỉ một lần cho E2E. Không chạy cùng business assertions lần nữa ở SDK/layer/transport khác.

Shared contracts/SDK đổi thì mở rộng affected consumers; không chỉ compile package producer. app code đổi chạy owner checks và system wiring cần thiết. Integration/E2E result không cache; chỉ cache Go modules/build, uv/pnpm downloads và BuildKit layers. CPU dependency/model layers chỉ invalidated khi relevant lockfile/Dockerfile/model pin đổi; PR XLSX không download OCR models lúc test.

Concurrency group theo PR/ref, cancel outdated CI runs. Timeouts hữu hạn, không tự retry toàn job để giấu flaky test. Upload Playwright JUnit/HTML và failure compose logs/ps bằng native artifacts; browser giữ trace/screenshot khi lỗi bằng native Playwright, không framework recorder riêng. Không huge Docker image tar/report matrix cho mọi PR. Pin actions/tool versions; CI default read-only, không production secrets, SSH hoặc registry push từ untrusted PR.

Không một job cho mỗi service/test type/transport/OS. Một Linux architecture phù hợp VPS, không matrix multi-arch trước nhu cầu. Budget là wall time/container starts/lock waits đo được sau implementation, không hứa CI rẻ hơn chỉ từ số files.

## 7. Release và deploy VPS

release.yaml chạy chủ động từ commit/default branch đã qua CI hoặc release tag được chọn theo policy đó; chưa auto deploy mọi PR/push. Có hai jobs: build-and-verify, deploy. Native GitHub concurrency theo môi trường chặn hai deploy đồng thời; không lock/lease trong application hoặc custom deployment registry. Không cancel deploy đang migrate giữa chừng.

- Build app images của cùng một commit, chạy E2E trên chính image set đó, rồi push cùng artifacts vào GHCR. Không test source tree xong deploy một image rebuild khác. PR dùng build cache; release có verification riêng trên artifacts sẽ deploy, không upload/reuse untrusted PR images.
- Pipeline sinh image-lock Compose override chứa refs immutable theo digest và release bundle gồm Compose/native templates, scripts cần vận hành, public descriptor/authz schema. Migrations nằm trong owner images, dùng native Goose; không yêu cầu Go/Node hoặc application source trên VPS.
- SCP/SSH đưa bundle vào /opt/openlet/releases/<sha>. VPS có Docker Compose và Python/uv cho scripts nhẹ; openlet.yaml và root dotenv là cấu hình riêng của VPS, không copy secrets từ CI hoặc developer. Native generated outputs đặt riêng, không sửa bundle nguồn.
- Pull trước khi dừng dịch vụ. Sau đó stop ingress/writers, backup dữ liệu, init/migrate bằng native jobs, up --wait rồi kiểm health. Worker running status không thay thế release E2E. Chỉ xóa test volumes; deploy thường giữ volumes. Chấp nhận maintenance downtime ngắn, không blue/green/canary/orchestrator.
- Rollback image set cũ nếu schema tương thích. Nếu migration không tương thích, dừng writers và restore backup phù hợp trước khi chạy bộ cũ. Không tự động down-migrate hoặc merge dữ liệu mới vào hệ cũ. Backup/restore phục vụ hệ mới, không là importer database cũ đã từ chối.

SpiceDB là canonical data nên backup datastore cùng Platform/LetFS/Temporal sau khi writers core đã dừng; nếu deployment chọn kèm Leta thì backup database Leta theo procedure của owner. Đây là operational backup của deployment, không callback/stop ACK trong workspace deletion. Core backup/restore không yêu cầu Leta process tồn tại hoặc healthy. Redis không canonical, Qdrant derived. Backup PostgreSQL không thay thế backup/versioning của S3; object retention/restore dùng native provider và phải được kiểm chứng trước claim phục hồi đầy đủ. Giữ bản backup ngoài VPS để tránh mất cả dữ liệu lẫn backup khi host hỏng; không viết sync/backup service riêng trong application.

VPS provisioning chi tiết, domain/TLS, registry/host credentials và lịch off-host backup được cấu hình khi target thật sẵn sàng. Chưa dựng route, gửi SSH hoặc deploy trong lượt này. Không thêm một tập config/scripts dự phòng cho các cloud/Kubernetes chưa dùng.

## 8. Acceptance của phần infra

- Không còn active dependency tới legacy infra/scripts/tests/workflows hoặc archive; root/local/CI commands cùng native owners.
- Mỗi environment load đúng một YAML và dotenv; không print/commit resolved secrets. App HTTP listeners không quay lại vì health/metrics.
- Local và CI chạy cùng Compose topology và E2E runner; signed S3 URLs chạy nguyên vẹn trong Docker network.
- Essential integration và API E2E chạy trên application/dependencies thật; paid external APIs được thay đúng tại boundary bằng WireMock. Browser project dùng frontend thật khi có và không bị loại khỏi thiết kế vì backend polyglot.
- Release deploy đúng tested image digests, giữ data volumes và có backup/restore path đã chạy thử trước production acceptance.
- Core build/test/release/startup không bắt buộc image, migrations, health hay ACK của Leta. Nếu release chọn kèm Leta thì cũng test/pin đúng images đó; không biến lựa chọn đóng gói thành application dependency.
- Archive hash/mode/size, source bảo toàn và document links được kiểm; runtime/provider/remote CI/deploy chưa chạy phải ghi rõ.

## Nguồn native đã đối chiếu

- [Docker Compose merge/override](https://docs.docker.com/compose/how-tos/multiple-compose-files/merge/).
- [BuildKit cache trong GitHub Actions](https://docs.docker.com/build/ci/github-actions/cache/).
- [GitHub workflow syntax, path filters và concurrency](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax).
- [RustFS container](https://docs.rustfs.com/en/installation/container), [release 1.0.5](https://github.com/rustfs/rustfs/releases/tag/1.0.5).
- [WireMock Docker image](https://wiremock.org/docs/standalone/docker/).

Pinned image/provider/SDK combination đã qua native smoke và local API E2E; versions/digests thực thi nằm ở manifests/lockfiles. Nguồn không thay thế verification trên GitHub/VPS hoặc production provider thật.
