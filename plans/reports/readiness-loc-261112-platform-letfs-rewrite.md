# Rà soát trước khi đưa core rewrite lên dev

Ngày 2026-11-12. Thuộc [plan hiện tại](../261111-1727-platform-letfs-rewrite/plan.md). Phạm vi: Platform, LetFS, ingest CPU/IO, contracts/SDKs, cấu hình, infra, scripts và CI/E2E đang active. Không implementation Leta; archived code chỉ dùng đối chiếu hành vi và đo baseline.

## Kết luận

Đủ điều kiện đưa bản core MVP lên `dev` theo bằng chứng local hiện có; không còn blocker được phát hiện trong phạm vi đã chốt. Chưa stage, commit, push, chạy GitHub Actions hoặc deploy. Đây không phải xác nhận production readiness. [Đối chiếu chức năng](feature-parity-261112-platform-letfs-rewrite.md) đã đóng: chỉ thêm hybrid search; bốn phần cắt còn lại do người dùng chấp nhận.

Rà soát owning implementation, contracts/migrations, call boundaries, quyền, SQL/query shape, workflow/activity retries, bootstrap và recovery/deploy paths. Lists dùng graph/SQL bulk; recursive tree operations dùng CTE; không thấy per-item RPC/SQL N+1 trong các đường đã kiểm. Chưa có EXPLAIN/load benchmark nên không suy ra latency hay throughput từ số dòng code.

## Các sửa đổi sau review

- [Hybrid search](../../apps/letfs/internal/storage/search.go): native Qdrant BM25 + dense prefetch, RRF, giữ SQL current-version/live ancestry và rerank. [Bootstrap](../../scripts/bootstrap.py) tạo text index có BM25 scoring cho cả collection mới hoặc đã có. Không đổi wire contract/dependency.
- [CreateUpload](../../apps/letfs/internal/storage/uploads.go) đọc completed receipt sau authorization/validation và trước mutable target lookup/S3 side effects. Dùng cùng [receipt decoding/hash check](../../packages/sdk-go/receipt.go) với Claim; Claim trong SQL transaction vẫn quyết định admission. Retry tuần tự không tạo multipart mới rồi mới phát hiện duplicate. Không hứa exactly-once S3 khi hai request chạy đồng thời; native provider lifecycle xử lý multipart bỏ dở theo giới hạn đã chốt.
- [Invitation acceptance](../../apps/platform/internal/platform/invitations.go) dùng chung bounded member admission với [AddMember](../../apps/platform/internal/platform/members.go), từ chối quá giới hạn trước khi consume token. E2E chứng minh token còn dùng được sau khi một thành viên rời workspace. Không thêm member counter, broad lock hoặc fully-consistent check; giới hạn vẫn chịu consistency/concurrent-admission window của graph.
- [Collaboration E2E](../../e2e/tests/api/collaboration.spec.ts) kiểm HTTP 400 cho gRPC FailedPrecondition theo native Envoy mapping, và poll bounded cho kết quả thu hồi quyền async đã chốt. Không đổi permission semantics để cứu test.
- [CI](../../.github/workflows/ci.yaml) chạy push trên `main` và `dev`, cùng PR trigger; giữ owner filters/docs-only skip. Release vẫn yêu cầu successful default-branch CI.

## Verification

| Kiểm chứng | Kết quả |
|---|---|
| `make check test` | Pass: gofmt/vet/tests, Ruff, Buf lint, TypeScript, shell syntax; 15 ingest tests |
| ShellCheck 0.11.0 và actionlint 1.7.12 | Pass |
| `make generate` rồi so SHA-256 24 generated files | Không drift |
| `TestStorageSQLInvariants` với integration tag | Pass trên PostgreSQL riêng, backup trước migration; gồm receipt replay/mismatch/missing, quota, tree và source-version publication |
| `scripts/e2e.sh api` | **4/4 pass, 32.7 giây phần Playwright** trên fresh Compose |
| Hybrid proof trong journey XLSX | Keyword evidence có dense score thấp hơn README vẫn đứng đầu sau BM25/RRF; Qdrant và hai worker thật |
| PostgreSQL backup/restore drill đã thực hiện | Sáu databases/dumps, checksums/data đối chiếu, nonempty-target refusal và restored SpiceDB authorization pass |
| Candidate-file audit + Gitleaks | 442 text files; không phát hiện secret trong scan từng file, không đọc dotenv thật/ignored generated secrets |
| `git diff --check` | Pass |

