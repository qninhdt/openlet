# Brainstorm refactor Openlet theo ba note

Ngày: 2026-10-31. Trạng thái: phân tích và quyết định bước đầu; chưa triển khai.

## Nguồn và quyền ưu tiên

Đã tải và giải mã ZIP do người dùng cung cấp, kiểm tra authentication của metadata và từng chunk. ZIP SHA-256: `1f5074616471cf6f28901739b6fc014c2dc56415a6ba13e3011f5cf5b503950f`.

- [Architecture decisions](../261031-1738-refactor-three-notes/inputs/openlet-architecture-decisions.md) sở hữu monorepo/testing/infra.
- [Final architecture](<../261031-1738-refactor-three-notes/inputs/openlet-final-architecture-status-to-processing (1).md>) sở hữu API/lifecycle.
- [Note đánh số](<../261031-1738-refactor-three-notes/inputs/1. xóa bảng operation của user và workspace, quá.md>) bổ sung semantic pipeline và tách worker.

Người dùng đã xác nhận thứ tự này. Các note là target design, không chứng minh implementation hiện tại.

## Hợp đồng đầu ra

**Outcome:** Refactor backend theo cả ba note: bỏ generic operations và staging copy toàn cây; đơn giản hóa retry bằng natural idempotency/receipts; orchestration Temporal trực tiếp; resource-oriented APIs; nodes/files và semantic pipeline đúng ownership; ZIP HTTP streaming; hai nhóm processing workers; monorepo và testing/infra theo kiến trúc mới.

**Constraints:** Chưa có production. Người dùng cho phép sửa/xóa và không cần backward compatibility. Việc reset DB thực tế vẫn phải có backup theo quy tắc project. Giữ các thay đổi có sẵn trong working tree. Không bỏ authorization, namespace uniqueness, revisions, quota transaction, cleanup evidence hoặc stale-attempt/version fencing. Resource owner sinh resource IDs. Giữ chức năng ID/path, artifact readonly, trash/restore và search trừ khi có quyết định thay đổi rõ ràng.

**Non-goals:** Bước này chưa sửa code/schema hay reset dữ liệu. Không tạo frontend, billing, cloud platform, Nexus deployment, framework orchestration/test mới hoặc rollback copy riêng. Các đánh giá chất lượng parser từ phiên trước là bằng chứng cần tham khảo, chưa tự động mở rộng thành yêu cầu sửa toàn bộ parser.

**Acceptance criteria cho delivery sau brainstorm:**

1. Không còn generic operations, copy_items, deletion_items, export_attempts và staging_operation_id trong thiết kế cuối; các nghĩa vụ đang nằm trong đó đã có owner cụ thể.
2. Concurrent retry, mất response sau commit, worker restart và Continue-As-New không tạo trùng resource, cộng/trừ quota hai lần, hoặc làm mất công việc đã được API nhận.
3. Copy hiển thị partial progress, không rollback toàn cây; purge/delete tiếp tục dọn phần còn lại. Mỗi file được publish khi bytes sẵn sàng.
4. ZIP stream giữ cấu trúc/empty directories, bounded buffers/backpressure, dừng khi disconnect và không tạo object ZIP tạm. Limits/timeouts áp dụng xuyên Workspace/Envoy/Letfs. Lỗi sau khi headers đã gửi phải làm stream thất bại, không tạo ZIP có vẻ thành công nhưng thiếu file.
5. Semantic fields và MIME thuộc files; artifact folder dùng README của nó. Enrich lá rồi README cha, cuối cùng root README và copy metadata sang original. Search và stale-version filtering cùng chuyển đổi.
6. Parse CPU và enrich/index I/O có queues/workers/concurrency riêng trong cùng Python application. Upload transport dùng chung nhưng publication/index readiness vẫn do Letfs kiểm soát.
7. Native unit/integration + Testcontainers, Playwright API E2E + Compose, replay/recovery giữ các bảo đảm có giá trị. Native workspaces, Docker builds, Turbo task discovery, contracts và docs đồng bộ.

## Các quyết định đã xác nhận

- Được thay schema/API trực tiếp, không cần lớp tương thích cũ.
- Không yêu cầu snapshot toàn cây khi copy. Kiểm tra từng mục; lỗi thay đổi nguồn/đích thì dừng và giữ phần đã commit. Mục thêm trong lúc copy có thể được lấy hoặc không.
- Người dùng yêu cầu chọn cách xử lý partial progress đơn giản, hợp lý. Đề xuất giữ kết quả đã xong, không xây rollback riêng; chưa có yêu cầu thêm rollback.
- Dùng child workflow khi workflow gọi một quy trình con do app khác sở hữu. Remote Activity so với HTTP được yêu cầu tra cứu trước khi chốt.

## Đối chiếu source hiện tại

