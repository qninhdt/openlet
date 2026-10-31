# Openlet — Monorepo, Testing & Infrastructure Architecture

**Trạng thái:** Baseline thiết kế đã thống nhất  
**Ngày:** 31/10/2026  
**Phạm vi:** Cấu trúc monorepo, tên applications, unit/integration/E2E testing, Temporal testing, test environments, infrastructure, scripts, Makefile và nguyên tắc CI/CD.

> Tài liệu này tổng hợp những quyết định của cuộc thảo luận. Đây là **thiết kế mục tiêu từ đầu**, không phải bản mô tả hoặc yêu cầu bảo toàn hệ thống testing/infra/scripts trong ZIP hiện tại. Giữ production logic bên trong từng application; được phép thay thế cách tổ chức testing, orchestration và infrastructure. Những chi tiết chưa được chốt được nêu rõ ở cuối tài liệu.

---

## 1. Các quyết định kiến trúc đã chốt

| Hạng mục | Quyết định |
|---|---|
| Repository | **Một polyglot monorepo**, có backend và frontend trong tương lai |
| Điều phối monorepo | **Turborepo** (chọn dùng; Go/Rust/Python native integration cần kiểm chứng theo version, hiện còn experimental) |
| Frontend package manager | **pnpm** |
| Go | Go workspace; native `go test` |
| Rust | Cargo workspace; native `cargo test` |
| Python | uv workspace; **pytest** |
| Testing levels | **3 cấp:** Unit → Integration → System E2E |
| Integration dependencies | **Testcontainers**, sử dụng dependencies thật khi đang kiểm thử boundary tương ứng |
| System E2E | **TypeScript + Playwright Test** cho cả API và browser |
| System E2E environment | **Docker Compose**, chạy full stack và cô lập với môi trường development |
| Workflow testing | Native Temporal SDK testing, activity tests, server integration khi cần, **workflow history replay** |
| Cross-cutting testing | Recovery, security, contract, parser regression, performance… là **mục tiêu/suite/technique**, không phải level thứ tư |
| CI/CD | GitHub Actions điều phối pipeline; Turborepo điều phối các application tasks |
| Developer CLI | Root **Makefile mỏng**, không tự triển khai task engine |
| Scripts | Ít nhất có thể; không tạo thêm wrapper cho các chức năng Turbo/Compose/Playwright đã cung cấp |
| Deployable directories | `apps/web`, `apps/account`, `apps/workspace`, `apps/letfs`, `apps/letfs-processing` |
| Root boundaries | `apps/`, `e2e/`, `infra/`, `scripts/`, `contracts/`, `docs/`, `.github/` |

**Nguyên tắc trọng tâm:** Quy tắc testing và build thuộc mỗi application; việc kiểm chứng hành vi toàn hệ thống thuộc E2E; môi trường chạy thuộc infrastructure; Turborepo **điều phối** chứ không thay native frameworks.

---

## 2. Tên applications và ranh giới trách nhiệm

| Application | Công nghệ | Trách nhiệm định hướng |
|---|---|---|
| `web` | TypeScript | Giao diện người dùng của Openlet; bổ sung khi triển khai frontend |
| `account` | Go | User/account lifecycle, onboarding, liên kết danh tính bên ngoài; là tên rộng hơn `identity` để không bó hẹp hướng phát triển account/plan/billing |
| `workspace` | Go | Workspace, membership, collaboration, access control ở phạm vi workspace |
| `letfs` | Rust | File system/storage domain, metadata, APIs và phần orchestration thuộc Letfs |
| `letfs-processing` | Python | Xử lý nội dung: conversion, parsing, OCR, enrichment, indexing; chạy dưới dạng Temporal Activity worker |

### Vì sao chọn `account` thay `identity` hoặc `user`?

`identity` gợi trách nhiệm hẹp về định danh/xác thực. Nếu sau này cùng deployable quản lý account lifecycle, subscription hay plans thì `account` là tên linh hoạt hơn. **Chưa quyết định** subscription và billing sẽ thuộc account, workspace/organization hay một `billing` service riêng; không tạo thêm service chỉ để dự đoán tương lai. Nếu business boundary thay đổi thì xét lại service ownership theo domain, không dựa riêng vào tên folder.

