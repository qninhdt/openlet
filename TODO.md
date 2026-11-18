# Openlet — hoàn thiện sản phẩm

Cập nhật: 2026-11-18. Còn **36 mục** sau khi bỏ A04/A05/A06 theo yêu cầu; giữ nguyên ID, không khôi phục A21–A30 đã bỏ.

Đã triển khai frontend/backend cho các mục dưới đây. **25 mục đã đóng bằng kiểm thử phù hợp; 11 mục còn mở để hoàn tất xác nhận trên hệ thống thật hoặc xử lý giới hạn được ghi ngay tại mục đó.** Checkbox mở không có nghĩa là chưa viết code. Checkbox đóng cũng không có nghĩa là đã deploy.

`P1`: luồng sử dụng chính. `P2`: hoàn thiện trải nghiệm. Các điểm cần kiểm tra bên trong mỗi mục là tiêu chí nghiệm thu, không được tính thành tính năng bổ sung mới.

## 1. Yêu cầu ban đầu

- [x] **U01 · P2 · FE — Workspace picker.** Menu workspace nằm trong dropdown avatar ở đáy rail, theo vị trí/menu/submenu OpenBot. Click chuyển workspace, submenu mở Workspace settings; không có selector đầu sidebar hoặc trang danh sách riêng. `/workspaces` đi vào workspace hiện có hoặc form tạo workspace trong dashboard.
- [x] **U02 · P2 · FE — Account dropdown.** Dropdown avatar chứa danh sách workspace, New workspace, Workspace settings, Your profile, Your settings và Sign out. Dùng avatar bot, primitive dashboard, menu mở sang phải ở đáy rail.
- [x] **U03 · P1 · FE/BE — Account profile manager.** Sửa display name và chọn avatar bằng bộ bot avatar hiện có. Platform lưu appearance có validation; profile thay đổi cập nhật identity và danh sách thành viên. Kiểm thử SQL xác nhận lưu/reload, trim tên, từ chối avatar sai và không sửa tài khoản khác.
- [ ] **U04 · P1 · FE/BE — Workspace settings.** Đã có đổi tên, thành viên, mời/thu hồi lời mời, đổi vai trò/xóa thành viên, chuyển owner và rời workspace; UI tuân theo capability. Browser đã xác nhận đổi tên và layout dashboard desktop/mobile. **Còn:** chạy luồng mời → tham gia → đổi quyền → thu hồi bằng nhiều tài khoản thật, gồm owner cuối cùng và invitation hết hạn.
- [x] **U05 · P1 · FE/BE — Account settings và lưu bền.** Platform lưu preferences JSONB; PATCH chỉ merge trường được gửi, kể cả giá trị `false`. Theme, send shortcut, agent steps, compact actions và message sound nối vào caller thật; layout theo thiết bị vẫn lưu cục bộ. Theme chỉ chỉnh trong Appearance; không có nút theme trên rail. SQL test xác nhận patch không ghi đè preference khác và dữ liệu riêng không lọt vào BatchGetUsers.
- [ ] **U06 · P1 · FE/Auth — Logout.** Đã nối Clerk signOut, hủy fetch/SSE, dọn query cache, consistency token, draft và upload metadata của account; về `/login`. UI xác nhận discard khi còn draft/file chưa lưu. Kiểm thử helper đã xác nhận dọn đúng account. **Còn:** E2E Clerk thực tế, Back/reload sau sign out, session hết hạn và đổi tài khoản.
- [x] **U07 · P2 · FE — Context menu.** Agent/pin chỉ có menu chuột phải Pin/Unpin và Move to; bỏ nút ba chấm, Open chat/Activity/Overview/Settings và Move left/right. Folder giữ thao tác quản lý riêng; vùng trống giữ New agent/New folder theo quyền. Tất cả sửa/xóa agent nằm trong Overview.
- [ ] **U08 · P1 · FE/BE — Xóa agent.** Đã nối DELETE, capability `can_delete`, xác nhận hậu quả, trạng thái chờ/lỗi, dọn draft/pin và loại agent khỏi cache trước khi điều hướng. **Còn:** xóa thật bằng owner/workspace owner/operator, xóa agent cuối cùng và kiểm tra lifecycle cleanup; demo không giả lập xóa tài nguyên thật.
- [x] **U09 · P2 · FE — Bỏ Move left / Move right trên pin.** Đã bỏ hai option; giữ drag & drop và Alt+ArrowLeft/Right qua cùng đường lưu organization. Browser xác nhận menu không còn các option đó và pin/unpin hoạt động. **Giới hạn QA:** native HTML drag trên thiết bị cảm ứng chưa được xác nhận.
- [x] **U10 · P1 · FE/BE — Image preview.** Thumbnail đọc remote node qua ReadImage, viewer đọc qua adapter download; cache tách account/storage/node/version, quản lý object URL và trạng thái lỗi. Browser đã xác nhận thumbnail PNG qua adapter remote và mở ảnh từ file mention trong chat; kiểm tra `naturalWidth`, không chỉ thấy thẻ img. CORS/URL hết hạn trên installation thật vẫn cần smoke test khi deploy.
- [x] **U11 · P2 · FE — Preview các loại file text.** Phân loại MIME/extension dùng chung upload/viewer, mở source với CodeMirror và grammar có sẵn. Giới hạn 1 MB, giữ UTF-8/BOM/CRLF, từ chối nội dung binary và có download fallback. Adapter tests đã kiểm tra encoding, newline và dữ liệu không phải text.
- [x] **U12 · P2 · FE — Sidebar preview không lộ Markdown.** Thành phần MessagePreview dùng chung cho agent sidebar, Inbox và tool preview; chuyển Markdown thành text và file token thành nhãn. Browser đã kiểm tra Inbox không còn raw `:file[` sau khi gửi mention.
- [x] **U13 · P1 · FE/BE — File mention trong message/Activity.** Parser/renderer chung cho chat, Activity, Inbox và inbox_send. File token nguyên vẹn trong inline code cũng trở thành chip; fenced code vẫn giữ literal. Metadata file_refs đi qua snapshots; browser kiểm tra mention trong inline code, mở file và attachment Activity.
- [x] **U14 · P2 · FE — Sound effect message.** Âm gửi chỉ phát sau API thành công; âm nhận theo reply ID mới của mọi agent trong workspace đang chọn. Web Audio tạo âm ngắn với âm lượng cố định, có setting bật/tắt; unlock sau tương tác. Dedupe ID + Web Locks tránh poll/reconnect/nhiều tab phát lại; hydration và pagination im lặng. Demo nhúng landing im lặng. Có kiểm thử lọc lịch sử và browser kiểm tra oscillator/dedupe; chưa nghe trực tiếp trên thiết bị thật, không theo dõi workspace khác đang đóng.
- [x] **U15 · P2 · FE/BE — Agent read receipt.** Icon dưới góc phải bubble chỉ hiện cho message user cuối toàn hội thoại, dùng read_at của chính message. Ẩn ngay khi có message user/agent mới, kể cả đang xem permalink cũ. Sending/failed vẫn có trạng thái riêng. SQL/private chat và browser kiểm tra ranh giới người nhận, nhiều message và agent trả lời.
- [ ] **U16 · P1 · FE/BE — Agent đang xử lý/đang viết.** Đã nối run/heartbeat/stream vào chat, Activity, avatar và Stop; private `/processing` chỉ cho operator thấy trạng thái coarse của root run đang xử lý message của họ, không lộ reasoning/tool của người khác. **Còn giới hạn thật:** root kết thúc nhưng Leti tiếp tục công việc được giao thì operator chưa có tín hiệu liên kết chính xác. Schema hiện chưa có quan hệ parent-run/task để quy công việc con về message người gửi; không dùng mọi run trong workspace làm “đang xử lý” vì sẽ lộ trạng thái việc riêng. Cần xác nhận root/Leti/tool/cancel/reconnect trên worker thật trước khi đóng.
- [ ] **U17 · P1 · FE/BE — Agent gửi ảnh/file cho user.** Đã dùng inbox_send/file_refs hiện có, hướng dẫn agent và kiểm tra quyền/copy vào conversation storage khi cần. Attachment có thumbnail, mở và download trong chat/Activity; không lưu presigned URL vào lịch sử. Tests đã xác nhận metadata và renderer. **Còn:** agent thật tạo và gửi ảnh/PDF/text qua worker, người nhận có/không có quyền, reload và nguồn bị xóa/chuyển.
- [ ] **U18 · P2 · FE/BE — Browse artifact/blob.** Đã có tab Artifacts trong viewer blob: duyệt node con bằng ListNodes, breadcrumb, trạng thái xử lý, preview/download và chỉ đọc. Không tạo storage riêng. **Còn:** nghiệm thu PDF có ảnh trích xuất/thư mục con từ ingest thật, replace/trash nguồn khi browser đang mở. Cần model ingest để kiểm tra đủ luồng.
- [x] **U19 · P1 · FE — Syntax highlight code block.** Giữ Shiki, mở rộng grammar/alias gồm Go/Rust/TOML/C/C++/C#, nhận diện code fence qua `pre`, fallback plain text khi không hỗ trợ. Browser đã xác nhận token có màu khác nhau ở dark/light trong chat; renderer Activity dùng chung. Copy giữ nguyên code. Số dòng giữ bật cả trước và sau khi highlight bất đồng bộ hoàn tất.

