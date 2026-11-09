# Chi tiết thực hiện

Tài liệu này triển khai [roadmap](plan.md), chưa phải kết quả audit đầy đủ hoặc lệnh bắt đầu sửa code.

## 0. Thiết lập baseline

Đọc owning docs và kế hoạch hiện hành; chụp revision/working tree. Lập danh sách production files theo module, tách tests, fixtures, migrations, generated bindings và vendored output. Ghi nhận lỗi tồn tại trước khi sửa bằng focused reproduction; không coi lịch sử PASS là baseline của revision mới.

Chạy các gate sẵn có theo điều kiện môi trường. CI hiện dùng:

```sh
pnpm exec turbo run build check test test:workflow test:integration --concurrency=1
uv run --locked --package letfs-ingest ruff check scripts
uv run --locked --package letfs-ingest ruff format --check scripts
uv run --locked --package letfs-ingest pytest scripts -q
```

Integration cần Docker và dependencies thực. Có thể bắt đầu bằng focused unit checks rồi mới chạy graph; ghi chính xác phần chưa chạy. Dùng `OPENLET_HISTORY_DIR` khi cần thu history cho Go replay theo `docs/testing.md`.

Lập coverage ledger ngắn trong thư mục plan: module, revision, luồng đã trace, bằng chứng, kết luận sửa/giữ/cần đo, checks và PR tương ứng. Không cần thêm framework audit hoặc CI gate riêng.

Với mỗi optimization, xác định trước workload, metric và ngưỡng có ý nghĩa. Đo latency/SQL count/RPC count/bytes hoặc memory đúng boundary; dùng cùng fixture, concurrency và môi trường trước/sau. Không suy ra p95 API từ một SQL microbenchmark.

Nghiệm thu: biết trạng thái hiện tại, command chạy được và các invariant bắt buộc giữ. Không chỉnh database đang dùng; phép đo dùng môi trường disposable. Nếu phạm vi sau này cần sửa schema/data đang tồn tại, backup trước.

## 1. Bắt đầu từ persistence của Leta

Đọc `apps/leta/src/leta/store.py`, `domain.py`, `schedules.py`; trace callers trong `runtime/`, `temporal/`, `http/`, `transport/` và tests. Ưu tiên cụm schedules trước khi chạm receive/save_run/checkpoint.

Lát cắt đầu tiên:

1. Trace create/update/delete/occurrence từ tool/API qua Temporal tới SQL; ghi ai sở hữu validation, authorization và transaction.
2. Kiểm tra việc compile/validate schedule và chuyển đổi payload ở từng tầng. Chỉ gộp phần trùng cùng invariant; giữ validation tại trust boundary.
3. Nếu persistence schedules tách được thành một module cohesive, chuyển cả nhóm cùng callers; giữ quyền sở hữu transaction/locking rõ ràng. Nếu việc tách chỉ thêm forwarding, giữ nguyên và ưu tiên bỏ phần xử lý thừa đã chứng minh.
4. Sau lát cắt đầu tiên mới đánh giá tiếp HITL, history/API reads, runs/inbox và lifecycle. Không ép một module cho từng bảng SQL; không dựng BaseRepository, mixin hoặc facade để giữ mọi thứ trông giống cũ.

Giới hạn: schedule delete chủ ý hoạt động khi root/box đang deleting; create/update đòi hỏi admission khác. Không hợp nhất chúng thành một active-check chung. Giữ root/agent/box lock order, UUID, occurrence identity, replay và soft-delete semantics.

Kiểm chứng bằng `test_schedules.py`, `test_schedule_tools.py`, `test_schedules_integration.py`; thay đổi teardown chạy thêm lifecycle/workspace-cleanup tests. Mở rộng tới `test_store_integration.py`, HITL, inbox và recovery khi chạm các nhóm đó. Nghiệm thu là ranh giới rõ hơn hoặc ít xử lý thừa hơn với cùng kết quả/failure semantics; không chỉ file ngắn hơn.

## 2. Runtime và orchestration của Leta

Phạm vi: `runtime/`, `temporal/`, `filesystem/`, `http/`, `transport/`; đồng thời `history.py`, `streaming.py`, `schedules.py`, `models.py`, `domain.py`, `lifespan.py`, config, worker/server entrypoints và migrations liên quan để kiểm tra hợp đồng.

Trace một vòng inbox → model → tools → checkpoint → public history → Redis/SSE, rồi các nhánh pause/resume, human answer, schedule và deletion. So sánh trách nhiệm giữa middleware, runner, tool handlers và Temporal activities/bridges.

Tìm payload encode/decode lặp, truy vấn context/roster/mounts lặp, pass-through không giữ invariant và trạng thái có nhiều owner. Chỉ bỏ/gộp khi dependency và failure paths cho phép. Mount refresh và kiểm tra quyền hiện tại không được bỏ chỉ vì tốn RPC; đo trước khi đổi cách gọi.

