# Filesystem API và ranh giới phân quyền

Ngày tra cứu: 2026-11-01, Asia/Saigon. Trạng thái: nghiên cứu để user review, chưa chốt thay đổi kiến trúc hoặc triển khai.

**Đã thay thế về hướng đề xuất:** User mở rộng scope sang redesign toàn hệ thống và không chọn giữ domain file facade làm kiến trúc lâu dài. Xem [nghiên cứu filesystem platform](research-261101-2337-filesystem-platform-redesign.md). Bằng chứng pattern bên dưới vẫn hữu ích; khuyến nghị giữ facade thuộc phạm vi cũ.

## Kết luận

Bài toán đã có các pattern: domain/backend làm authorization facade; external authorization tách nơi quyết định quyền và nơi thực thi; scoped access credentials theo Valet Key/delegation. Không có bằng chứng rằng callback từ storage về domain luôn là boundary leak hoặc luôn là phương án tốt nhất.

Đề xuất trước về letfs tra owner rồi callback Workspace/Leti chưa được user chấp nhận. Không giữ nó làm mặc định cho implementation plan. Với hiện trạng repo và yêu cầu quyền hiện tại, hướng ưu tiên là giữ domain authorization facade, chuẩn hóa contract filesystem và thu mỏng forwarding. Chỉ chuyển kiểm tra quyền sang gateway khi lợi ích cụ thể đủ bù chi phí tích hợp.

## Phạm vi và tiêu chí

Outcome: Workspace, Leti và chủ sở hữu filesystem tương lai dùng một contract file, không lặp nghiệp vụ storage, còn mỗi domain quyết định quyền của mình. Constraints: Go Workspace, Rust letfs, Python Leti; tái sử dụng Envoy và signed object transfers; không đồng bộ membership/ACL thành nhiều nguồn sự thật; không đổi ngầm semantics thu hồi quyền. Non-goals: triển khai personal filesystem, thêm authorization platform hoặc tự thiết kế token protocol ngay trong brainstorm.

Acceptance cho hướng được chọn: storage không chứa role/conversation logic; mọi đường browser/worker kiểm tra đúng actor/resource/action; upload completion không vượt quyền; hợp đồng revision/idempotency/lifecycle giữ nguyên; auth service outage không cấp quyền; signed URL lifetime được phân biệt với quyền API.

## Hiện trạng đã kiểm tra

- [Workspace node handlers](../../apps/workspace/internal/http/nodes.go) vừa authorize role/storage mapping, vừa dựng lại DTO/scope cho từng thao tác. [Upload handlers](../../apps/workspace/internal/http/uploads.go) cũng làm cả hai. Đây là phần duplication có thể giảm; CRUD/quota/processing thật vẫn ở letfs.
- [letfs authentication](../../apps/letfs/src/http/mod.rs) hiện nhận private service credential, phân biệt processing với Workspace. Nó chưa có browser-facing generic filesystem API, owner callback hoặc scoped filesystem access token.
- [Architecture](../../docs/architecture.md) đặt membership/role ở Workspace, tree/storage/lifecycle ở letfs. Revocation chặn admission tiếp theo, không bảo đảm thu hồi request đang chạy. File bytes đi trực tiếp qua signed URLs, không qua proxy toàn bộ payload.
- [Envoy config](../../infra/config/envoy.template.json) có JWT authentication; chưa bật `ext_authz`. [Compose](../../infra/compose/dev.yaml) pin Envoy 1.37.0. Contract được sở hữu ở [public OpenAPI](../../contracts/public/openapi.yaml) và [internal OpenAPI](../../contracts/internal/openapi.yaml).

## Pattern đã có và giới hạn áp dụng