| Phạm vi | Bằng chứng | Hệ quả thiết kế |
|---|---|---|
| Onboarding | [OnboardUser](../../services/user/internal/temporal/workflows.go) gọi HTTP start Workspace rồi GetInitialWorkspaceStatus, sleep/poll và Continue-As-New. | Thay bằng child CreateWorkspace, chờ result qua Temporal. User natural identity theo Clerk; bỏ operation riêng. |
| Workspace | [Store](../../services/workspace/internal/workspace/store.go) dùng operations cho dedup/result và workspace_storage riêng; [deletion](../../services/workspace/internal/workspace/deletion.go) lưu cursor trong operations. | Gộp storage vào workspaces; receipt cho create; deletion cursor/input chuyển về workflow hoặc lifecycle owner thích hợp. |
| Cross-service delete | [DeleteWorkspace](../../services/workspace/internal/temporal/deletion.go) gọi HTTP EnsureFilesystemDeletion rồi polling. | Child DeleteFilesystem; short mutations có thể đi remote Activity. |
| Copy/delete | [Copy](../../services/letfs/src/fs/copy.rs), [deletion](../../services/letfs/src/fs/deletion.rs) và [CopyNode](../../services/letfs/src/temporal/copy_workflow.rs) phụ thuộc item tables, staging và discard. | Chấp nhận partial progress bỏ được whole-tree publish/discard. Vẫn phải có destination identity ổn định, bounded traversal/checkpoint, guard concurrent changes và quota theo transaction. |
| Processing identity | [Processing](../../services/letfs/src/fs/processing.rs) kiểm tra generation/attempt/source identity từ operations. | Không xóa kiểm tra này cùng bảng. Chọn domain owner cho publication generation và index readiness; không chép execution history vào receipt. |
| Semantic | [Schema](../../services/letfs/migrations/0011_semantic_processing.sql) thêm metadata vào nodes. [enrich_tree](../../services/letfs/processor/src/openlet_processor/semantic.py) đã duyệt bottom-up nhưng describe folder rồi copy sang README. [readme](../../services/letfs/processor/src/openlet_processor/readme.py) đặt tên folder dựa trên metadata folder. | Đổi chủ thể enrichment sang README; folder path/title derivation lấy từ README, không giữ semantic fields trên folder. Thay taxonomy cả Python/Rust/contracts/search/tests. |
| Workers | [Python worker](../../services/letfs/processor/src/openlet_processor/worker.py) đăng ký parse/enrich/index cùng queue với max_concurrent_activities=1; [Rust workflow](../../services/letfs/src/temporal/process_file_workflow.rs) cùng queue cho ba stage. | Tách hai queue và hai worker processes; không chỉ tăng concurrency chung. Tách startup/import để worker I/O không bị bắt buộc nạp models/OCR khi không cần. |
| Upload evidence | [Uploads](../../services/letfs/src/fs/uploads.rs) tính composite multipart ETag từ MD5, rồi so HEAD size/ETag. Đã có completion_parts durable và xử lý completion mất response. | Sửa verification theo provider capability; giữ receipts/reconciliation, không xem ETag luôn là full-content checksum. |
| Object cleanup | [Maintenance](../../services/letfs/src/fs/maintenance.rs) giữ ambiguous_write và re-delete terminal candidates; kiểm tra cả copy_items/export_attempts đang dùng. | Giữ transactional outbox; bỏ dependency theo thiết kế mới. Chưa được prune ambiguous candidates chỉ vì URL hết hạn hoặc DeleteObject từng thành công. |
| ZIP | [Exports](../../services/letfs/src/fs/exports.rs) đã có enumerate/limits/name validation và async_zip dependency, nhưng export là workflow/S3 object. [Envoy](../../deploy/envoy/openlet.template.json) timeout 120s; Workspace server write timeout 125s. | Tái sử dụng validation có giá trị; chuyển writer thành HTTP stream xuyên facade/gateway, không thêm dependency ZIP mới. |
| Test/infra | [Makefile](../../Makefile), [testing](../../docs/testing.md) và [Compose test](../../deploy/compose.test.yaml) hiện dùng Go E2E và shell orchestration. | Chuyển scenarios có giá trị sang kiến trúc đã chọn; bỏ harness cũ sau khi có coverage thay thế, không chỉ đổi tên thư mục. |

## Temporal: tài liệu và đề xuất