Giữ LangGraph checkpoint làm owner của execution state, SQL làm owner dữ liệu nghiệp vụ và Temporal làm orchestration. Giữ sáu Workflow types đã chốt; không gộp engine hoặc bỏ Redis vì nhìn có vẻ nhiều tầng. Không đổi tên workflow/activity hoặc payload đang lưu chỉ để làm gọn.

Kiểm chứng runtime, compaction/history, saved tool results, duplicate delivery, worker crash sau commit, HITL, lifecycle, mount escape và cached-read revocation. Thay đổi workflow chạy native replay; thay đổi publication chạy streaming/SSE integration. Đo model/tool latency tách khỏi provider latency.

## 3. LetFS theo từng operation

Phạm vi chính: `internal/filesystem/`; đi kèm `internal/transport/http/`, `internal/transport/grpc/`, `internal/clients/`, `internal/temporal/`, config, server startup và migrations. Không tách mọi feature thành một package mới: các transaction dùng chung là boundary thật.

Thứ tự bên trong:

1. Reads: paths/nodes/tree/text reads/search; đối chiếu SQL/RPC count, pagination và batch hydration.
2. Writes: node writes/directories/text mutations/scope move; giữ revision, expected target identity và atomic quota publication.
3. Copy/trash/restore/purge/deletion: giữ partial-copy output, repeat-safe accounting, ancestor visibility và cleanup bounds.
4. Upload/publication/processing/artifacts/index cleanup/backfill: giữ generation fences, late-write reconciliation, immutable objects và read-only generated children.
5. Download/image/archive và storage/search/AI adapters: kiểm tra streaming memory, cancellation, deadlines và cleanup cả khi khởi tạo dở.

Rà `Service`/`Store` cùng hai transport adapters. Một method chuyển tiếp chưa đủ chứng minh abstraction thừa: `Service` hiện còn điều phối processing/deletion. Chỉ xóa wrapper khi invariant/side effect còn đúng cho tất cả callers. Không cho HTTP gọi gRPC server implementation để giảm số dòng.

Dùng `scripts/performance/sql-benchmark.py` cho workload phù hợp và per-query benchmark khi cần tìm SQL site cụ thể. Filename subtree scan, backfill và contention của filesystem lock là câu hỏi cần đo; chưa phải bottleneck đã chứng minh. Không bỏ locks hoặc thêm cache/index/tree representation mới nếu chưa có bằng chứng và acceptance riêng.

Kiểm chứng focused filesystem/transport tests, sau đó LetFS integration có race detector. Đổi durable paths chạy workflow/replay và recovery; đổi native text/search chạy Mirage cross-language gates. Nghiệm thu giữ exact bytes, scope boundaries, quota, idempotency, cancellation và bounded work, đồng thời có bằng chứng giảm xử lý hoặc giảm chi phí.

## 4. Workspace và Account

Workspace: `internal/workspace/`, hai transport adapters, `internal/temporal/`, config/startup/migrations. Rà service/store ownership, add/join/remove/invite, accessible scopes, personal-scope grant, Leta home và deletion callbacks. Chỉ tái sử dụng logic add/join sau khi đối chiếu các điều kiện invitation, email, owner và scope reuse; chúng không có cùng admission.

Giữ WorkspaceChanges serialization, SQL→SpiceDB reconciliation và cleanup callback không quay lại coordinator đang khóa. Giữ direct scope grants khi rebuild; không thay bằng quan hệ suy ra từ membership.

Account: `internal/account/`, `internal/clients/`, transport, Temporal, config/startup/migrations. Rà onboarding/profile và Clerk adapter; ưu tiên giữ nguyên nếu không có lợi ích cụ thể. Không đồng nhất trạng thái onboarding với metadata đã publish; response loss và retry là behavior cần bảo vệ.

Kiểm chứng role/owner transactions, invitation races, typed user/Leta identity, grant/revoke, deletion với pending human work và onboarding response loss. Thay đổi shared authentication cần gateway smoke. Nghiệm thu không xuất hiện cross-service SQL hoặc business logic mới trong transport.

## 5. LetFS ingest và parser

Phạm vi: `apps/letfs-ingest/src/letfs_ingest/processing/`, `parser/`, `temporal/`, `clients/`, config/worker/telemetry, tests và corpus.

Rà prepare → convert → upload → publish → enrich → index. Kiểm tra vòng lặp upload/transfer, materialization không cần thiết, retry classifications, timeout/cancellation và tài nguyên subprocess/tempfile/HTTP session. Giữ CPU/I/O worker roles và processing contract với Go.

Parser có compatibility logic thực cho Word/PowerPoint/OCR. Không xóa fallback vì trông dài hoặc ít caller; phải đối chiếu dependency đang pin và corpus. Chỉ đổi concurrency/batching khi đo được workload đại diện và vẫn giữ bounds.