| Pattern, nguồn chính thức | Bằng chứng | Hệ quả cho Leti/letfs |
|---|---|---|
| External authorization: [MinIO AIStor](https://docs.min.io/aistor/administration/iam/access/plugin-access/) | Storage có thể gọi webhook quyết định ALLOW/DENY theo request. | Callback là pattern thật. Nó tạo phụ thuộc latency/availability; không tự giải quyết resource ownership hoặc routing tới nhiều domain. |
| Gateway external authorization: [Envoy 1.37.0](https://www.envoyproxy.io/docs/envoy/v1.37.0/configuration/http/http_filters/ext_authz_filter), [API](https://www.envoyproxy.io/docs/envoy/v1.37.0/api-v3/extensions/filters/http/ext_authz/v3/ext_authz.proto) | Filter gọi HTTP/gRPC auth service, chuyển metadata tới upstream; phiên bản pin có per-route backend override. | Có thể đặt enforcement trước letfs bằng gateway sẵn có. Mapping domain/action và bao phủ worker vẫn là integration cần thiết, không chỉ bật một flag. |
| Valet Key: [Azure Architecture Center](https://learn.microsoft.com/en-us/azure/architecture/patterns/valet-key) | Backend authorize rồi cấp quyền giới hạn resource/operation/time cho client truy cập storage. | Repo đã dùng ý tưởng này cho object bytes. Áp dụng thêm cho toàn bộ API metadata của letfs là thay đổi contract mới. |
| Scoped credentials: [S3 GetDataAccess](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-grants-credentials.html), [R2 temporary credentials](https://developers.cloudflare.com/r2/api/s3/temporary-credentials/) | Các hệ thống thật cấp credential tạm thời, giới hạn target và permissions. | Credential này chỉ bảo vệ S3 operations. Không tự thực thi được quota, revisions, artifact immutability, logical trash hoặc letfs metadata publication. |
| Delegation protocol: [RFC 8693](https://www.rfc-editor.org/rfc/rfc8693.html) | OAuth token exchange có audience/resource/scope và delegation semantics. | Có chuẩn để tham khảo nếu cần token delegation. RFC không định nghĩa letfs permission model, cũng không chứng minh auth stack đang có hỗ trợ token exchange. |

Đây là bằng chứng về pattern, không phải tuyên bố có sản phẩm cắm vào thay toàn bộ filesystem contract của Openlet.

## Boundary leak và phụ thuộc vận hành

Storage tự biết Viewer/Editor, bot owner hoặc conversation participants là trộn nghiệp vụ vào storage. Storage phụ thuộc một contract generic actor/resource/action để thực thi quyền có thể là external authorization hợp lệ. Tuy nhiên, việc storage phải biết từng domain service và callback chúng trên hot path làm tăng phụ thuộc vận hành và routing responsibility. Hai nhận xét này không đồng nghĩa.

Đề xuất trước trộn hai quyết định chưa được chứng minh: chuyển toàn bộ API public sang letfs, và để letfs sở hữu routing tới từng domain authority. Nên đánh giá riêng, không lấy mục tiêu giảm code proxy làm lý do mặc định cho cả hai.

## Các hướng khả thi

| Hướng | Giả định quan trọng | Điểm hỏng đầu tiên | Đánh giá |
|---|---|---|---|
| Domain authorization facade mỏng, cùng filesystem contract | Domain resolve actor/resource/action và forward scope đáng tin cậy; DTO/storage validation có một owner ở letfs. | Facade tiếp tục tích lũy chuyển đổi DTO/logic cho từng endpoint như hiện tại. | Ưu tiên hiện tại: ít thay đổi boundary và không làm yếu revocation semantics. Một forwarder nhỏ mỗi runtime vẫn là duplication vận chuyển có chủ đích. |
| Envoy `ext_authz`, domain giữ policy, letfs xử lý file | Mọi public request và delegated worker request được enforce đúng, metadata không bị giả mạo hoặc lệch route. | Bypass qua route/internal path, operation mapping thiếu hoặc owner outage. | Candidate nếu mục tiêu là bỏ toàn bộ forwarding ở app services; cần spike trước khi chốt. |
| Scoped access grant cho client/worker | Quyền có thể được chụp trong thời hạn grant hoặc có revocation mechanism đã định nghĩa. | User mất quyền nhưng credential vẫn được chấp nhận; issuer cấp vượt phạm vi. | Candidate nếu user chấp nhận semantics đó. Không tự chọn thay yêu cầu quyền hiện tại. Không tự viết crypto hoặc coi JWT là đủ cho authorization. |

Direct callback từ letfs tới generic PDP cũng khả thi theo pattern external authorization. Chưa có bằng chứng nó tốt hơn facade/gateway cho repo này; không chọn làm mặc định.

Better approaches: với yêu cầu KISS hiện tại, chuẩn hóa contract và thu mỏng facade tốt hơn việc mặc định thêm owner-aware callbacks vào letfs. Delta là giữ dependency nghiệp vụ ở domain và không thêm issuer/token lifecycle. Chi phí là refactor phần DTO/operation mapping đang rải trong Workspace; Go/Python vẫn cần transport adapter nhỏ, không có shared handler library xuyên ngôn ngữ.

## Hướng đề xuất để review

1. Giữ một owner cho contract và nghiệp vụ filesystem ở letfs. Public/domain routes có thể khác prefix nhưng dùng cùng operations, schema, lỗi, revision và idempotency. Thống nhất contract không bắt buộc một URL toàn cục.
2. Domain chỉ resolve identity/resource, quyết định allowed action và chuyển authorized scope bằng đường nội bộ được authenticate. letfs vẫn enforce scope và invariants tại operation boundary. Không cho body/header client tự nâng scope.
3. Giảm handler-specific request rebuilding; schema/code generation có thể giúp client/DTO Go/Python, nhưng không coi SDK là lời giải đầy đủ nếu facade vẫn chuyển đổi từng thao tác. Chi tiết forwarder/header/envelope phải review cùng contract trước triển khai.
4. Giữ signed upload/download hiện có cho bytes. Quyền finalize/publication vẫn được kiểm tra; credential storage không phải quyền gọi API letfs.
5. Nếu cần bỏ app forwarding, thử Envoy external authorization ở một thao tác đọc và một upload lifecycle trước, không xây gateway mới. Phải kiểm tra cả delegated actor của Temporal worker và revocation, không chỉ browser happy path.

## Kiểm tra phiên bản và rủi ro cụ thể

Đã đọc docs đúng Envoy 1.37.0 thay vì chỉ dựa `latest`. Chưa chạy config hoặc benchmark. Nếu chọn `ext_authz`, pin hiện tại cần được đối chiếu và cập nhật các bản vá phù hợp trước khi bật tính năng: [GHSA-mvh9-767w-x47j](https://github.com/envoyproxy/envoy/security/advisories/GHSA-mvh9-767w-x47j) liệt kê bản vá nhánh 1.37 là 1.37.5 cho lỗi per-route overrides; [GHSA-q8wp-gf7q-m8cv](https://github.com/envoyproxy/envoy/security/advisories/GHSA-q8wp-gf7q-m8cv) liệt kê 1.37.6 cho lỗi HTTP auth client. Đây là điều kiện của candidate mới, không tuyên bố config hiện tại đang kích hoạt các đường lỗi đó hoặc các bản vá ấy đã đủ cho mọi advisory.

Docs Envoy còn nêu route-cache mutation có thể làm bypass per-route authorization. Review route normalization/rewrite, trusted headers, failure-closed và internal route access là bắt buộc nếu chọn gateway enforcement. Không cần mở rộng thành security audit toàn repo trong nghiên cứu này.

## Bước tiếp theo và câu hỏi còn mở

User review hướng giữ facade mỏng hay thử gateway enforcement; chưa thay architecture authority hoặc tạo implementation plan cho phương án chưa được chọn. Nếu chọn facade, làm rõ contract chung trước khi Leti thêm file handlers. Nếu chọn gateway, chạy spike đúng các boundary ở trên.

Câu hỏi còn mở: mức thống nhất mong muốn là một contract/client dùng chung hay bắt buộc một global filesystem URL; và chi tiết đường delegation cho worker nếu bỏ facade. Scoped grants chỉ cần đưa ra quyết định nếu user muốn đánh đổi per-request permission check lấy access session có thời hạn.
