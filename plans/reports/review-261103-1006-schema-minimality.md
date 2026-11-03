# Review toàn bộ schema ứng dụng Openlet

What this change does: Đây là review, chưa thay đổi implementation. Đã kiểm kê 14 bảng, 150 cột từ ba migration hiện hành của Account, Workspace và letfs, đối chiếu các đường tạo resource, onboarding, upload, parse, enrichment, indexing, copy và cleanup.

Phạm vi hiện tại: các tính năng backend đã có; chưa có production data; không cần phân quyền sở hữu giữa các service; không lưu cấu hình embedding trên từng resource. Chỉ dùng tính idempotent tự nhiên của resource hoặc bảng idempotency đã có. Không thêm bảng, binding, khóa provisioning, attempt protocol hay bản sao workflow state để thay các cột bị bỏ.

## Should fix

1. **Quyền sở hữu giữa service ngoài phạm vi hiện tại: 3 cột.**
   - What this is: `quota_buckets.creator_service`, `quota_buckets.create_fingerprint`, `filesystems.create_fingerprint` đang kiểm tra service sở hữu và hash tham số tạo ban đầu suốt đời resource. Xem [provisioning.go](../../apps/letfs/internal/filesystem/provisioning.go:140).
   - Problem: người dùng đã loại bỏ yêu cầu phân quyền giữa service và lớp fingerprint bên ngoài bảng idempotency. Caller thực tế dùng ID đã lưu làm idempotency key, trong [Workspace workflow](../../apps/workspace/internal/temporal/workflows.go:101).
   - Fix: bỏ ba cột cùng check/constraint/API context chỉ phục vụ chúng. Giữ authentication, quyền user qua SpiceDB, bảng idempotency, PK và lifecycle hiện có; không tạo owner binding hay khóa mới.
   - If we skip it: vẫn giữ hai yêu cầu người dùng đã loại khỏi sản phẩm.

2. **Workspace lưu chi tiết workflow và input tạo lặp lại: 4 cột.**
   - What this is: `workspaces.creation_workflow_id`, `workspace.idempotency_keys.workflow_id`, `request_input`, `operation`. Hai cột Workflow ID đang chứa cùng giá trị; `operation` bị CHECK cố định là `create-workspace`. Xem [store.go](../../apps/workspace/internal/workspace/store.go:125), [reconciliation.go](../../apps/workspace/internal/workspace/reconciliation.go:16).
   - Problem: workflow gọi lại hàm nhận tạo resource, nên implementation lưu Workflow ID trên resource để tìm lại nó sau receipt expiry, rồi lưu input để diễn lại create. Trong khi HTTP đã commit workspace/member/receipt trước khi start workflow. Onboarding hiện dùng một đường child workflow khác, xem [Account workflow](../../apps/account/internal/temporal/workflows.go:92).
   - Fix: dùng lại admission hiện có của Workspace cho cả HTTP và onboarding; sau admission, workflow chỉ nhận workspace ID đã tồn tại và provision resource đó. Tính native Temporal Workflow ID từ workspace ID. Reconciliation tiếp tục resource đang pending bằng ID; không dựng lại request tạo. Bỏ bốn cột; khóa receipt của Workspace còn `(actor_id, request_key)` vì bảng này hiện chỉ chứa một operation.
   - If we skip it: data model tiếp tục phụ thuộc vào lịch sử/cách đặt tên workflow và có thêm đường chống tạo lặp sau receipt expiry. Không được chỉ drop cột rồi giữ nguyên luồng caller cũ.

3. **Receipt lưu hai timestamp có thể suy ra nhau: 2 cột.**
   - What this is: `completed_at` trong cả hai bảng idempotency. DDL buộc completion/expiry cùng null và `expires_at = completed_at + 24 hours`.
   - Problem: runtime dùng `completed_at IS NULL` để nhận diện receipt chưa hoàn tất; không có nghiệp vụ đọc thời điểm hoàn tất riêng. Xem [Workspace reconciliation](../../apps/workspace/internal/workspace/reconciliation.go:47).
   - Fix: giữ `expires_at`: null nghĩa là còn pending; khi hoàn tất chỉ set một lần thành `now()+24h`. Thay predicate bằng `expires_at IS NULL`. Không thêm status hay bảng receipt mới.
   - If we skip it: mọi completion path tiếp tục phải cập nhật và kiểm tra hai bản của cùng một thông tin.