Chạy package unit tests và `pnpm --filter @openlet/letfs-ingest test:parser` khi chạm parser. Chạy cross-language processing integration khi chạm RPC/upload/publication; giữ image paths, recovered text, typed diagnostics và log không chứa document text. Nghiệm thu output tương đương, bounded memory/resource cleanup và đo trước/sau nếu thay execution strategy.

## 6. Shared packages và contracts

Phạm vi: `packages/go/{clients,rpc,httpapi,identity,authz,apperr,config,telemetry,temporal,testfixture,cmd}`, handwritten `packages/python/src/openlet/`, package tests, `packages/contracts/` và `scripts/contracts/`.

Shared code bị ảnh hưởng phải sửa ngay trong các chặng trước. Chặng này rà phần còn lại và toàn bộ consumers, không tạo một shared rewrite độc lập.

Ưu tiên Python LetFS client: kiểm tra DTO/protobuf conversion, presence/default/null, scope/identity validation và nhóm processing/filesystem/admin. Nếu thực sự cần module boundary thì giữ import/export rõ ràng và cập nhật mọi consumer cùng PR. Không tạo generic RPC repository, generic mapper hoặc ép Go/Python dùng cùng implementation pattern.

Rà deadlines/retries/error translation ở Go/Python RPC theo semantics thực. Read và mutation không mặc nhiên có cùng retry policy; typed actors, delegation allowlists, TLS, trace propagation và stream cancellation là contract bắt buộc.

Không edit `packages/go/gen/`, `openlet_api`, `_authz_actions.py` hoặc generated action matrix trực tiếp. Sửa nguồn contract/generator khi có yêu cầu rồi chạy `pnpm contracts:check` và generation đúng quy trình. Refactor giữ behavior không tự đổi proto namespace, API version hay schema baseline.

Nghiệm thu shared unit/integration, wheel-consumer/import-boundary tests và tất cả consumer bị tác động đạt; wire shape và public errors không đổi. Migrations chỉ rà tính đúng và owning docs; không sửa migration đã áp dụng như một thao tác cleanup.

## 7. Tooling, infrastructure và nghiệm thu toàn repo

Phạm vi: `scripts/{bootstrap,operations,performance,contracts}`, `infra/`, Dockerfiles của từng app, `e2e/{fixtures,setup,tests,external}`, `.github/`, root/app manifests, lockfiles, Makefile, Turbo/uv/Go workspace config và `docs/`.

Rà command ownership, duplicated setup/teardown, redaction, deterministic ports, bounded resources và process/container cleanup. CI trước đây đã được deduplicate; phải trace task graph hiện tại trước khi bỏ gate. Không bật caching cho integration/recovery chỉ để rút thời gian.

`scripts/operations/recovery.py` là đường vận hành quan trọng: độ dài file không đủ lý do viết lại. Bảo vệ owner-safe fencing/drain, coordinated metadata+object snapshot, corrupted-snapshot rejection và restore vào môi trường cô lập. Giữ public Envoy và private gRPC trust boundaries trong Compose/templates.

Mỗi test chỉ bị bỏ khi chứng minh duplicate cùng invariant ở cùng boundary hoặc contract đã thay đổi có chủ ý. Unit test không thay được real SQL locks/S3/recovery; fixture history không bị xóa chỉ vì cũ. Live-provider tests tiếp tục opt-in.

Chạy E2E typecheck, real setup/recovery checks, API journeys và native replay theo `docs/testing.md`; parser gate nếu bị ảnh hưởng. Kiểm tra docs bằng source/config hiện tại, cập nhật owning surface nhỏ nhất. Plan/report lịch sử không trở thành kiến trúc hiện hành và không bị xóa hàng loạt.

Nghiệm thu: coverage ledger bao phủ toàn phạm vi; final diff không chứa unrelated edits, generated drift, artifact tạm hoặc secrets; checks và môi trường chưa kiểm chứng được ghi riêng. Dừng mọi process/container do đợt thực hiện sở hữu.

## Cách chia PR và rollback

Mỗi PR đi hết một luồng hoặc một invariant: implementation, callers, tests, exports/fixtures và docs nếu có tác động. Ghi lý do giữ/xóa từng abstraction quan trọng và bằng chứng trước/sau. Nếu không tìm thấy thay đổi có ích, ghi giữ nguyên rồi chuyển vùng tiếp theo.

PR đầu tiên chỉ xử lý schedule persistence/validation của Leta sau khi trace callers; không kèm đổi tên workflow, schema, runtime engine hay shared RPC. Dùng kết quả lát cắt này để ước lượng phần còn lại; chưa đặt deadline toàn repo khi chưa có baseline thực thi.

Rollback source theo PR/commit cụ thể, giữ nguyên thay đổi của người khác. Không dùng reset database, xóa volume hoặc restore toàn working tree để rollback code. Nếu durable history/wire/schema bắt buộc thay đổi, tách riêng kế hoạch tương thích và rollout trước khi triển khai.