## 2. Tính năng bổ sung ngoài yêu cầu ban đầu

### Điều khiển agent và công việc

- [ ] **A01 · P1 · FE — Pause / Resume agent.** Đã thêm controls, trạng thái chờ/lỗi, invalidate resource/directory/graph trong Overview; nút Pause/Resume ở trên, Delete ở dưới. **Còn:** nghiệm thu pause khi đang chạy, message tới lúc pause và resume bằng worker thật; xác nhận operator không điều khiển được.
- [ ] **A02 · P1 · FE — Stop lượt chạy.** Root/Leti có Stop theo đúng run ID và capability; gọi cancel hiện có, giữ output đã sinh, refetch sau yêu cầu dừng. **Còn:** tool thật đang chạy, run kết thúc ngay trước khi bấm, bấm lặp và kết quả hủy trên worker.
- [ ] **A03 · P1 · FE — Quản lý quyền agent.** Đã có Access, danh sách operator và grant/revoke từ workspace members, phân biệt manage_access với edit settings. **Còn:** nhiều tài khoản thật grant → dùng private chat → revoke, đặc biệt stream đang mở và không lộ chat người khác.

### Hội thoại

- [x] **A07 · P2 · FE — Draft chat bền.** Lưu text/reply theo actor/workspace/agent trong localStorage; gửi thành công mới dọn recovery, lỗi storage vẫn soạn được và có cảnh báo. Không tự gửi sau reload. Tests xác nhận account isolation và cleanup logout.
- [x] **A08 · P2 · FE/BE — Message permalink.** Copy message link với message/role, API context theo quyền riêng tư, scroll/highlight dùng chung cho reply và permalink. SQL tests xác nhận message cũ, giới hạn actor và phân biệt role khi ID trùng.

