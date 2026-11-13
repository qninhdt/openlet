# Box và Leti — thiết kế đã chốt

Ngày 2026-11-12. Người dùng đã duyệt; chưa runtime implementation. [Plan](plan.md), [schema/constraints](schema.md), [Temporal](temporal.md), [filesystem](filesystem.md), [tools](tools.md) và [streaming](streaming.md) giữ các owning contracts. Quyết định home-first dưới đây thay khoảng trống provisioning cũ; không cần đổi API LetFS hoặc home_node_id NOT NULL.

## 1. Thành phần và ownership

Box là nhóm Leti với membership, communication edges và representative bất biến, dùng chung một home directory. Box không có LLM, inbox, LangGraph thread hoặc Agent workflow riêng. BoxLifecycle chỉ thực thi create/delete hữu hạn.

Mỗi Leti có stable agent ID, inbox/cursor, LangGraph thread, rolling summary + bounded tail, public history và logical runs riêng. Dùng cùng runtime implementation với root; không một framework/class/runtime per agent. Agent workflow lazy-start khi nhận input đầu tiên; create box không start children hoặc tự gửi việc. Leti chạy độc lập và có thể đồng thời theo worker slots.

Representative là một Leti bình thường được chọn làm endpoint root/box, không supervisor engine riêng. Model/effort mặc định inherit root; product agent configuration API có thể override và cập nhật prompt/model tại safe boundary. Không lưu resolved-model hoặc child pause/status mirrors. Root desired pause áp dụng children; remove human owner khỏi workspace không dừng agents.

## 2. Graph và messaging

| Sender | Recipient |
|---|---|
| Root | Representative qua endpoint của box cùng root |
| Representative | Root và các Leti có cạnh trực tiếp |
| Leti khác | Các Leti có cạnh trực tiếp trong cùng box |

Cạnh hai chiều, lưu một row low/high. Không ép DAG; cycle/mesh hợp lệ. Graph là quyền gửi message, không compile thành một LangGraph chứa các Leti nodes. Backend kiểm route/liveness trong inbox admission transaction; model nhận bounded allowed roster từ workspace_get.

Chỉ inbox_send tạo delivery. Không auto-broadcast, auto-forward final output hoặc tự chạy toàn graph. Leti không direct human chat/cross-box messaging. HITL riêng: hitl_ask có thể hỏi bất kỳ current human workspace member theo exact-recipient contract, không mở chat route mới. Root nhận inbox notifications, Leti nhận bounded full inbox batch; agents trao đổi nội dung hoặc file references rõ ràng, không chia sẻ context ngầm.

## 3. Create input và validation

Giữ box_create(name, description, letis, edges, representative) trong tools.md/tool-schemas.json. LetiDefinition có name/description/system_prompt; system cấp IDs một lần trong canonical Temporal input, mapping local names sang IDs. Model không quản lý IDs kỹ thuật, model inheritance hoặc timeouts.

Validation tại owning boundary: ít nhất một Leti; unique names; representative thuộc roster; edge endpoints tồn tại/khác nhau/không duplicate; box live name unique trong root; input có kích thước hữu hạn. SQL giữ deferred representative FK, same-root/box endpoint FKs, low < high và naming/home uniqueness. Không graph version, edge status, reverse rows hoặc adjacency mirror.

Membership/edges/representative không sửa sau create; đội mới là box mới. Prompt/model configuration của agents vẫn dùng API chung. Mutation targets dùng stable IDs; tên chỉ phục vụ create/lookup/display.

## 4. Home-first provisioning

Native Temporal nhận immutable create input và stable IDs trước external effects. Box create dùng hai activities hiện có theo thứ tự mới:

```text
BoxLifecycle.open(create)
  → provision_box: LetFS CreateDirectories(".boxes/<box_id>")
                   trả home_node_id thật
  → prepare_box: SQL transaction ghi active box + Leti + edges + finalized receipt
  → return resource sẵn sàng
```

provision_box kiểm root active và dùng effect barrier hiện có trước native directory operation. CreateDirectories nhận locator của home storage root và stable relative path; LetFS tự sinh node ID, replay cùng path lấy directory hiện có. Activity result được Temporal lưu để SQL step dùng lại. Không preallocate node ID mà LetFS chưa nhận.