4. **Hai generation phụ không đại diện cho phiên bản độc lập: 2 cột.**
   - What this is: `files.published_generation`, `files.indexed_generation`. DDL buộc giá trị khác null bằng generation hiện tại; code clear chúng khi nhận nội dung mới.
   - Problem: sản phẩm hiện không phục vụ generation cũ trong lúc generation mới xử lý. Publication/index status đã biểu diễn việc kết quả hiện tại sẵn sàng hay chưa. Xem [CompleteEnrichment](../../apps/letfs/internal/filesystem/enrichment.go:399), [CompleteIndex](../../apps/letfs/internal/filesystem/indexing.go:116).
   - Fix: giữ một `desired_generation` cho phiên bản nội dung hiện tại. Nếu API vẫn trả hai trường phụ, tính từ generation và trạng thái, không lưu lại trong DB.
   - If we skip it: giữ thêm các assignment, null-state và predicate lặp trên mọi đường ghi/search.

5. **Hash ngoài receipt mở rộng hợp đồng kiểm tra payload: 4 cột.**
   - What this is: `files.processing_source_identity`, `parse_manifest_hash`, `publication_manifest_hash`, `uploads.sha256`.
   - Problem: source hash kiểm tra thêm việc bytes bị sửa mà generation không đổi; test dựng tình huống này bằng [SQL trực tiếp](../../apps/letfs/internal/filesystem/processing_integration_test.go:84). Đường thay nội dung nguồn của ứng dụng tăng generation cùng transaction; enrichment cấm sửa bytes nguồn. Hai manifest hash và upload SHA-256 chủ yếu đòi callback/write lặp với payload khác phải conflict sau khi resource đã hoàn tất, xem [WriteOutputBytes](../../apps/letfs/internal/filesystem/processing_uploads.go:276).
   - Fix: bỏ bốn hash. Giữ bất biến thay nội dung và tăng generation trong cùng transaction; dùng resource/upload identity và trạng thái đã hoàn tất cho thao tác tự nhiên, bảng idempotency hiện có cho admission cần receipt. Không chuyển hash sang bảng khác. Giữ `request_hash` trong bảng idempotency, `token_hash` của invitation và Content-MD5 mà S3 yêu cầu.
   - If we skip it: vẫn giữ nhiều lớp kiểm tra payload chỉ để thỏa contract nội bộ đã tự mở rộng. Bỏ hash nghĩa là chủ động bỏ contract conflict-after-completion đó, không tuyên bố giữ nguyên contract cũ.

6. **Giao thức attempt riêng giữa ingest và letfs: 4 cột.**
   - What this is: `files.accepted_attempt`, `accepted_attempt_id`, `uploads.processing_attempt`, `processing_attempt_id`. Python lấy số attempt từ Temporal rồi tự sinh thêm UUID, xem [activity.py](../../apps/letfs-ingest/src/letfs_ingest/activity.py:120).
   - Problem: ngoài native retry, code buộc toàn bộ prepare/upload/publish/cleanup mang attempt metadata và duy trì acceptance riêng. Đây là phần ngoài nhu cầu hiện tại mà người dùng đã yêu cầu bỏ.
   - Fix: bỏ cả protocol, RPC fields và unique/index predicates phụ thuộc attempt. Resource hiện tại, trạng thái publish và receipt sẵn có phải được dùng xuyên luồng. Publish dùng các upload ID trong kết quả thực tế của activity, không bắt tất cả output từng được tạo phải thuộc một custom attempt. Không thay bằng lease, execution token, worker UUID hay processing-run table.
   - If we skip it: vẫn còn bộ điều phối attempt tự xây. Không thể chỉ drop cột: phải bỏ assumption cũ trong output selection/cleanup và kiểm tra retry của worker bằng luồng thật.