### Storage

- [ ] **A09 · P1 · FE — Quản lý quyền storage.** Đã expose List/Set/Revoke, chọn user/agent trong workspace, tôn trọng manage_access; giải thích quyền conversation kế thừa. **Còn:** grant/revoke thật trên nhiều account và agent, đặc biệt quyền bị thu hồi trong lúc viewer/transfer đang chạy.
- [x] **A10 · P2 · FE — Xóa vĩnh viễn/dọn Trash.** Có Delete permanently/Empty trash, xác nhận, xử lý đủ phân trang, tiến trình và lỗi từng mục; dùng trash ID thật. Adapter/SQL tests bao phủ pagination, purge và dung lượng.
- [x] **A11 · P2 · FE — Tạo file text mới.** New file dùng dialog/validateName hiện có, tạo text rỗng bằng MIME/extension rồi mở editor; xử lý quyền ghi và trùng tên qua API.
- [x] **A12 · P2 · FE/BE — Tìm nội dung toàn storage.** TextSearch có phân trang, semantic search giới hạn topK, kết quả có path/snippet/line; mở và chọn dòng trong Storage lẫn viewer hội thoại. Adapter tests và browser đã xác nhận nhảy đúng dòng trong file chưa mở.

### Upload, chỉnh sửa và khôi phục