### Vì sao chọn `letfs-processing` thay `processor` hoặc `letfs-worker`?

`processing` mô tả trách nhiệm nghiệp vụ, còn `worker` chỉ là cơ chế vận hành của Temporal. Tách Python ra khỏi Rust vì đây là **deployable riêng** có runtime, dependencies, build/test, scaling và deployment lifecycle riêng. Nó vẫn thuộc domain xử lý nội dung của Letfs; **không** bắt buộc tạo microservice mới chỉ vì tách folder.

**Không đổi tên application theo những tên thư viện/framework** như `temporal-worker`, `axum-service`, `go-api`.

---

## 3. Folder structure mục tiêu

Cây dưới đây **chỉ thể hiện thư mục**, không liệt kê production source files. Những thư mục tùy chọn chỉ cần tạo khi có nội dung thật; đặc biệt `web/` và cloud IaC có thể chưa tồn tại ngay.

```text
openlet/
├── apps/
│   ├── web/
│   │   ├── src/
│   │   └── public/
│   │
│   ├── account/
│   │   ├── cmd/
│   │   │   └── server/
│   │   ├── internal/
│   │   └── migrations/
│   │
│   ├── workspace/
│   │   ├── cmd/
│   │   │   └── server/
│   │   ├── internal/
│   │   └── migrations/
│   │
│   ├── letfs/
│   │   ├── src/
│   │   ├── tests/
│   │   └── migrations/
│   │
│   └── letfs-processing/
│       ├── src/
│       │   └── openlet_processor/
│       └── tests/
│           ├── unit/
│           ├── integration/
│           └── fixtures/
│
├── e2e/
│   ├── tests/
│   │   ├── api/
│   │   │   ├── account/
│   │   │   ├── workspace/
│   │   │   ├── filesystem/
│   │   │   ├── processing/
│   │   │   └── search/
│   │   └── browser/
│   │       ├── authentication/
│   │       ├── onboarding/
│   │       ├── workspaces/
│   │       ├── files/
│   │       └── search/
│   ├── fixtures/
│   │   ├── auth/
│   │   └── data/
│   ├── setup/
│   ├── pages/
│   └── helpers/
│
├── infra/
│   ├── compose/
│   ├── config/
│   │   ├── envoy/
│   │   ├── postgres/
│   │   ├── temporal/
│   │   ├── object-storage/
│   │   └── qdrant/
│   ├── bootstrap/
│   │   ├── postgres/
│   │   ├── temporal/
│   │   └── object-storage/
│   └── terraform/                 # Chỉ khi chọn cloud/IaC cụ thể
│       ├── environments/
│       │   ├── staging/
│       │   └── production/
│       └── modules/
│
├── scripts/
│   ├── bootstrap/
│   └── operations/
│
├── contracts/
│   ├── public/
│   └── internal/
│
├── docs/
│   ├── architecture/
│   ├── decisions/
│   ├── development/
│   ├── testing/
│   └── operations/
│
└── .github/
    └── workflows/
```

### Root configuration (không đưa vào cây thư mục)

- **Turborepo:** root task configuration; pin version và kiểm chứng native workspace integrations.
- **TypeScript:** pnpm workspace; E2E là một workspace package độc lập; `web` sẽ là một workspace package khi có frontend.
- **Go:** root `go.work`, các Go applications giữ module riêng.
- **Rust:** root Cargo workspace trỏ tới Rust applications, sử dụng workspace lockfile.
- **Python:** root uv workspace trỏ tới Python applications, sử dụng workspace lockfile; cần sửa Docker build theo layout workspace.
- **Makefile:** entry points ngắn cho developer.
- **GitHub Actions:** pipeline orchestration, không định nghĩa lại nội dung native test runners.

> Lưu ý về Go/Rust: Dùng native layout của từng ngôn ngữ. Không ép Go tạo `tests/unit/` nếu test nên nằm cạnh source, và không ép Rust unit tests ra khỏi module chỉ để đồng nhất với Python.

---

## 4. Taxonomy testing: chính xác 3 levels

### Level 1 — Unit

- Kiểm chứng units of behavior: logic, validation, policy, transformations, error branches.
- **Không cần database hay external infrastructure thật**; fake/stub/mock khi ranh giới cần cô lập.
- Test nhỏ, deterministic, chạy nhanh, không phụ thuộc shared state.
- Dùng native framework theo ngôn ngữ.