7. **Actor của processing chỉ điền vào output nội bộ: 1 cột.**
   - What this is: `files.processing_actor_id` được copy vào `uploads.actor_id`, xem [processing_uploads.go](../../apps/letfs/internal/filesystem/processing_uploads.go:191).
   - Problem: consumer hiện tại không dùng nó để kiểm tra quyền processing hoặc cung cấp audit. Output ingest được xác thực bằng service identity và source/output scope; public upload bị tách khỏi output nội bộ bằng source binding.
   - Fix: bỏ field trên file và việc ép output nội bộ có actor của user. `uploads.actor_id` vẫn bắt buộc cho upload của user, có thể null cho output ingest. Không tạo bảng actor/job khác.
   - If we skip it: tiếp tục lưu và truyền một user ID chỉ để thỏa shape chung của bảng uploads.

8. **Cấu hình embedding được lưu theo resource: 6 cột.**
   - What this is: `embedding_model`, `vector_collection`, `vector_dimension` trên cả `files` và `index_deletions`.
   - Problem: phục vụ nhiều vector space/lịch sử cấu hình, ngoài phạm vi người dùng vừa xác định. Xem [indexing.go](../../apps/letfs/internal/filesystem/indexing.go:80), [index_cleanup.go](../../apps/letfs/internal/filesystem/index_cleanup.go:18).
   - Fix: dùng cấu hình embedding hiện tại của hệ thống. Bỏ cột, composite key/filter và index-only reconciliation chỉ để hỗ trợ nhiều cấu hình. Không thay bằng bảng embedding profile, registry hoặc configuration revision.
   - If we skip it: mỗi file và cleanup row tiếp tục mang bản sao cấu hình triển khai. Việc đổi cấu hình rồi giữ đồng thời index cũ/mới không nằm trong phạm vi này.

9. **Hai cột trạng thái cho cùng pipeline tuyến tính: gộp 1 cột.**
   - What this is: `files.publication_status` và `index_status` được kiểm tra cùng nhau trong dispatch, search và reconciliation.
   - Problem: model phải duy trì tổ hợp hai status mặc dù workflow hiện chạy tuần tự parse, enrichment, indexing. Xem [processing.go](../../apps/letfs/internal/temporal/processing.go:25).
   - Fix: dùng một cột hiện có làm trạng thái pipeline, biểu diễn các mốc đã hoàn tất và lỗi thực sự cần phân biệt. Không thêm cờ cho từng stage, stage table hoặc execution blob. Giữ filename search độc lập với semantic readiness.
   - If we skip it: vẫn giữ các tổ hợp trạng thái và constraint đồng bộ không cần thiết.

10. **Upload lưu thêm hai giá trị không được đọc độc lập: 2 cột.**
    - What this is: `uploads.size_bytes` và `write_expires_at`. Kích thước serving được đọc từ `expected_size`; finalized CHECK buộc size bằng expected. Thời điểm write chỉ được giữ để lấy max và kiểm tra khác null, trong khi `transfer_deadline` đã lưu deadline cần cho cleanup.
    - Problem: [publishUpload](../../apps/letfs/internal/filesystem/upload_publication.go:185) copy expected size sang size; [recordCapability](../../apps/letfs/internal/filesystem/uploads.go:367) ghi hai mốc nhưng cleanup chỉ dùng giá trị deadline.
    - Fix: bỏ size copy, tiếp tục kiểm tra HEAD/byte count bằng expected size. Bỏ write expiry, dùng `transfer_deadline IS NOT NULL` để biết đã cấp capability và chính deadline đó để dọn. Không thêm verified-size hoặc signed flag thay thế.
    - If we skip it: vẫn ghi thêm hai bản giá trị mà luồng hiện tại không cần.

