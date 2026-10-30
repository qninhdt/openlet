# letfs: adjacency list và materialized path

Thời điểm tra cứu: 2026-10-29, bắt đầu lúc 09:42 Asia/Ho_Chi_Minh; nguồn code được đối chiếu lúc 09:44 +07:00.
Trạng thái: khuyến nghị thiết kế, chưa triển khai hoặc benchmark Openlet.

## Kết luận

Giữ adjacency list làm nguồn chính cho MVP: mỗi node có id, filesystem_id, parent_id, name và kind. Resolve path bằng recursive CTE có điều kiện theo từng thành phần, trong một round trip; không dựng toàn bộ cây rồi lọc path.

Đây là lựa chọn phù hợp với các thao tác đã yêu cầu: ID ổn định, rename/move nguyên tử, trash bằng tách gốc cây con và restore bằng gắn lại. Chưa có bằng chứng workload để khẳng định đây là phương án nhanh nhất về latency.

Materialized path bằng tên có lợi cho lookup nguyên path. Materialized path bằng ID có lợi cho truy vấn ancestor/descendant và không phải cập nhật descendants khi chỉ rename. Cả hai đều có chi phí cập nhật descendants khi thay đổi ancestry, nếu cột path phải phản ánh cây hiện tại.

## Outcome và phạm vi

- Outcome: chọn mô hình cây và cách resolve path phù hợp cho letfs.
- Constraints: PostgreSQL; lookup bằng ID và path; không có N+1 round trip; file/directory dùng UUIDv7; filesystem scope rõ ràng; hỗ trợ rename, move, trash, restore.
- Non-goals: viết migration, đổi stack, xây cache hoặc benchmark giả lập rồi coi là số liệu production.
- Acceptance: xác định chính xác chi phí đọc/ghi của từng mô hình, có nguồn triển khai thực tế, chỉ rõ giới hạn bằng chứng và các kiểm chứng cần làm trước khi gọi một phương án là tối ưu.

## Bằng chứng từ triển khai thực tế

### JuiceFS: cạnh parent/name và inode

Tài liệu internals mô tả ánh xạ parentInode, name sang type, inode. Tài liệu tự ghi phạm vi ban đầu là v1.0.0, nên đã đối chiếu thêm code SQL hiện tại.

Trong pkg/meta/sql.go, kiểu edge có Parent và Name với unique index cùng nhóm; Inode được lưu riêng. Đây là triển khai relational metadata engine thực tế, không chỉ ví dụ cây lý thuyết. letfs không cần sao chép cách tách inode/edge vì MVP chưa yêu cầu hard link.