### Level 2 — Integration

- Kiểm chứng các thành phần kết hợp và các boundaries thật (SQL/transactions, object storage, Qdrant, network adapters, Temporal server khi thích hợp).
- **Testcontainers** quản lý lifecycle của containerized dependencies; ưu tiên cùng engine/semantics với production khi có thể.
- Một integration test chỉ nên dựng các dependencies nó cần; **không** khởi động toàn bộ microservices mặc định.
- Isolation bằng independent data/schema/db/container hoặc cleanup phù hợp; kiểm tra readiness; không phụ thuộc thứ tự test.

### Level 3 — System E2E

- Kiểm chứng business journeys thông qua **public interface của toàn hệ thống**.
- Dùng **TypeScript + Playwright Test**; Docker Compose khởi động hệ thống được kiểm thử.
- Hai **nhóm theo điểm truy cập**: `API E2E` và `Browser E2E`; đây **không** phải hai testing levels mới hay taxonomy toàn ngành chỉ có đúng hai loại E2E.
- Ưu tiên critical journeys; không nhân đôi tất cả validation cases của unit/integration tests.

**Phân loại theo scope, không theo tool:** Một HTTP test dùng Playwright với service mock không tự trở thành E2E; một browser test stub toàn bộ backend không chứng minh full-stack integration.

---

## 5. Unit & Integration theo từng ngôn ngữ

### 5.1 Go (`account`, `workspace`)

- Dùng built-in **`testing`**, `*_test.go` colocated với package, `t.Run` và **table-driven tests** khi phù hợp.
- `t.Cleanup`, `t.TempDir`, `httptest`, `go test -race` dùng theo mục đích thực tế.
- Test public behavior; assertions rõ ràng; mock ở abstraction boundary khi cần, tránh mock mọi implementation detail.
- Integration tests gần package mà chúng kiểm chứng; dùng Testcontainers cho PostgreSQL và dependencies thích hợp.
- Phân biệt unit/integration bằng conventions và test selection đã định; không coi `go test ./...` mặc nhiên là *unit-only* nếu project có integration tests không được tách.
- Không tạo root Go module chỉ để phục vụ E2E; không đưa Go test harness vào `e2e/`.

### 5.2 Rust (`letfs`)

- Dùng **`cargo test`**.
- Unit tests trong các `src/` modules với **`#[cfg(test)]`**; có thể truy cập private items phù hợp mục đích unit.
- Rust integration test targets ở **crate `tests/`** kiểm chứng public crate interface; có thể dùng Testcontainers để dựng PostgreSQL/S3-compatible/Qdrant dependencies khi cần.
- Async tests dùng runtime/test facilities của Tokio theo workload.
- Cần chọn test targets/ignored tests rõ ràng khi định nghĩa Turbo tasks. Không coi mọi test trong `tests/` là external-infrastructure test: theo Cargo, đó là khái niệm integration target ở mức crate.

### 5.3 Python (`letfs-processing`)

- Dùng **pytest** với `src/` package layout, `tests/unit/`, `tests/integration/`.
- Dùng **pytest fixtures**, `pytest.mark.parametrize`, marker selection và pytest-asyncio khi có async functions.
- `yield` fixtures/context managers cho cleanup; scope đủ rộng để tối ưu startup nhưng state của mỗi test phải cô lập.
- Integration tests dùng parser/library thật, database/S3/other dependencies thật theo mục tiêu; Testcontainers khi cần containerized services.
- Mock/monkeypatch có chủ đích để tạo lỗi hoặc cô lập external calls, không giả lập parser thật trong các regression tests.

### 5.4 Frontend (`web`, khi xuất hiện)

- Frontend tự sở hữu unit/component tests của mình bằng tooling phù hợp framework được chọn sau này.
- Browser **system E2E** đặt tại root `e2e/`, không nằm trong unit tests của FE.
- FE UI tests dùng mocked API **không** thay thế browser E2E với backend thật.

### Best practices xuyên ngôn ngữ