11. **Cấu hình max nodes bị copy vào filesystem: 1 cột.**
    - What this is: `filesystems.max_nodes` được copy từ `Store.MaxNodes` khi tạo filesystem. Hiện không có API cấu hình giới hạn riêng từng filesystem.
    - Problem: đổi `MAX_NODES` không đổi cột đã copy; đây là cấu hình resource riêng tự phát sinh. Xem [provisioning.go](../../apps/letfs/internal/filesystem/provisioning.go:212).
    - Fix: kiểm tra giới hạn bằng `Store.MaxNodes` hiện có. Giữ `node_count` đang phục vụ giới hạn và accounting. Không thay bằng policy/config table.
    - If we skip it: cùng một cấu hình triển khai tiếp tục bị lưu thành snapshot riêng trên từng filesystem.

12. **Cleanup dùng bộ đếm để biểu diễn đã từng bắt đầu xóa: 1 cột.**
    - What this is: `object_deletions.attempts` chỉ được tăng và kiểm tra bằng 0 hoặc lớn hơn 0 trong [copy_state.go](../../apps/letfs/internal/filesystem/copy_state.go:114), [maintenance.go](../../apps/letfs/internal/filesystem/maintenance.go:147). Đây không phải số attempt của Temporal.
    - Problem: con số chính xác không được sử dụng; nó đang giữ một sự kiện mà state đã có thể biểu diễn, nhưng các UPSERT hiện lại reset state về pending.
    - Fix: không cho state cleanup quay lại pending sau khi đã bắt đầu xóa; dùng state hiện có để từ chối publish/reuse candidate đó. Bỏ counter, không thêm delete-started flag.
    - If we skip it: tiếp tục lưu hai dạng trạng thái của cùng cleanup lifecycle. Không được bỏ check rồi cho copy publish một object mà cleanup đã nhận xóa.

## Metadata không có consumer hiện tại

Có thêm 8 cột được schema/default hoặc câu UPDATE ghi, nhưng code ứng dụng hiện không đọc/trả/lọc bằng chúng: `account.users.created_at`, `workspace.workspaces.created_at`, `workspace.workspace_invitations.created_at`, `workspace.workspace_members.joined_at`, `letfs.filesystems.created_at`, `letfs.quota_buckets.created_at`, `letfs.uploads.created_at`, `letfs.object_deletions.updated_at`.

Không có yêu cầu audit hiện tại làm cơ sở giữ các cột này. Đề xuất bỏ trong scope hiện tại. Đây là metadata chưa được tiêu thụ, không phải 8 cơ chế phân tán nghiêm trọng. Không gom `nodes.created_at/updated_at`, `trash_entries.created_at`, `uploads.updated_at` hay timestamps phục vụ reconciliation vào nhóm này: chúng có consumer thực tế.

## Những cột có mục đích thật, không đề xuất xóa

- `users.initial_workspace_id`: kết quả onboarding, tránh tạo lại workspace đầu tiên sau khi nó đã bị user xóa. `users.status/updated_at`: trạng thái onboarding và quét admission đang pending.
- `workspaces.quota_bucket_id/filesystem_id/root_id`: reference storage được API hiện tại trả về và workflow sử dụng. `limit_bytes` là policy đã nhận khi tạo storage. `revision` đang dùng cho If-Match, không phải authorization projection revision.
- Membership, invitation role/token/acceptance và expiry phục vụ API đang tồn tại. Riêng `accepted_user_id` chặn dùng lại invitation để thêm lại membership đã bị xóa.
- PK/FK, tree parent/name/kind, byte payload và semantic metadata là dữ liệu ứng dụng. Generation là phiên bản nội dung đang xử lý; không thêm generation hay marker để thay cho idempotency key.
- Bucket usage, node count và lifecycle đang dùng trực tiếp khi tạo, thay, copy, trash/purge và xóa filesystem.
- Upload target/input lưu destination và overwrite precondition trong lúc byte truyền qua S3; actor bảo vệ upload của user; multipart ID/part size/ETag receipts phục vụ S3 thật. `result` giữ kết quả finalize theo upload ID; không tạo bảng finalize receipt thứ hai.
- Source/generation/stage/path trên output là liên kết file đầu ra và bộ kết quả để publish/dọn; chúng không phải lý do giữ custom attempt protocol.
- `object_deletions.ambiguous_write/open_writes` đang theo dõi khả năng object còn được ghi bởi upload/copy; giữ chúng trong review này vì có đường S3 thực tế, không chỉ test. `eligible_at` hẹn dọn sau hạn transfer. Không đánh đồng chúng với retry counter.
- `index_deletions.file_id/generation/eligible_at` giữ mục tiêu dọn vector sau khi source bị xóa. Không giữ lịch sử cấu hình embedding.