- [x] **A13 · P2 · FE/BE — Hủy/resume upload.** AbortSignal xuyên checksum/XHR/complete; Cancel abort server session, điều hướng giữ metadata để resume. GetUpload trả parts/checksum/ETag đã được server xác nhận; chọn lại file và kiểm tra checksum, chỉ gửi part còn thiếu. Lưu metadata nhỏ theo account bằng localStorage, không lưu byte file/token/URL; không thêm IndexedDB. Tests xác nhận resume sau tạo lại adapter, cancel khi hash/transfer, navigation và session server.
- [x] **A14 · P1 · FE — Replace giữ danh tính file.** Blob dùng UploadReplace với expectedVersion, text dùng MutateText; không trash/create khi thay nội dung. Adapter/SQL tests xác nhận giữ node ID, chặn conflict và không mất nội dung cũ khi thất bại.
- [ ] **A15 · P1 · FE/BE — Theo dõi/retry processing.** Đã đưa ProcessingSummary vào UI, retry có request_id/expectedVersion/quyền ghi, migration lưu attempt; workflow ID theo attempt và maintenance khôi phục dispatch. Stale worker không ghi đè attempt/version mới; SQL tests đã qua. **Còn:** chạy fail/retry parse/enrich/index bằng Temporal và ingest model thật, gồm worker crash giữa dispatch/commit.
- [x] **A16 · P2 · FE — Dung lượng storage.** Circle progress 34px ở đáy rail, phía trên Settings và avatar; click mở popover used/quota/available. Bỏ progress bar ở Storage sidebar. Refetch sau thay đổi và preflight upload; backend vẫn kiểm tra quota cuối cùng gồm revisions/artifacts.
- [x] **A17 · P1 · FE — Giải quyết save conflict.** Giữ draft, View server version, reload có xác nhận và Save as copy; không force overwrite. Browser đã xác nhận restore khi đang sửa không mất draft và copy an toàn; adapter kiểm tra expectedVersion.
- [x] **A18 · P2 · FE/BE — File version history/restore.** Bảng file_revisions giữ 10 bản cũ/file, actor/thời điểm snapshot, text/object_key. List/read/restore theo quyền; restore tạo version mới, blob reset processing, quota/purge/GC giữ đúng object. SQL tests bao phủ text/blob/retention/quota; browser đã view/restore và xử lý draft conflict.
- [x] **A19 · P2 · FE — Nhận biết file thay đổi.** Stat polling 5 giây cho viewer đang hoạt động, refetch khi focus; cập nhật node/version/metadata. Bản sạch refresh, draft được giữ và có cảnh báo/conflict actions; mất quyền không cho Save. Browser đã kiểm tra đổi version khi đang có draft. Không thêm change feed service.
- [x] **A20 · P2 · FE/BE — ZIP streaming có thể hủy.** Stream tới writable file handle khi hỗ trợ; fallback browser download qua ticket hash dùng một lần/hết hạn sau 2 phút, GET kiểm tra quyền lại. Cancel/unmount hủy fetch/writer; không buffer toàn ZIP trong RAM. Tests xác nhận cancel/abort và chạy **Envoy thật** kiểm tra ZIP bytes, Content-Disposition, replay 404, POST thiếu auth 401. Đã sửa regex route vượt giới hạn RE2 khiến Envoy không khởi động. Browser-native fallback hủy trong download manager của browser.

