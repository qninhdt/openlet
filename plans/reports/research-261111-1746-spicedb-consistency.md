# SpiceDB consistency cho kiến trúc viết lại

Ngày tra cứu: 2026-11-11. Chỉ tra tài liệu; chưa benchmark deployment Openlet.

## Kết quả từ nguồn chính thức

- [Consistency](https://authzed.com/docs/spicedb/concepts/consistency): read APIs mặc định `minimize_latency`; relationship writes/deletes mặc định fully consistent. Full consistency chọn snapshot mới nhất lúc request bắt đầu và bỏ qua khả năng cache của consistency path này; không làm request theo dõi các writes xảy ra sau đó.
- [Load testing](https://authzed.com/docs/spicedb/ops/load-testing#spicedb-consistency-performance): Authzed cho biết đa số người dùng dùng minimize latency, và khuyên dùng at-least-as-fresh thay cho fully-consistent khi cần giữ caching an toàn. Cache subproblems giúp tránh cả tính toán và datastore roundtrips.
- [Read-after-write](https://authzed.com/docs/spicedb/concepts/read-after-write): capture write ZedToken và dùng `at_least_as_fresh` khi cần thấy vừa ghi. Default revision quantization là 5 giây; staleness còn chịu ảnh hưởng max-staleness percentage và follower delay nếu có. Không được biến con số đó thành SLA revoke chính xác 5 giây.
- [PostgreSQL driver v1.57.0](https://pkg.go.dev/github.com/authzed/spicedb@v1.57.0/internal/datastore/postgres): revision quantization default 5 giây, phù hợp phiên bản SpiceDB đang pin ở repository.

Đây là nhận định được nhà cung cấp công bố, không phải telemetry về tỷ lệ sử dụng ngoài thực tế do Openlet tự đo.

## Diễn giải

Fully consistent không có nghĩa là application tự chạy một polling loop vào database. Mỗi authorization RPC chọn revision mới và đánh đổi cache reuse để lấy độ mới. Với hot paths gọi nhiều lần, datastore work tăng; số SQL cụ thể phụ thuộc schema, driver và cache, không phải luôn đúng một query mỗi Check.

Minimize latency vẫn là RPC tới SpiceDB và vẫn có thể đọc datastore khi cache miss. Nó không có nghĩa mọi check chỉ nằm trong RAM.

At-least-as-fresh chỉ đảm bảo độ mới so với token được cung cấp. Token trả về cho người vừa grant không làm những caller khác, không có token, lập tức thấy revoke. Không hứa global immediate revocation bằng một optional client token.

## Đề xuất cho Openlet

| Luồng | Consistency |
|---|---|
| Metadata/content reads, listing, search, VFS reads | `minimize_latency` |
| Read ngay sau thay đổi quyền có write token | `at_least_as_fresh(token)` |
| Admission cho content mutation, purge, membership/ACL change, delete workspace | `fully_consistent`, một lần mỗi admission |
| WriteRelationships/DeleteRelationships | Native write semantics |

Graph write trả token; boundary có thể chuyển token cho read kế tiếp bằng optional gRPC metadata / response field. Không bảng token mirror, distributed invalidation hoặc local permission cache. Platform membership inventory dùng graph reads; sau mutation dùng token nếu cần current view.

Trade-off đề xuất: ordinary reads có thể thấy quyền cũ trong cửa sổ staleness. Không có local TTL cộng thêm. Mutation admissions kiểm tra quyền mới hơn. Nếu sản phẩm yêu cầu revoke chặn ngay mọi content read, phải chọn fully-consistent cho content admission hoặc thiết kế durable freshness propagation; không thể hứa điều đó với minimize-latency đơn thuần.

Giữ native quantization mặc định trước; đo representative checks trên phiên bản pin rồi mới chỉnh. Không chọn interval nhỏ chỉ từ suy đoán.