## Kết luận và giới hạn

31 cột được đề xuất bỏ/gộp ở các finding trên; thêm 8 metadata không có consumer hiện tại. Mục tiêu sau thay đổi là 111 cột thay vì 150, không thêm bảng/cột thay thế. Đây là đề xuất execution dựa trên luồng, không phải tuyên bố có thể DROP 39 cột mà không sửa caller.

Verdict: sửa các finding trước khi tiếp tục mở rộng schema processing. Chưa triển khai trong lượt review này.

Not checked: chưa chạy migration hoặc fault-injection trên thiết kế đơn giản hóa; chưa sửa schema, code, contracts hay test. Không audit bảng nội bộ của Temporal/SpiceDB vì chúng do dependency quản lý.

## Kiểm kê đầy đủ từng cột

Mỗi cột của cả 14 bảng nằm trong đúng một nhóm dưới đây. “Giữ” có nghĩa có trách nhiệm hiện tại; không phải bảo đảm tên/kiểu/constraint không thay đổi khi gộp luồng.

### account.users (8 cột)

Nguồn: [migration](../../apps/account/migrations/0001_initial.sql:2).

- Giữ: `id`, `clerk_id`, `display_name`, `avatar_url`, `status`, `initial_workspace_id`, `updated_at`.
- Bỏ/gộp theo finding: —.
- Metadata chưa có consumer, đề xuất bỏ: `created_at`.

### workspace.idempotency_keys (9 cột)

Nguồn: [migration](../../apps/workspace/migrations/0001_initial.sql:3).

- Giữ: `actor_id`, `request_key`, `request_hash`, `workspace_id`, `expires_at`.
- Bỏ/gộp theo finding: `operation`, `request_input`, `workflow_id`, `completed_at`.
- Metadata chưa có consumer, đề xuất bỏ: —.

### workspace.workspace_invitations (9 cột)

Nguồn: [migration](../../apps/workspace/migrations/0001_initial.sql:18).

- Giữ: `id`, `workspace_id`, `email`, `role`, `token_hash`, `expires_at`, `status`, `accepted_user_id`.
- Bỏ/gộp theo finding: —.
- Metadata chưa có consumer, đề xuất bỏ: `created_at`.

### workspace.workspace_members (4 cột)

Nguồn: [migration](../../apps/workspace/migrations/0001_initial.sql:35).

- Giữ: `workspace_id`, `user_id`, `role`.
- Bỏ/gộp theo finding: —.
- Metadata chưa có consumer, đề xuất bỏ: `joined_at`.

### workspace.workspaces (12 cột)

Nguồn: [migration](../../apps/workspace/migrations/0001_initial.sql:43).

- Giữ: `id`, `name`, `status`, `quota_bucket_id`, `filesystem_id`, `root_id`, `limit_bytes`, `revision`, `error_code`, `updated_at`.
- Bỏ/gộp theo finding: `creation_workflow_id`.
- Metadata chưa có consumer, đề xuất bỏ: `created_at`.

### letfs.idempotency_keys (7 cột)

Nguồn: [migration](../../apps/letfs/migrations/0001_initial.sql:3).