prepare_box khóa root gate, kiểm current liveness/unique name rồi ghi graph cùng receipt trong một transaction. Box row có home_node_id NOT NULL ngay từ INSERT; representative FK deferred đến commit. Box SQL states chỉ active/deleting/archived. Pending creation thuộc Temporal, không SQL provisioning row, phase table hoặc pending receipt. Box list chưa thấy resource trước SQL commit.

Box create là ngoại lệ của lifecycle admission chỉ SQL: open(create) chờ provision_box rồi prepare_box; Update COMPLETED/resource ACK chỉ trả sau SQL commit, tool chờ resource active. API create chờ resource sẵn sàng; HTTP disconnect không cancel operation, retry giữ identity. Không coi native Update ACCEPTED là resource đã lưu. Không thêm workflow/activity type hoặc progress table.

Root đóng trước SQL commit thì transaction không tạo active box. Critical-section barriers/gate checks ngăn tiếp tục provision sau teardown. Crash giữa directory create và SQL có thể để lại directory rỗng nếu operation không hoàn tất; chấp nhận giới hạn này, không thêm orphan ledger/sweeper/compensation framework. Không tuyên bố SQL/LetFS atomic hoặc native mkdir bảo đảm mọi concurrent caller không conflict.

## 5. Filesystem và rights

Root thấy ~/.boxes/<box_id>/; mọi Leti cùng box thấy directory đó là ~/. Bind bằng home_node_id thật, không resolve theo tên box. Root nhìn toàn home storage; box khác có containment root khác. Các locators/raw IDs và cả hai đầu copy/move phải mang đúng containment root, LetFS kiểm live ancestry.

Leti gọi LetFS bằng root agent actor. Box không phải security principal/storage riêng; external public/shared/private grants của root dùng chung qua /mnt/<storage_id>. Không tạo /mnt alias của home storage cho Leti. HITL storage approval cấp root, mọi Leti có cùng external grants sau refresh. Không SQL grant/mount mirrors hoặc actor từ model.

Shared files dùng native LetFS edit/version/receipt semantics. Không box-wide file lock hoặc distributed filesystem coordinator. Full overwrite và multi-effect shell giữ giới hạn đã ghi trong filesystem.md, không tự hứa auto-merge/exactly-once.

## 6. Delete và control

close_box đóng admission bằng deleting. cleanup_box settle provisioning, delete schedules có creator/target trong box, cancel pending HITL và settle grant effects, stop children và qua writer barriers, trash home rồi archive box. Root/box khác tiếp tục chạy; history còn theo quyền hiện tại. Không thu hồi root grants chỉ vì requester box bị xóa.

Root cleanup gọi cùng concrete box cleanup function inline; không join BoxDelete workflow/B activity trong cùng pool. Pause/cancel/rollover dùng agent runtime chung, sync checkpoint/public projection rồi keep_latest tại mỗi model/tools boundary. Technical rotation không tạo logical run mới.

## 7. API/code và checks

API create/list/get/delete boxes ở root Leta; config/history/run/cancel của Leti dùng agent APIs chung. List trả metadata/state/counts; get trả graph/agent summaries, prompts opt-in. Requests/schedules/history qua owning paginated APIs, không nhét toàn bộ vào box_get.

boxes.py chứa owning models/functions/SQL/routes, messages.py kiểm routing, jobs/resources.py orchestration, runtime/agent.py chạy root/Leti và runtime/tools.py bindings. Không box runtime/service, repository framework hoặc module per Leti.

Focused checks khi implementation: atomic graph/invalid route rejection; home-first retry giữ home ID và NOT NULL; lazy-start, concurrent children độc lập và same-box shared home/cross-box containment; delete settle writers/producers và giữ public history. Reuse shared integration environment, không port archive tests hoặc một stack per case.

Chưa triển khai/apply DB hoặc chạy provider/LangGraph/PostgreSQL/LetFS/Temporal journey. SQL artifact chỉ cập nhật CHECK states của boxes; root letas vẫn provisioning/active/deleting/archived. Giữ 11 application tables/86 columns; inventory hiện 6 workflows/22 activities/3 queues sau workspace cleanup, không thêm box activity.