- [Internals](https://juicefs.com/docs/community/internals/#edges)
- [SQL schema được pin theo commit d5d80841103174106923a1a2f26503466140ee8e, dòng 66](https://github.com/juicedata/juicefs/blob/d5d80841103174106923a1a2f26503466140ee8e/pkg/meta/sql.go#L66)
- [Rename cùng phiên bản, dòng 2453](https://github.com/juicedata/juicefs/blob/d5d80841103174106923a1a2f26503466140ee8e/pkg/meta/sql.go#L2453)

Commit cuối tác động file được đọc có ngày 2026-10-27.

### Nextcloud: parent kết hợp path và path_hash

Cache.php lưu cả parent, name, path và path_hash. Khi move directory, code lấy child IDs và cập nhật path/path_hash của descendants theo batch. Đây là ví dụ cho việc materialize đường dẫn bằng tên mang lại truy cập trực tiếp nhưng cần duy trì dữ liệu dư thừa.

Tài liệu quản trị Nextcloud 35 có lệnh files:repair-tree để sửa trường hợp stored path không khớp path suy ra từ parent. Điều này chứng minh có invariant cần bảo vệ; không chứng minh mọi thiết kế hybrid đều không đáng tin cậy.

- [Code được pin theo commit 8dec0db8fc63e5a81f6fd319abde143615d3c082, dòng 789](https://github.com/nextcloud/server/blob/8dec0db8fc63e5a81f6fd319abde143615d3c082/lib/private/Files/Cache/Cache.php#L789)
- [Lệnh repair-tree](https://docs.nextcloud.com/server/stable/admin_manual/occ_files.html#files-repair-tree)

Commit cuối tác động file được đọc có ngày 2026-09-29.

### PostgreSQL 18: recursive query, index và ltree

PostgreSQL hỗ trợ recursive CTE, multicolumn B-tree và ltree với toán tử ancestor/descendant cùng GiST index. Đây là khả năng kỹ thuật, không phải benchmark so sánh hai thiết kế Openlet.

ltree lưu chuỗi label, không phải arbitrary filesystem path. Tên chứa dấu chấm, khoảng trắng hoặc ký tự không hợp lệ cần encoding; có thể dùng chuỗi ID làm label để tránh phụ thuộc tên.

Không nên mặc định full_path text có thể được unique-index với mọi độ dài: B-tree có giới hạn kích thước một entry. Hash path làm key nhỏ hơn nhưng phải xử lý collision và kiểm tra đúng path; không biến hash thành identity duy nhất của file.

- [Recursive CTE](https://www.postgresql.org/docs/18/queries-with.html#QUERIES-WITH-RECURSIVE)
- [Multicolumn index](https://www.postgresql.org/docs/18/indexes-multicolumn.html)
- [ltree definitions và index](https://www.postgresql.org/docs/18/ltree.html)
- [B-tree entry size](https://www.postgresql.org/docs/18/btree.html)

### Benchmark có sẵn và giới hạn suy luận

Tài liệu django-treebeard 7.0.2 có bảng benchmark và mã kiểm chứng. Materialized path/ltree thắng adjacency ở một số phép đo, kể cả một bài move. Vì thế không thể kết luận adjacency luôn nhanh nhất khi ghi chỉ từ số hàng lý thuyết.

Benchmark này đo implementation và workload của thư viện. Nó không đo recursive path resolver của letfs, tải đồng thời, quota hoặc trash. Không áp các con số đó thành dự đoán latency Openlet.

- [Choosing a tree implementation](https://django-treebeard.readthedocs.io/en/latest/choosing.html)

## So sánh và Trade-offs

Gọi d là độ sâu path và S là số node trong cây con.

| Tiêu chí | Adjacency list | Materialized path bằng tên | Materialized path bằng ID |
|---|---|---|---|
| Path tên đến node | Khoảng d lần lookup có index bên trong một query | Một phép lookup nguyên path có index | Vẫn cần resolve tên hoặc một index tên riêng |
| List con trực tiếp | Lookup theo filesystem_id và parent_id | Thường vẫn giữ parent_id hoặc thêm điều kiện depth | Tương tự |
| Rename directory | Không sửa descendants | Sửa path của khoảng S node | Không sửa ID path của descendants |
| Move directory sang parent khác | Không sửa descendants | Sửa path của khoảng S node | Sửa ID path của khoảng S node |
| Truy vấn descendants | Recursive traversal | Prefix/range có index phù hợp | Toán tử ltree có index phù hợp |
| Trash bằng tách root | Không sửa descendants | Rewrite path hoặc thêm cơ chế visibility | Rewrite path hoặc thêm cơ chế visibility |
| Bảo trì | Một cấu trúc cây chính | Đồng bộ parent với full path nếu lưu cả hai | Đồng bộ parent với ancestry path nếu lưu cả hai |

Các số S chỉ mô tả số node cần thay đổi trong mô hình đường dẫn được lưu trực tiếp. Chúng không phải kết quả đo thời gian.

- Adjacency phụ thuộc vào giả định path không quá sâu và truy vấn toàn subtree không chiếm phần lớn tải. Nó chịu áp lực trước ở path rất sâu hoặc đọc subtree liên tục.
- Named materialized path phù hợp khi exact-path lookup chiếm ưu thế và ancestry ít thay đổi. Nó chịu áp lực trước ở rename/move/trash cây lớn, transaction dài, WAL và index churn.
- ID materialized path phù hợp khi đọc quan hệ ancestor/descendant nhiều và move ít. Nó không tự giải quyết lookup path bằng tên, đồng thời vẫn có subtree write amplification khi reparent.

Không gọi move adjacency là O(1) tuyệt đối: còn kiểm tra cycle, live ancestry, quyền, trạng thái đích và khóa chống race. Điểm lợi là không phải sửa mọi descendant.

## Cách triển khai MVP được đề xuất

1. Mỗi node lưu trực tiếp filesystem_id, parent_id, name, kind và ID ổn định.
2. Unique B-tree trên (filesystem_id, parent_id, name), cùng primary key/foreign key phù hợp. Bảo đảm parent thuộc cùng filesystem, là directory; move không được tạo cycle.
3. Resolve từ live root, chỉ lookup tên thành phần tiếp theo ở mỗi vòng recursive CTE. Một query không có nghĩa một lookup, cũng không bảo đảm planner luôn dùng index.
4. List directory theo parent_id với cursor pagination và metadata nhỏ. Nội dung file nằm riêng.
5. Rename/move/trash/restore dùng transaction ngắn và quy tắc khóa thay đổi cấu trúc nhất quán. Không dựng lại full path của cây con.
6. ID-based access vẫn kiểm tra node thuộc live tree; filesystem_id riêng lẻ không chứng minh node chưa bị trash.
7. Không thêm full_path hoặc ltree cùng lúc chỉ để dự phòng. Nếu benchmark chứng minh nhu cầu đọc hierarchy chiếm ưu thế, thêm derived index có thể rebuild và đo cả chi phí duy trì.
8. Cache path chỉ bổ sung sau khi có chiến lược invalidation cho rename/move/trash của ancestor. TTL đơn thuần không bảo đảm path cũ không trả node đã chuyển.

Better approaches: none — chưa có bằng chứng hướng thay thế tốt hơn adjacency cho toàn bộ contract hiện tại; kết luận dựa trên mutation semantics đã yêu cầu và bằng chứng parent/name index trong JuiceFS, không dựa trên một benchmark latency Openlet.

## Kiểm chứng khi có schema chạy được

- Dùng cùng dataset và cùng semantics cho cả phương án, không so hai implementation khác hợp đồng.
- Thử cây rộng và cây sâu; exact lookup hit/miss; list directory; subtree enumeration; rename/move/trash/restore cây lớn.
- Đo p50/p95/p99, số round trip, EXPLAIN (ANALYZE, BUFFERS), rows touched, WAL, index size và lock waits dưới tải đọc/ghi đồng thời.
- Kiểm tra rename/move concurrent không tạo cycle, không trả nhầm path và không lộ cây trash.
- Không mặc định Redis sẽ che được truy vấn kém hoặc chấp nhận stale path khi mutation.
- Chỉ thêm derived path nếu lợi ích đọc vượt chi phí ghi và độ phức tạp giữ nhất quán trong workload mục tiêu.

Không chạy database, migration hoặc benchmark trong lượt nghiên cứu này; không có dữ liệu người dùng bị thay đổi. Chỉ tạo báo cáo nghiên cứu.

## Khoảng trống còn lại

- Chưa pin phiên bản PostgreSQL của ứng dụng; PostgreSQL 18 chỉ là phiên bản tài liệu được đối chiếu.
- Chưa có dataset, phân phối độ sâu, tỷ lệ thao tác hoặc benchmark của Openlet.
- Chưa có bằng chứng để cam kết số millisecond hoặc tốc độ tương đối giữa hai mô hình trên Openlet.