- Tests tự tạo preconditions, không phụ thuộc thứ tự, tránh global mutable state.
- Dùng real dependencies ở integration boundary cần kiểm chứng; không biến toàn bộ integration suite thành full-stack suite.
- Tránh fixed sleeps; dùng readiness, conditions/polling với timeout.
- Test cả success/error/transaction/concurrency paths ở đúng level.
- Không tối ưu bằng mọi giá cho 100% line coverage; ưu tiên behavior và rủi ro.

---

## 6. System E2E — TypeScript + Playwright

### 6.1 API E2E (`e2e/tests/api/`)

- Không mở browser; Playwright `request`/`APIRequestContext` gọi **public HTTP API** qua gateway.
- Dùng backend/worker/infrastructure thật trong Compose, với controlled test data.
- Kiểm tra business outcomes xuyên services, ví dụ account/workspace onboarding, file lifecycle, upload → processing → indexing → search, và các flow hệ thống quan trọng khác.
- Với Temporal/async processing: poll observable status/result đến khi đạt điều kiện hoặc timeout; không dùng hard-coded sleep.
- **Không** chuyển mọi endpoint-level validation test sang API E2E.

### 6.2 Browser E2E (`e2e/tests/browser/`)

- Browser thật chạy FE thật với backend thật.
- Kiểm chứng critical user journeys: authentication/onboarding, workspace collaboration, upload/processing UX, search và file interactions.
- Ưu tiên Playwright locators theo accessibility, auto-waiting assertions, traces/screenshots khi failed.
- Không nhân đôi toàn bộ nghiệp vụ đã được API E2E bảo vệ; chỉ kiểm tra các rủi ro UI ↔ backend cần thiết.

### 6.3 Tổ chức Playwright

- **Một Playwright workspace package** cho sản phẩm Openlet.
- **Hai Playwright projects/suites** logic: `api` và `browser`, chọn chạy độc lập hoặc cùng nhau.
- Tests nhóm theo **domain/user journey**, không theo tên source files của các backend services.
- `fixtures/` quản lý test identities/data/cleanup; `setup/` phục vụ setup projects; `pages/` và `helpers/` chỉ tạo khi có reuse thực sự.
- Không để Go/Rust/Python test harness lẫn vào project Playwright.

### 6.4 Các kiểu E2E khác

- Không tạo thêm `workflow-e2e/` chỉ vì hệ thống dùng Temporal: workflow đi xuyên services đã có thể được kiểm chứng qua API E2E.
- Nếu sau này có **mobile, CLI hoặc event-only public entry points**, có thể thêm suite tương ứng; hiện tại không cần.
- **Recovery/system failure scenarios** có thể là E2E special-purpose tests, nhưng không phải testing level mới.

---

## 7. Temporal testing là một phần chính thức của testing architecture

Temporal testing **không phải level thứ tư**, mà đi qua các level hiện có:

| Hình thức | Scope phù hợp | Thực thi/ownership |
|---|---|---|
| Workflow logic tests | Unit | SDK test environment của ngôn ngữ tương ứng, mock Activities khi cần; nằm tại app sở hữu workflow |
| Activity unit tests | Unit | Native runner, fake external dependencies khi cần |
| Activity integration tests | Integration | Native runner + real dependency/Testcontainers |
| Temporal server integration | Integration | Dùng Temporal test/dev server hoặc container khi cần xác minh worker polling, registration, task queue và server interactions |
| Workflow history replay | Determinism/compatibility regression | Replay trên **history fixtures có quản lý**, thuộc app sở hữu workflow; runner/SDK phải hỗ trợ replay tương ứng |
| Cross-service workflow execution | System E2E | Playwright API E2E + Temporal/real workers trong Compose |
| Worker crash/restart & recovery | System reliability/recovery | Dedicated system-level scenario chạy với Temporal thật; chỉ dùng các điều khiển restart/kill khi cần |

**Nguyên tắc:**

1. Không dùng Temporal server thật cho mọi workflow logic unit test.
2. Không mock Temporal trong những integration tests mà mục đích là kiểm tra registration, task queue hoặc persistence của Temporal server.
3. Workflow history replay phải có đầu vào xác định, được version-control hoặc quản trị như regression fixtures; không nên chỉ dựa vào history ngẫu nhiên được một E2E job trước tạo ra.
4. Temporal SDK/language support có thể khác nhau; không áp một test API hoặc replayer giống hệt cho Go, Rust và Python.
5. Crash/recovery scenarios không được ngụy trang thành chỉ kiểm tra mock retry; mục tiêu là trạng thái bền vững và business outcome thực sự.