Temporal hỗ trợ Activity thực thi ở worker khác qua task queue, và Activity cũng có thể gọi HTTP. Không có quy tắc bắt buộc mọi microservice phải dùng cùng một transport. [Task Queues](https://docs.temporal.io/task-queue) mô tả routing, persistence và worker polling. Go SDK v1.50.0 đang cài hỗ trợ ExecuteActivity theo tên và TaskQueue; Rust v1.1.0 có typed ActivityDefinition và ActivityOptions.task_queue. Project cũng đã có Rust gọi Python activity qua queue.

[Child Workflows](https://docs.temporal.io/child-workflows) dùng cho quy trình riêng, worker fleet khác hoặc chia execution/history; không nên bọc từng thao tác nhỏ chỉ để tổ chức code. Child và parent ở cùng namespace. Project hiện dùng namespace openlet.

| Cách | Giả định chính | Điểm thất bại đầu tiên |
|---|---|---|
| Remote Activity, đề xuất cho mutation nội bộ của Temporal | Cùng control plane/namespace tin cậy; chấp nhận contract gồm activity name, queue và payload. | Cần tách quyền/team/namespace độc lập hoặc schema registration không tương thích. |
| Activity gọi HTTP | App đích cần giữ HTTP làm service contract độc lập. | Tăng adapter/network hops và mapping lỗi/timeout; HTTP start + polling làm trùng orchestration nếu đích vốn là workflow. |
| Nexus | Cần business service contract độc lập, nhất là khác team/namespace. | Thêm setup/contract/SDK-support work khi hiện chưa cần boundary này. |

**Khuyến nghị:** Child cho OnboardUser → CreateWorkspace và DeleteWorkspace → DeleteFilesystem. Các thao tác ngắn như tạo quota bucket/filesystem, freeze/complete bucket chạy remote Activities tại Letfs worker, gọi cùng domain functions với HTTP handlers. Caller không truy cập DB của app đích. HTTP vẫn dùng cho client/facade, processor resource/byte APIs và external providers; không chuyển bytes sang Temporal payload.

Remote Activities không loại bỏ at-least-once side effects: vẫn cần natural identities/receipts. Payload xuyên Go/Rust phải có contract JSON tương thích và real integration test. Queue không thay authorization boundary. Chốt parent-close/cancellation policy cho deletion; không để mặc định terminate vô tình cắt công việc đã nhận.

[Nexus guidance](https://docs.temporal.io/nexus/choosing-an-approach) phân biệt trực tiếp gọi workflow do cùng team sở hữu với service contract dành cho team khác/namespace khác. Chưa có bằng chứng Openlet cần thêm Nexus trong scope hiện tại. [Activity granularity](https://temporal.io/blog/how-many-activities-should-i-use-in-my-temporal-workflow) ủng hộ chia theo transaction, retry/timeout hoặc queue riêng.

**Better approaches:** Khuyến nghị remote Activity cải thiện đề xuất ban đầu giữ Go Activity gọi HTTP cho mutation Letfs: worker Rust đã có domain logic và cùng namespace. Delta là bỏ HTTP adapters trong đường orchestration; chi phí là đăng ký cross-language activity DTOs và contract tests. Đây vẫn là đề xuất chờ người dùng phản hồi.

## Thứ tự delivery đề xuất

So với sửa đồng thời schema/API/layout/testing, các lát chức năng kiểm chứng được giúp tách lỗi path/build khỏi lỗi nghiệp vụ. Cách đồng thời dựa vào giả định có thể debug nhiều lớp đang đổi cùng lúc; nó thất bại sớm khi mất baseline. Cách chia lát dựa vào acceptance rõ cho từng lát; nó thất bại nếu giữ implementation cũ song song quá lâu. Vì không cần compatibility, mỗi lát có thể thay hẳn implementation liên quan.

1. Chốt hợp đồng/schema đích và bảng trách nhiệm đang nằm trong operations. Ghi coverage cần giữ.
2. Chuyển layout/workspaces/build paths và dựng các entrypoints native test/Compose cần thiết; giữ baseline hành vi để các bước sau có kiểm chứng.
3. Account/workspace lifecycle, storage mapping, receipts và child/remote activity orchestration.
4. Letfs nodes/files, upload transport/verification, partial copy/delete, outbox và HTTP ZIP. Đổi HTTP contracts/callers/tests cùng lát sở hữu.
5. Processing publication/version fences, README semantics/taxonomy, search/index và hai nhóm workers. Hoàn tất Playwright scenarios, replay/recovery và bỏ harness cũ.

Đây là thứ tự thảo luận, chưa phải implementation plan. Mỗi giai đoạn vẫn cần checks phù hợp, không hoãn mọi testing tới cuối.

## Giới hạn kiểm chứng

Đã đọc ba note, docs, manifests và source liên quan qua CodeGraph/source hiện hành; tra Temporal official docs, Context7 và SDK source cài tại máy. Chưa chạy tests, benchmark, paid model requests, provider checks hay thử cross-language Activity mới. Chưa sửa application/config/docs hiện hành. Chưa kết luận API/provider checks từng pass ở phiên trước chứng minh target design mới.

## Các điểm còn cần chốt hoặc chứng minh

1. Người dùng có chọn khuyến nghị remote Activities cho mutation nội bộ Temporal không.
2. Chốt receipt TTL, scope key, result/handle retention và recovery tại ranh giới SQL commit ↔ Temporal start; không nhận công việc rồi để mất dispatch khi process crash.
3. Invitation retry contract khi DB chỉ lưu token hash; không tự thêm email delivery trái scope hiện tại.
4. Late-write/reconciliation policy và checksum evidence cho provider thực tế trước khi giảm cleanup schema.
5. Domain schema tối thiểu cho processing/version publication, stable output identity và index fencing; không đổi tên operations thành một generic job table khác.
6. ZIP consistency khi nguồn bị replace/purge giữa stream, giới hạn thời gian xuyên proxy và hành vi lỗi sau headers. Copy đã được chấp nhận không snapshot; điều đó không tự quyết định ZIP contract.