- Giữ: `scope`, `operation`, `request_key`, `request_hash`, `result`, `expires_at`.
- Bỏ/gộp theo finding: `completed_at`.
- Metadata chưa có consumer, đề xuất bỏ: —.

### letfs.files (26 cột)

Nguồn: [migration](../../apps/letfs/migrations/0001_initial.sql:17).

- Giữ: `node_id`, `media_type`, `title`, `description`, `semantic_type`, `context`, `storage_kind`, `inline_bytes`, `object_key`, `desired_generation`, `processing_format`, `publication_status`, `processing_error`, `processing_updated_at`.
- Bỏ/gộp theo finding: `processing_actor_id`, `processing_source_identity`, `accepted_attempt`, `accepted_attempt_id`, `published_generation`, `parse_manifest_hash`, `publication_manifest_hash`, `index_status`, `indexed_generation`, `embedding_model`, `vector_collection`, `vector_dimension`.
- Metadata chưa có consumer, đề xuất bỏ: —.

### letfs.filesystems (8 cột)

Nguồn: [migration](../../apps/letfs/migrations/0001_initial.sql:54).

- Giữ: `id`, `bucket_id`, `root_id`, `state`, `node_count`.
- Bỏ/gộp theo finding: `create_fingerprint`, `max_nodes`.
- Metadata chưa có consumer, đề xuất bỏ: `created_at`.

### letfs.nodes (9 cột)

Nguồn: [migration](../../apps/letfs/migrations/0001_initial.sql:70).

- Giữ: `id`, `filesystem_id`, `parent_id`, `name`, `kind`, `size_bytes`, `revision`, `created_at`, `updated_at`.
- Bỏ/gộp theo finding: —.
- Metadata chưa có consumer, đề xuất bỏ: —.

### letfs.object_deletions (8 cột)

Nguồn: [migration](../../apps/letfs/migrations/0001_initial.sql:86).

- Giữ: `object_key`, `bucket_id`, `eligible_at`, `state`, `ambiguous_write`, `open_writes`.
- Bỏ/gộp theo finding: `attempts`.
- Metadata chưa có consumer, đề xuất bỏ: `updated_at`.

### letfs.index_deletions (6 cột)

Nguồn: [migration](../../apps/letfs/migrations/0001_initial.sql:98).

- Giữ: `file_id`, `generation`, `eligible_at`.
- Bỏ/gộp theo finding: `embedding_model`, `vector_collection`, `vector_dimension`.
- Metadata chưa có consumer, đề xuất bỏ: —.

### letfs.quota_buckets (7 cột)

Nguồn: [migration](../../apps/letfs/migrations/0001_initial.sql:109).

- Giữ: `id`, `limit_bytes`, `used_bytes`, `state`.
- Bỏ/gộp theo finding: `creator_service`, `create_fingerprint`.
- Metadata chưa có consumer, đề xuất bỏ: `created_at`.

### letfs.trash_entries (8 cột)

Nguồn: [migration](../../apps/letfs/migrations/0001_initial.sql:123).

- Giữ: `id`, `filesystem_id`, `node_id`, `original_parent_id`, `original_name`, `actor_id`, `state`, `created_at`.
- Bỏ/gộp theo finding: —.
- Metadata chưa có consumer, đề xuất bỏ: —.

### letfs.uploads (29 cột)

Nguồn: [migration](../../apps/letfs/migrations/0001_initial.sql:135).

- Giữ: `id`, `filesystem_id`, `bucket_id`, `actor_id`, `input`, `candidate_key`, `state`, `expires_at`, `transfer_deadline`, `inline_bytes`, `result_node_id`, `updated_at`, `transport`, `expected_size`, `content_md5`, `multipart_id`, `part_size`, `completion_parts`, `result`, `processing_file_id`, `processing_generation`, `relative_path`, `processing_stage`.
- Bỏ/gộp theo finding: `size_bytes`, `sha256`, `write_expires_at`, `processing_attempt`, `processing_attempt_id`.
- Metadata chưa có consumer, đề xuất bỏ: `created_at`.