---

## 8. Test environments: ownership và isolation

| Môi trường | Ai quản lý | Tính chất |
|---|---|---|
| Unit | Native test process / Temporal SDK test env | In-process, không cần system services |
| Integration | Test runner + Testcontainers | Chỉ các dependency cần thiết; isolated data và cleanup |
| Temporal server integration | Native tests + test server/container | Có worker/server thực khi test boundary này |
| API E2E | `infra/compose` + Playwright | Full backend + Temporal + storage/search infra; isolated environment |
| Browser E2E | `infra/compose` + Playwright | FE + full backend; isolated environment |

### Các quy tắc đã thống nhất về môi trường

- **Local development** và **E2E** dùng cùng nguồn config nền nếu phù hợp nhưng **khác state/credentials/namespaces/databases** khi cần isolation.
- Test runs phải có readiness/health checks. Container `running` không đồng nghĩa `ready`.
- Mỗi test có data preconditions/cleanup rõ ràng; không phụ thuộc thứ tự hoặc dữ liệu developer còn sót.
- Với async consistency (Temporal, indexing), chờ điều kiện observable với timeout.
- External providers (ví dụ Clerk, model/API provider) có thể được stub/test-mode ở system E2E khi không kiểm soát được; provider-specific smoke/contract checks là suite riêng nếu cần.
- E2E diagnostics nên thu thập service logs, failure artifacts, Playwright traces/screenshots và correlation IDs nếu có.

### Chưa chốt chi tiết implementation

- Cơ chế khởi tạo và reset E2E DB/storage/Temporal data cụ thể.
- Cách cấp test identities/tokens cho Clerk và chính sách dùng sandbox/provider thực.
- Parallel E2E workers dùng isolated environment per worker hay per job.
- Chính sách seed/migration và test fixtures chi tiết.

Những vấn đề này thuộc **environment implementation**, không làm thay đổi folder structure hay testing taxonomy đã chọn.

---

## 9. Infrastructure structure và ranh giới

### `infra/compose/`

- Quản lý các Compose configurations cho **local development** và **isolated E2E**.
- Compose chịu trách nhiệm khởi động service containers và infrastructure dependencies; Playwright không thay Compose.
- Tách rõ provisioning startup, readiness, teardown; tránh custom scripts chỉ để gọi lại các Compose commands có sẵn.

### `infra/config/`

- Configuration cho Envoy, PostgreSQL, Temporal, object storage và Qdrant.
- Không bỏ application migrations vào đây; migration files của ứng dụng ở `apps/<app>/migrations/`.

### `infra/bootstrap/`

- Khởi tạo infrastructure resources như databases/users, Temporal namespace hoặc object-storage buckets khi thực sự cần.
- Khác với developer machine setup nằm trong `scripts/bootstrap/`.

### Cloud/deployment IaC

- Chỉ bổ sung Terraform/cloud IaC chi tiết **sau khi chọn platform triển khai**.
- Không thêm đồng thời Kubernetes, Helm, Kustomize, Argo CD, Terraform… chỉ để tạo đủ thư mục.
- Mỗi app sở hữu Docker build context/Dockerfile của mình; `infra/` sở hữu cách kết nối/triển khai tổng thể.

---

## 10. Turborepo, native workspaces và caching

Turborepo làm **task orchestration**, không thay thế `go test`, `cargo test`, `pytest`, Playwright hoặc Docker Compose.

### Các nhóm tasks logic

- `lint` / `format` / `check`
- `build`
- `test:unit`
- `test:integration`
- `test:workflow` (nếu cần lệnh tách riêng)
- `test:replay` (nếu cần lệnh tách riêng)
- `test:parser` (parser regression chuyên biệt, nếu tách)
- `e2e:api`
- `e2e:browser`
- `e2e` (tổng hợp)

Tên task chính xác/configuration cần kiểm tra với Turborepo version và native workspace integration thực tế. **Không** được xem `turbo run test` là unit-only nếu native default command trộn các scopes.

### Caching

