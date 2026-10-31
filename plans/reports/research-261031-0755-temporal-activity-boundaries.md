# Ranh giới Temporal activity trong Openlet

Khảo sát ngày 2026-10-31, Asia/Ho_Chi_Minh. Phạm vi: toàn bộ activity và workflow được đăng ký trong user, workspace, letfs và Python processor trên working tree hiện tại.

## Kết luận

Openlet có 9 workflow và 31 activity definitions. Ranh giới hiện tại nhìn chung hợp lý: DB admission, tác động qua dịch vụ ngoài, publication và cleanup được retry riêng. Chưa có lý do từ source để gộp hàng loạt.

Cặp EnsureStorageBucket/EnsureDriveFilesystem có thể gộp nếu cần giảm một lượt activity khi tạo workspace. Hai vòng polling mỗi giây là nơi đáng đánh giá trước khi tối ưu số lượng activity. File processing tiếp tục dùng ba activity cấp toàn original file: parse, enrich và index.

## Tiêu chí tách activity

[Temporal định nghĩa activity](https://docs.temporal.io/activity-definition) là một hành động có mục đích rõ ràng. [Tài liệu execution](https://docs.temporal.io/activities) nêu rằng retry bắt đầu lại activity từ đầu, trừ khi ứng dụng sử dụng checkpoint; chia việc lớn giúp recovery, timeout và idempotency.

Áp dụng vào Openlet, tách khi có ít nhất một nhu cầu cụ thể:

1. **Cần giữ kết quả bước trước khi bước sau retry.** Ví dụ indexing lỗi thì sử dụng enrichment đã lưu.
2. **Cần lịch chạy hoặc điều kiện thực thi riêng.** Ví dụ workflow phải chờ trạng thái remote, rẽ nhánh theo kết quả, hoặc chỉ chạy cleanup khi thất bại.
3. **Cần chính sách thực thi riêng.** Timeout, heartbeat, worker/task queue, tài nguyên hoặc rate limit khác nhau đủ để cần cấu hình riêng.
4. **Cần giới hạn một đơn vị công việc lớn.** Batch giúp giới hạn transaction, thời gian chạy và lượng công việc phải làm lại.

Gộp khi các phần luôn chạy cùng nhau, có thể retry cùng nhau với chi phí chấp nhận được và không cần workflow điều phối ở giữa. Số dòng wrapper hoặc thời gian chạy ngắn chưa đủ để kết luận nên gộp. Các thao tác cần atomicity vẫn phải dùng transaction hoặc publication contract thích hợp; activity không tạo transaction xuyên hệ thống.

Sampling, slug, render metadata và chuẩn bị payload được giữ thành hàm nội bộ khi dùng chung ranh giới retry. [Hướng dẫn Local Activity](https://docs.temporal.io/local-activity) ưu tiên regular activities cho nhu cầu thông thường; chỉ tối ưu bằng local activities khi có nhu cầu hiệu năng cụ thể.

## Kết quả theo workflow

| Service và workflow | Activity definitions | Đánh giá |
|---|---:|---|
| user: OnboardUser | 6 | Giữ. Lưu user, khởi tạo/chờ workspace, cập nhật Clerk và hoàn tất DB có kết quả và lỗi riêng. |
| workspace: CreateWorkspace | 5 | Giữ admission và activation riêng. Cặp provision bucket/filesystem có thể gộp. |
| workspace: DeleteWorkspace | 8 | Giữ. Freeze, duyệt filesystem, chờ xóa, lưu cursor và hoàn tất hai service là các mốc riêng. |
| letfs: CopyNode | 5 | Giữ. Prepare, copy batch, publish và cleanup có mốc commit và recovery riêng. |
| letfs: PurgeTrash, DeleteFilesystem, StorageMaintenance | 5 dùng chung | Giữ. Deletion theo batch; maintenance phân biệt hết hạn upload, dọn staging và xóa object. |
| letfs: ExportArchive | 1 | Giữ. Prepare/build/upload/publish cùng một attempt, heartbeat và giới hạn runtime. |
| letfs: ProcessFile | 1 trong Python | Giữ parse thành một activity. Download/convert/upload/publish dùng chung scratch directory và attempt. Phase 2 bổ sung enrich_file và index_file. |

### user

[OnboardUser và Activities](../../services/user/internal/temporal/workflows.go) gồm EnsureUser, EnsureInitialWorkspace, GetInitialWorkspaceStatus, PublishClerkUserID, CompleteOnboarding và FailOnboarding.

PublishClerkUserID thành công là mốc đáng giữ: lỗi ghi CompleteOnboarding chỉ cần retry DB. GetInitialWorkspaceStatus đọc trạng thái ngoài nên nằm trong activity, còn thời gian chờ do workflow.Sleep quản lý. Vòng chờ hiện poll mỗi giây và Continue-As-New sau 200 polls. Polling nhiều tạo thêm activity và history theo thời gian chờ; có thể tăng dần khoảng chờ khi trạng thái chưa đổi nếu độ trễ sản phẩm cho phép.

### workspace

[CreateWorkspace](../../services/workspace/internal/temporal/workflows.go) gồm EnsureWorkspace, EnsureStorageBucket, EnsureDriveFilesystem, ActivateWorkspace và FailWorkspace.

EnsureStorageBucket và EnsureDriveFilesystem chạy nối tiếp, cùng letfs, dùng chung timeout/retry options. [letfs provisioning](../../services/letfs/src/fs/mod.rs) hỗ trợ gọi lại với ID/provision_key cố định. Có thể gộp thành EnsureWorkspaceStorage; đổi lại lỗi filesystem sẽ gọi lại cả ensure bucket. Giữ hai activity giúp retry riêng bước filesystem; gộp giúp giảm một lượt activity. Khuyến nghị hiện tại là giữ, vì chưa có số đo cho thấy lượt này gây chi phí đáng kể.

[DeleteWorkspace](../../services/workspace/internal/temporal/deletion.go) gồm BeginDeletion, GetDeletion, FreezeBucket, ListBucketFilesystems, EnsureFilesystemDeletion, AdvanceDeletion, CompleteBucketDeletion và CompleteWorkspaceDeletion. BeginDeletion/GetDeletion là hai nhánh khởi tạo/tiếp tục, không chạy nối tiếp trong mỗi lần workflow.

AdvanceDeletion ghi cursor phục vụ Continue-As-New sau khi remote deletion hoàn tất. CompleteBucketDeletion và CompleteWorkspaceDeletion chạm hai chủ sở hữu dữ liệu. Các mốc này có lý do recovery cụ thể. Vòng chờ EnsureFilesystemDeletion cũng poll mỗi giây; áp dụng cùng đánh giá polling như onboarding.

### letfs và processor

[CopyNode](../../services/letfs/src/temporal/copy_workflow.rs) gồm prepare_copy, copy_batch, publish_copy, mark_copy_discarding và discard_copy_batch. Copy batch có timeout 180 giây và heartbeat; prepare/publish dùng timeout 30 giây. [Implementation](../../services/letfs/src/fs/copy.rs) duyệt tối đa 64 children của một item hoặc copy một object trong mỗi lượt. Inline leaves có thể được tạo sẵn ở trạng thái ready theo batch. Đây là xử lý tăng tiến trong một workflow copy cả cây; batch size có thể đánh giá theo workload sau.

[Lifecycle activities](../../services/letfs/src/temporal/lifecycle_workflow.rs) gồm begin_deletion, delete_nodes_batch, expire_uploads_batch, discard_failed_copies_batch và delete_objects_batch. [Deletion](../../services/letfs/src/fs/deletion.rs) xử lý tối đa 64 nodes/children trong một lượt; [maintenance](../../services/letfs/src/fs/maintenance.rs) đã gom nhiều thao tác trong batch. Các giới hạn này giữ transaction/công việc hữu hạn.

[ExportArchive](../../services/letfs/src/temporal/export_archive_workflow.rs) gọi export_archive với start-to-close 1900 giây, schedule-to-close 7200 giây, heartbeat 30 giây và tối đa 3 attempts. Prepare/build/publish nằm trong cùng activity và attempt.

[ProcessFile](../../services/letfs/src/temporal/process_file_workflow.rs) gọi Python [process_file](../../services/letfs/processor/src/openlet_processor/activity.py) với start-to-close 1800 giây, schedule-to-close 7200 giây, heartbeat 30 giây và tối đa 3 attempts. Các bước chuẩn bị/download/convert/upload/complete cùng dùng một attempt và thư mục tạm.

## Áp dụng cho phase 2 đã chốt

- process_file parse và publish cây artifact.
- enrich_file sinh metadata bottom-up rồi publish tên, README và relative links cho cả cây.
- index_file tạo file/chunk representations, embedding và Qdrant index cho cả cây.

Mỗi activity hoàn tất lưu kết quả để activity kế tiếp retry độc lập. Các model calls, node traversal và embedding batches là công việc nội bộ của activity tương ứng. Với text nguồn không cần parse, workflow bắt đầu ở enrich_file.

## Hành động đề xuất

Giữ các ranh giới hiện tại khi lập plan phase 2. Ghi nhận polling interval của onboarding và workspace deletion để đánh giá theo thời gian chờ thực tế. Nếu tối ưu provisioning, thay đổi đúng cặp bucket/filesystem và cập nhật workflow tests cùng replay compatibility.

Kiểm chứng của khảo sát là đọc registration, workflow, activity implementation, DB batch logic và các workflow test hiện có; chưa đo latency, event volume hoặc chi phí Temporal trên runtime.