A04 (scheduler management UI), A05 (Questions & requests toàn app) và A06 (message search UI/API) đã bỏ theo yêu cầu. Schedule deliveries/details có sẵn chỉ đọc. Không còn toolbar/separator trống sau khi gỡ nút scheduler.

## 3. Thay đổi dữ liệu và triển khai

- Platform: migration `0002_account_settings.sql` cho appearance/preferences; contract GetMe/UpdateMe giữ preferences riêng tư, patch theo trường.
- Leta: `0007_message_processing.sql` cho processing association; đã bỏ migration search chưa triển khai. API private chat vẫn lọc actor, không dùng owner Activity làm lịch sử chung.
- LetFS: `0003_processing_retry.sql`, `0004_file_revisions.sql`, `0005_archive_downloads.sql`; quota/GC/purge/replace/restore đã tính cùng revisions và artifacts.
- Contracts đã generate lại Go/Python/public descriptor bằng `make generate`. Envoy template có route GET archive ticket, không mở bypass JWT cho các RPC còn lại.
- **Chưa áp migrations hoặc restart/deploy app đang chạy.** Working tree giữ cả thay đổi có sẵn của người dùng; không commit/reset hàng loạt.

## 4. Bằng chứng kiểm tra và phần còn phải nghiệm thu

- Web production build, Web/E2E TypeScript: đã qua với working tree cuối. Pyright và Go vet: đã qua; các thay đổi sau đó chỉ ở frontend. Prettier và git diff --check: đã qua. Oxlint không có lỗi chặn, còn cảnh báo hooks/Fast Refresh trong source; build còn cảnh báo chunk lớn và module directive của dependency.
- Public Playwright suite trước đợt chỉnh menu/settings: **32 passed (1.5m)**, gồm ảnh remote và âm gửi/dedupe. Có screenshot desktop/mobile của workspace settings, context menu, file history/conflict và code highlight. Một lượt chạy trước bị SIGTERM; đã chạy lại toàn bộ thành công. Console còn cảnh báo Clerk dev key, script tag, Questionnaire và React/router ở public navigation; test pass không chứng minh các cảnh báo này đã được xử lý.
- Go unit tests Platform/LetFS/SDK: đã qua. SQL integration dùng schema riêng trên Postgres rồi xóa schema; không dùng dữ liệu workspace thật. LetFS SQL gồm restore blob và Envoy streaming; account SQL gồm validation/isolation/preferences patch: đã qua.
- Private chat SQL: **23 passed, 1 skipped**. Nhóm Leta mục tiêu trước đó: **55 passed, 1 skipped**. Pyright: **0 lỗi**; Ruff Python: đã qua.
- Full Python suite: **114 passed, 23 skipped, 6 failed**. Sáu lỗi ingest export dừng vì thiếu thư mục model `/models/docling`; chưa có bằng chứng để coi full suite xanh. Redis private-stream test chưa chạy vì thiếu cấu hình Redis test.
- Browser tests dùng adapter demo cách ly và một số kiểm thử integration thật ở SQL/gateway; không thay thế Clerk, nhiều account, worker Temporal và ingest end-to-end. Những mục phụ thuộc các luồng này vẫn mở ở trên.
- Không khẳng định đã tìm hết mọi thiếu hụt của sản phẩm. Phát hiện tính năng mới sau này thêm ID mới; không đổi lỗi phụ/tiêu chí nghiệm thu thành mục A để tăng số lượng.

Kiểm tra đợt sửa menu/settings/Overview: web production build và Web/E2E typecheck đã qua; SQL private context/processing đã qua (1 test). Lượt browser tập trung gồm seen receipt đã qua 10/10; toàn public suite cuối đã qua **34/34 (2.3m)**, gồm For you desktop/mobile và luồng mở đúng câu hỏi. Impeccable detector không có findings trên các component đã chỉnh.
Review giao diện độc lập: **ship**, không có finding cần sửa trong phạm vi menu/settings/Overview/seen icon đã review (ảnh 1440/1851/390px và source mục tiêu). Không thay thế kiểm tra quyền production.
