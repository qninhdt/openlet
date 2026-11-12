# Role nằm ở PostgreSQL hay SpiceDB?

Ngày tra cứu: 2026-11-11. Nguồn là tài liệu/blog chính thức Authzed; chưa benchmark Openlet. Cập nhật quyết định: người dùng đã chọn A và chốt kiến trúc sau khi đọc so sánh; B dưới đây là phương án đã xem xét, không active schema.

## Kết quả tra cứu

Authzed hỗ trợ cả lưu relationships chỉ trong SpiceDB lẫn cập nhật từ application database. SpiceDB-only là một lựa chọn, không quy định bắt buộc. Ứng dụng chịu trách nhiệm cập nhật relationships phản ánh dữ liệu của mình. [Relationships](https://authzed.com/docs/spicedb/concepts/relationships).

UI có thể đọc role assignments bằng ReadRelationships. Tài liệu access-control management có ví dụ role_reader/role_writer/role_adminer, phù hợp ba role cố định của Openlet. Không cần CheckPermission từng user để đoán role; inherited permission không đồng nghĩa assigned role. [Access-Control Management](https://authzed.com/docs/spicedb/modeling/access-control-management).

ReadRelationships không dùng cache của Check/Lookup và đi xuống datastore; nó linh hoạt nhưng có thể kém tối ưu nếu filter không hợp index. Tuy vậy admin UI hiển thị roles là use case được nêu rõ. Check/CheckBulk vẫn là API cho authorization hot path. [Querying Data](https://authzed.com/docs/spicedb/concepts/querying-data).

Authzed lưu ý SpiceDB làm nguồn phù hợp nhất với relationships hiện diện/vắng mặt; sort/filter/paginate dữ liệu UI có thuộc tính sẽ khó hơn database thông thường. Bài viết trình bày durable execution và transactional outbox như các cách xử lý dual-write, không hứa có cách vừa atomically ghi hai hệ thống vừa không có chi phí. [The Dual-Write Problem](https://authzed.com/blog/the-dual-write-problem).

Tài liệu cũng mô tả two-writes-and-commit: gọi SpiceDB trong SQL transaction rồi commit và compensation khi lỗi. Đây không phải distributed atomic transaction. Nó giữ transaction qua network và không phù hợp mục tiêu bỏ long-held locks của Openlet. Async sync có replication lag; fully_consistent chỉ thấy latest SpiceDB, không tự đọc thay đổi SQL chưa replicate. [Relationships: writing strategies](https://authzed.com/docs/spicedb/concepts/relationships#two-writes--commit).

List resource details vẫn phải ghép dữ liệu ứng dụng với authorization: native LookupResources rồi batch SQL, hoặc SQL candidates rồi CheckBulkPermissions. Không có lý do gọi một graph check/SQL query cho mỗi item. [Protecting a List Endpoint](https://authzed.com/docs/spicedb/modeling/protecting-a-list-endpoint).

## Hai phương án hợp lệ cho Openlet

| | A: role canonical ở SpiceDB | B: role canonical ở PostgreSQL |
|---|---|---|
| Role assignments | workspace owner/admin/member relations | Một role column trong membership/mapping |
| UI ListMembers | Một ReadRelationships page + một SQL profiles batch | Một SQL join membership/users |
| Check quyền LetFS/Leta | Check/CheckBulk ở SpiceDB | Check/CheckBulk ở SpiceDB projection |
| Membership write | Một graph write; scope mapping SQL không mirror role | SQL mutation + graph propagation |
| Sort/filter/count member theo dữ liệu business | Ghép graph IDs với SQL; hạn chế pagination/sort cross-system | SQL tự nhiên hơn |
| Failure cần xử lý | Mapping có thể tồn tại trước grant, chưa tạo quyền | SQL/graph có thể lệch kể cả revoke; phải định nghĩa propagation/recovery |
| Recovery authority | Backup SpiceDB | Rebuild được membership projection từ SQL; pure graph grants vẫn phải backup |

### Nếu chọn B, schema nhỏ nhất

Thay member_scopes bằng một bảng duy nhất, không giữ hai bản mapping:

```text
workspace_members
  workspace_id
  user_id
  personal_scope_id
  role NULL | owner | admin | member
  PRIMARY KEY (workspace_id,user_id)
```

role NULL nghĩa là không còn membership, nhưng personal scope vẫn giữ để rejoin. Không cần active/status/removed_at/graph_synced flags. UI query `role IS NOT NULL` rồi JOIN users. Owner immutable; role replacement/removal thay một row.

B không cần mirror mọi computed permission vào SQL. Tuy nhiên phải xác định riêng direct scope grants nằm ở đâu; role SQL không tự khôi phục toàn bộ graph. Không được gọi SpiceDB là cache vứt bỏ được nếu grants khác chỉ tồn tại ở đó.

Chưa thiết kế một framework đồng bộ cho B vì người dùng đang yêu cầu nghiên cứu lựa chọn, không yêu cầu dựng thêm queue/outbox/coordinator. Nếu chọn B, propagation phải được chốt trước implementation; không viết hai lệnh nối nhau rồi tuyên bố exactly-once. Native Temporal giúp durable retries, không tự cung cấp cross-store atomicity hoặc thứ tự mọi concurrent grant/revoke.

## Khuyến nghị và trạng thái quyết định

Khuyến nghị hiện tại của assistant: A cho MVP ba role cố định, member cap khoảng 100 và mục tiêu giảm cơ chế sync. UI vẫn render role rõ ràng. Không khẳng định nó nhanh hơn SQL; ReadRelationships thêm graph/datastore work và cần đo.

Nếu yêu cầu sản phẩm là membership có thuộc tính business, SQL sorting/filtering/reporting hoặc SQL phải là authority, B phù hợp và lời người dùng về PostgreSQL là hoàn toàn hợp lệ. Chi phí propagation là trade-off thật, không phải lý do cấm B.

Người dùng đã chọn A: canonical role/grants ở SpiceDB, SQL chỉ giữ personal mapping/profile. Final proposal/schema/query plan dùng A làm thiết kế implementation; không còn A/B approval blocker. Trade-off UI sort/filter và yêu cầu backup SpiceDB vẫn giữ như phân tích phía trên.
