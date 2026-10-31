# Các hệ thống thực tế lưu trạng thái processing như thế nào?

Tra cứu ngày 2026-10-30, phiên bắt đầu 23:13 Asia/Ho_Chi_Minh. Phạm vi: source code công khai và tài liệu chính thức; không kiểm tra database production của các nhà cung cấp.

## Kết luận

**Có hệ thống dùng Temporal đồng thời vẫn có bảng job riêng của ứng dụng. Airbyte là ví dụ đã xác minh bằng cả schema và activity code. Tuy nhiên không có quy tắc mọi ứng dụng phải có bảng generic operations.** Có hệ thống dùng bảng task, có hệ thống đặt trạng thái indexing ngay trên document.

Bằng chứng này xác nhận các cách làm có tồn tại, không chứng minh thiết kế operations của Openlet là tối ưu, và không tự động chứng minh operation_id cần nằm trong Qdrant payload.

## Bằng chứng

### Airbyte: Temporal cộng bảng jobs/attempts

Snapshot source: airbytehq/airbyte-platform, commit ad8dac4ce0caa9f1c0a71a6dccd22d160c2274c3, nhánh main khi tra cứu.

- [Schema ứng dụng](https://github.com/airbytehq/airbyte-platform/blob/ad8dac4ce0caa9f1c0a71a6dccd22d160c2274c3/airbyte-db/db-lib/src/main/resources/jobs_database/schema.sql#L37) tạo bảng JOBS có config, scope, status và timestamps; ATTEMPTS có job_id, attempt_number, output, status và timestamps.
- [Temporal activity](https://github.com/airbytehq/airbyte-platform/blob/ad8dac4ce0caa9f1c0a71a6dccd22d160c2274c3/airbyte-workers/src/main/kotlin/io/airbyte/workers/temporal/scheduling/activities/JobCreationAndStatusUpdateActivityImpl.kt#L69) gọi jobs API để tạo job và nhận job ID.
- [Application helper](https://github.com/airbytehq/airbyte-platform/blob/ad8dac4ce0caa9f1c0a71a6dccd22d160c2274c3/airbyte-commons-server/src/main/kotlin/io/airbyte/commons/server/handlers/helpers/JobCreationAndStatusUpdateHelper.kt#L49) dùng JobPersistence để đọc và cập nhật job/attempt; [implementation](https://github.com/airbytehq/airbyte-platform/blob/ad8dac4ce0caa9f1c0a71a6dccd22d160c2274c3/airbyte-persistence/job-persistence/src/main/kotlin/io/airbyte/persistence/job/DefaultJobPersistence.kt#L73) sở hữu thao tác jobs database.

Đây là dữ liệu ứng dụng về sync jobs và attempts, không phải các bảng persistence nội bộ của Temporal. Không nên sao chép bảng attempts của Airbyte vào Openlet chỉ vì cùng dùng Temporal.

### Paperless-ngx: bảng task phục vụ document processing

Snapshot source: paperless-ngx/paperless-ngx, commit 80a1827fa0ef168cf610afee3c5ee0df51787415, nhánh dev khi tra cứu; không khẳng định schema này đã có trong mọi bản release đã deploy.

- [PaperlessTask model](https://github.com/paperless-ngx/paperless-ngx/blob/80a1827fa0ef168cf610afee3c5ee0df51787415/src/documents/models.py#L788) ghi rõ mục đích theo dõi background tasks để người dùng xem và debug. Model có Celery task ID, status và task type; các type gồm consume file, reprocess document và index optimize.
- [Migration](https://github.com/paperless-ngx/paperless-ngx/blob/80a1827fa0ef168cf610afee3c5ee0df51787415/src/documents/migrations/0019_task_system_redesign.py#L21) thực sự tạo model/table này, không chỉ là DTO của API.

Đây là ví dụ hệ thống tài liệu có bảng task riêng. Nó dùng Celery ở đường xử lý này, không phải bằng chứng về yêu cầu của Temporal.

### Dify: trạng thái indexing trên document

Snapshot source: langgenius/dify, commit 0c82953c625acd661188f74996f838f73217d1f1, nhánh main khi tra cứu.

- [Document model](https://github.com/langgenius/dify/blob/0c82953c625acd661188f74996f838f73217d1f1/api/models/dataset.py#L374) ánh xạ bảng documents, chứa processing_started_at, parsing/cleaning/splitting completion times, completed_at, error và indexing_status.
- [Indexing task](https://github.com/langgenius/dify/blob/0c82953c625acd661188f74996f838f73217d1f1/api/tasks/document_indexing_task.py#L34) chạy qua Celery và cập nhật trạng thái trên document trước/sau xử lý.

Đường xử lý được kiểm tra dùng document làm nơi sở hữu trạng thái. Điều này không chứng minh toàn repository Dify không có bất kỳ bảng job nào khác.

## Temporal đã sở hữu phần nào?

[Tài liệu persistence chính thức](https://github.com/temporalio/documentation/blob/main/docs/encyclopedia/temporal-service/persistence.mdx) mô tả Temporal tự lưu workflow state, event history và tasks. Có thể xem workflow status bằng API/CLI. [Retention](https://github.com/temporalio/documentation/blob/main/docs/encyclopedia/temporal-service/temporal-server.mdx) áp dụng cho dữ liệu workflow đã đóng; sau thời hạn cấu hình, dữ liệu được cleanup.

Suy ra: không cần tạo bảng ứng dụng chỉ để thực hiện lại việc giữ program counter, retry timer hoặc event history của Temporal. Nếu sản phẩm cần dữ liệu trạng thái bền lâu, truy vấn/join theo tài liệu, kết quả nghiệp vụ hoặc ownership của outputs, ứng dụng có thể lưu phần đó trong DB riêng. Nơi lưu có thể là bảng jobs/operations hoặc fields trên document.

## Áp dụng cho Openlet

Cập nhật kết luận ngày 2026-10-31: [kế hoạch filesystem core ban đầu](../261029-1220-openlet-backend-mvp/phase-03-filesystem-core.md) ghi rõ bảng operations được tạo cho scoped direct inline-copy keys/fingerprints/result IDs. Mục đích gốc là idempotency của synchronous inline copy trong transaction SQL; durable copy và processing tái dùng sau. Hướng phase 2 đã chốt là giữ bảng hiện có và tái dùng operation_id để phân biệt index của job cũ, còn Temporal điều phối và retry. Các đoạn dưới phản ánh phạm vi nghiên cứu ban đầu.

- Bảng [operations](../../services/letfs/migrations/0002_file_core.sql) đã có; [processing intent và invalidation](../../services/letfs/src/fs/artifacts.rs) dùng nó gắn job với source, supersede job cũ và cung cấp status.
- [Publication](../../services/letfs/src/fs/processing.rs) và [data model](../../docs/data-model.md) còn dùng quan hệ operation cho outputs/accounting; vì vậy bảng hiện tại không chỉ là bản sao của workflow status.
- Chưa có căn cứ để xóa bảng hiện tại trong brainstorm phase 2; cũng chưa có căn cứ để mở rộng thành một hệ thống job/attempt phức tạp hơn.
- Việc thêm operation_id vào Qdrant là quyết định khác: cần chỉ ra invariant chống index cũ cụ thể và cân nhắc với source/content identity có sẵn. Các ví dụ trên không xác nhận cách đặt payload đó.

**Hướng tiếp theo:** giữ nguyên implementation hiện tại trong phiên nghiên cứu; trước khi chốt phase 2, tách rõ trạng thái Temporal sở hữu, metadata processing mà letfs cần và dữ liệu Qdrant thực sự cần. Không thêm bảng/lock/attempt ledger dựa trên tiền lệ chung.

## Giới hạn và câu hỏi còn mở

Web search connector trả lỗi không kèm chi tiết. Nghiên cứu dùng Context7 và đọc trực tiếp source GitHub của các dự án; không truy cập production databases, không chạy các hệ thống, không sửa application code/schema/data. Chưa kết luận operation_id là field bắt buộc của index Openlet.