- Có thể cache deterministic build/lint/unit tasks khi inputs được định nghĩa đầy đủ.
- **Không cache mặc định** Integration/E2E/recovery tests phụ thuộc external mutable state; chỉ bật nếu có bảo đảm về inputs và môi trường.
- Pin Turborepo version vì polyglot native integration đang experimental; native commands vẫn phải chạy độc lập ngoài Turbo để dễ debug.

---

## 11. Scripts, Makefile và CI/CD

### Ownership rõ ràng

| Công cụ | Trách nhiệm |
|---|---|
| Go/Cargo/pytest | Native unit/integration/Temporal-related tests của app |
| Testcontainers | Containerized dependencies cho integration |
| Playwright | API/browser system E2E, assertions và test artifacts |
| Docker Compose | Local/E2E infrastructure và service lifecycle |
| Turborepo | Chạy/điều phối tasks trong monorepo, task graph, caching |
| GitHub Actions | CI jobs, conditions, matrices, quality/release gates |
| Makefile | Developer-facing shorthand commands |
| `scripts/` | Chỉ automation đặc thù không có sẵn trong tools trên |

### `scripts/`

- `bootstrap/`: developer environment initialization đặc thù, nếu không thể diễn đạt đủ bằng package managers/Compose.
- `operations/`: backup, restore, disaster recovery/operational procedures thực sự cần code riêng.
- **Không tạo** test wrapper shell scripts, build wrapper scripts hoặc custom orchestration chỉ để gọi các công cụ đã có.

### Makefile

Makefile là **thin façade**, ví dụ có nhóm targets cho setup/up/down/logs, build/check, unit/integration, API/browser E2E, migration/backup/restore. Nó không duy trì dependency graph/caching/retry engine riêng song song với Turbo/Compose.

### CI/CD (nguyên tắc, chưa khóa lịch và jobs cuối cùng)

- PR: quality checks và native unit; integration tests theo phạm vi cần thiết; E2E critical flows phù hợp thay đổi.
- E2E jobs: dựng isolated Compose environment rồi chạy Playwright API/browser projects.
- Nightly/pre-release: có thể chạy suites rộng hơn, parser regression, replay, recovery, multi-browser theo chi phí/rủi ro.
- Sau deploy: smoke checks những chức năng trọng yếu khi cần.
- Không mặc định mỗi microservice release phải chờ **toàn bộ** browser E2E nếu điều đó phá tính độc lập của deployment; dùng integration/contract checks ở ranh giới thay đổi.

---

## 12. Những gì **không** đưa vào kiến trúc mới

- Không giữ Go-based root E2E test harness làm kiến trúc chuẩn; system E2E sử dụng **Playwright/TypeScript**.
- Không tạo root shared `tests/testinfra` Go module chỉ để điều khiển Testcontainers cho mọi service.
- Không đặt unit/integration của mọi ngôn ngữ ở root `tests/`.
- Không xây framework test orchestration riêng bên cạnh Turborepo.
- Không gom tất cả migrations vào `infra/postgres`.
- Không tách `letfs-processing` thành nhiều microservices theo từng bước parsing/OCR/indexing chỉ vì chúng là Activities khác nhau.
- Không tạo `common/`, `shared/`, `packages/` hoặc nhiều Rust crates khi chưa có nhu cầu chia sẻ thật.
- Không xây sẵn Kubernetes/GitOps/cloud provider folders khi platform chưa chọn.
- Không tạo thêm level testing cho Temporal, contract, recovery, security hay performance.
- Không sao chép toàn bộ API E2E scenarios thành browser E2E scenarios.

---

## 13. Phạm vi chuyển đổi khi triển khai lại

Theo quyết định thiết kế lại từ đầu:

1. **Giữ production business logic** của các applications; được phép đổi thư mục và build paths theo ranh giới mới.
2. **Thiết kế lại toàn bộ** testing, E2E harness, infra, scripts, Makefile và CI organization — không giữ code cũ làm khuôn mẫu.
3. Chuyển/rewrite **critical scenarios** có giá trị từ test coverage cũ sang native unit/integration, Temporal suites hoặc Playwright E2E phù hợp; không đánh mất các bảo đảm quan trọng như persistence/recovery/replay chỉ vì bỏ harness cũ.
4. Chuyển Python app thành `apps/letfs-processing` với lifecycle build/deploy riêng; giữ các contract/task queue tương thích theo yêu cầu production.
5. Validation bắt buộc khi thay workspace: Go modules, Cargo workspace/lockfile, uv workspace/lockfile, Docker builds, runtime service connectivity, migration paths và task discovery của Turborepo.