E2E dùng WireMock cho Clerk/JWKS/model HTTP boundaries; PostgreSQL, SpiceDB, Temporal, RustFS và Qdrant thật. Không paid-provider suite mới. LangSmith dependency phát 13 deprecation warnings liên quan Python 3.16; Python 3.14 tests vẫn pass.

Evidence local, ignored: `.local/final-checks.log`, `.local/review-generate.log`, `.local/review-sql-invariants.log`, `.local/e2e-review-final.log`, `.local/e2e/results/`, `.local/drill/`, `.local/gitleaks-review.json`. SQL/E2E containers, networks/volumes thuộc lượt kiểm đã dọn. Không đụng DB cũ hoặc real dotenv.

## LoC trước/sau, ngoại trừ Leta

Đo bằng **cloc 2.06**, code lines, loại blank/comment. Before là snapshot thực tế dưới `archive/2026-11-11/`, không lấy con số ước lượng hoặc chỉ đếm phần diff. After là active tree sau hybrid và review fixes. Service table đếm Go/Python/SQL migrations; không đếm dependencies, models, binaries, generated bindings, config/docs hoặc test vào production. File tests/fixtures được tách riêng. Empty files không đóng góp LoC.

| Service/worker | Production trước | Production sau | Giảm | Tests trước | Tests sau |
|---|---:|---:|---:|---:|---:|
| Account + Workspace → Platform | 4,154 | 1,055 | 74.6% | 2,897 | 0 |
| LetFS | 10,841 | 3,156 | 70.9% | 8,375 | 238 |
| Ingest CPU + IO | 1,952 | 882 | 54.8% | 1,567 | 270 |
| **Tổng services/workers** | **16,947** | **5,093** | **69.9%** | **12,839** | **508** |

CPU và IO chia sẻ cùng app, nên đếm shared implementation đúng một lần. Platform không có service-local unit suite; hành vi identity/membership/invitation/lifecycle được kiểm trong gateway/collaboration E2E. Bảng test trên không bao gồm E2E hoặc SDK tests.

Để không che việc chuyển code sang packages, đo shared runtime packages riêng, loại đường dẫn Leta và tách generated code:

| Shared packages | Trước | Sau |
|---|---:|---:|
| Handwritten production Go/Python | 6,309 | 484 |
| Handwritten tests/fixtures | 4,190 | 32 |
| Generated Go/Python bindings/stubs | 20,780 | 15,796 |

Tính cả handwritten shared packages, production giảm **23,256 → 5,577 LoC, 76.0%**. Generated bindings nằm ở packages, không nằm trong service production totals; không cộng generated LoC vào mức giảm handwritten code. Không đưa Leta, proto/Zed definitions, scripts/infra hoặc E2E vào service table. Đây là so sánh maintenance surface sau các thay đổi/cắt tính năng đã duyệt, không chứng minh 100% parity, performance hay chất lượng chỉ bằng LoC.

Các manifests và raw cloc JSON nằm ở `.local/loc-comparison/`; mỗi nhóm dùng `cloc --quiet --skip-uniqueness --list-file=<manifest> --json`. Category tests: `_test.go`, `test_*.py`, conftest và test/fixture directories; generated: gen/openlet_api/buf-validate và protobuf outputs. Không đếm vendored/runtime dependencies hoặc caches.

## Giới hạn khi push và triển khai

- `archive/` và dirty-tree snapshots là **local ignored**, không được push cùng rewrite. Caches/venvs/binaries đi cùng archive khoảng 2 GB, vì vậy không bỏ ignore toàn folder. Source đã commit trước đây còn trong Git history; dirty archived source cần giữ backup local nếu muốn khôi phục chính xác. Các link `archive/` trong feature audit chỉ hoạt động trên máy có snapshot.
- Chưa chạy GitHub CI/release hoặc VPS, production Clerk/model/S3, frontend/browser, load benchmark hay full S3/Qdrant disaster recovery. PostgreSQL drill không phải full-system recovery.
- Giữ accepted trade-offs: permission stale window/signed URL expiry, invitation consume→graph failure cần invitation mới, quota có thể từ chối upload lúc complete. Không thêm saga/locks/framework để đổi những quyết định này trong review.
- Không validate lại Zed theo yêu cầu; bootstrap áp dụng schema vào test datastore mới. Leta/Computer runtime và production cutover vẫn ngoài đợt core này.