**Điều cấm trong migration:** không rewrite business logic hoặc introduce architecture abstraction mới chỉ để làm đẹp cấu trúc thư mục.

---

## 14. Các quyết định cố ý chưa chốt

Đây là các hạng mục cần lựa chọn trong giai đoạn triển khai chi tiết, **không được xem như đã có quyết định cuối cùng**:

1. **Billing ownership:** account vs workspace/organization vs deployable `billing` riêng.
2. **Production deployment platform:** VPS, managed containers, Kubernetes/cloud; Terraform modules/provider thực tế.
3. **Identity test strategy:** Clerk test-mode, sandbox tokens, API stubs và smoke/provider tests.
4. **E2E environment isolation mechanism:** per run/job/worker, reset policies, seeding và cleanup chi tiết.
5. **CI gate matrix:** thời điểm chạy toàn bộ integration, replay, parser regression, recovery, contract, performance, security và browser combinations.
6. **Specialized tooling:** có cần dedicated Pact/contract framework, security/performance tools hoặc provider testing hay chỉ dùng native implementations.
7. **Frontend framework và FE unit/component tooling:** chỉ chốt TypeScript frontend workspace và Playwright cho full-stack browser E2E, chưa chọn UI framework.

---

## 15. Tài liệu chuẩn tham khảo

- [Go — Organizing a Go Module](https://go.dev/doc/modules/layout)
- [Go — Test Comments](https://go.dev/wiki/TestComments)
- [Rust Book — Test Organization](https://doc.rust-lang.org/book/ch11-03-test-organization.html)
- [Cargo — Workspaces](https://doc.rust-lang.org/cargo/reference/workspaces.html)
- [pytest — Good Integration Practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html)
- [pytest — Fixtures](https://docs.pytest.org/en/stable/how-to/fixtures.html)
- [Testcontainers for Go](https://golang.testcontainers.org/)
- [Testcontainers for Rust](https://rust.testcontainers.org/)
- [Testcontainers for Python](https://testcontainers-python.readthedocs.io/)
- [Playwright — API Testing](https://playwright.dev/docs/api-testing)
- [Playwright — Projects](https://playwright.dev/docs/test-projects)
- [Playwright — Fixtures](https://playwright.dev/docs/test-fixtures)
- [Turborepo — Repository Structure](https://turborepo.dev/docs/crafting-your-repository/structuring-a-repository)
- [Turborepo — Playwright](https://turborepo.dev/docs/guides/tools/playwright)
- [Turborepo 2.11](https://turborepo.dev/blog/2-11)
- [Docker Compose — Multiple Compose Files](https://docs.docker.com/compose/how-tos/multiple-compose-files/)
- [The Practical Test Pyramid](https://martinfowler.com/articles/practical-test-pyramid.html)
- [Microservice Testing Strategies](https://martinfowler.com/articles/microservice-testing/)
- [ISTQB CTFL v4.0.1](https://istqb.org/wp-content/uploads/2024/11/ISTQB_CTFL_Syllabus_v4.0.1.pdf)

---

## 16. Tóm tắt chốt

**Repository:** `apps/ + e2e/ + infra/ + scripts/ + contracts/ + docs/ + .github/`  
**Applications:** `web`, `account`, `workspace`, `letfs`, `letfs-processing`  
**Test pyramid:** Unit → Integration → System E2E  
**Unit/Integration:** Native Go/Rust/Python + Testcontainers  
**Temporal:** workflow/unit, activity integration, server integration khi cần, history replay, E2E/recovery scenarios  
**System E2E:** Playwright TypeScript với API và browser projects, không trộn Go harness  
**Environments:** Docker Compose cho local/full-stack E2E, cô lập state, Testcontainers ở service integration  
**Orchestration:** Turborepo; Makefile mỏng; GitHub Actions CI; scripts tối thiểu  
**Chính sách thiết kế:** Tối giản, dựa vào convention native và ranh giới deployable, không xây lại chức năng có sẵn trong tooling.
