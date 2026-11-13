# HITL Leta: thiết kế cuối đề xuất

Ngày 2026-11-12. Đã đối chiếu sáu archive modules HITL (906 lines), selected domain/store/bridge operations, [schema](schema.md#11-hitl_requests), [Temporal](temporal.md#8-hitlrequest) và active LetFS access APIs. Đây là thiết kế cho app viết mới, chưa implementation. Giữ 11 application tables; inventory hiện tại 6 workflows/22 activities/3 queues sau khi thêm workspace cleanup, không thêm HITL activity. Public transport theo [HTTP/streaming đã chốt](streaming.md), HITL vẫn async resource/inbox, không agent-wide AG-UI interrupt.

## 1. Mục tiêu và hai request types

HITL là một yêu cầu bất đồng bộ từ root Leta hoặc Leti gửi tới một human cụ thể. Tool trả sau durable admission, agent tiếp tục làm việc khác. Một workflow HitlRequest, ID hitl/{request_id}, chờ decision/deadline, áp dụng grant nếu cần rồi giao kết quả về đúng requester.

| Type | Human làm gì | External effect |
|---|---|---|
| ask | Trả lời form text/single_choice/multiple_choice | Không có |
| approval | Accept hoặc deny quyền viewer/editor vào một storage cụ thể cho root agent | LetFS SetStorageAccess khi accepted |

Approval này không là generic execute-any-tool approval. Accept không thực thi command/model tool đang bị giữ lại. Agent đọc kết quả rồi tự chọn hành động tiếp; mỗi file operation vẫn qua quyền LetFS. Không pause toàn agent hoặc giữ Python stack chờ human.

## 2. Tools và người nhận

| Tool | Input chính | Behavior |
|---|---|---|
| hitl_ask | recipient_user_id, questions, optional title | Gửi tới bất kỳ human owner/member hiện tại trong cùng workspace |
| hitl_request | storage_id, recipient_user_id, role=viewer, reason | Gửi tới human được chỉ rõ và có current storage.manage_access |
| hitl_list | status, optional box filter cho root, cursor | Root quản lý root scope; Leti chỉ requests của chính nó; page size do system |
| hitl_get | request_id | Xem canonical form/decision/outcome trong authorized scope |
| hitl_cancel | request_id, reason | Cancel pending request thuộc quyền quản lý, không revoke grant |

hitl_ask nhận recipient_user_id explicit do root Leta hoặc Leti chọn. Chỉ cần người nhận là human có current workspace.participate trong workspace của root: owner hoặc member đều được, không cần agent.use, agent.manage hoặc quan hệ với owner của agent. Không resolve/fallback về agent.owner hoặc created_by. Đây là quyết định người dùng đã chốt; agent độc lập owner.

recipient_user_id là event identity cố định. Khi open, xem incoming card và answer đều kiểm người nhận còn tham gia cùng workspace; chỉ exact recipient được answer. Thành viên khác không được trả lời thay. Nếu recipient rời workspace thì mất quyền xem/answer; agent tiếp tục chạy, request vẫn pending tới cancel/expiry hoặc recipient rejoin. Không tự retarget tới owner hoặc member khác; muốn hỏi người khác thì tạo request mới. Owner transfer không ảnh hưởng ask routing.

hitl_request phải dùng storage ID cụ thể vì một user có thể có nhiều private storages. recipient_user_id là proposed human recipient, không phải quyền được caller tự khẳng định. Open kiểm native storage workspace relationship/current recipient manage_access và scope cùng workspace; apply còn để LetFS kiểm actual storage parent và rights lần nữa. Không có personal resolver, user→single-storage mapping hoặc platform grant proxy.

Lý do không auto-discover approver: ListStorageAccess yêu cầu manage_access; agent đang xin private access thường chưa có cả read nên không gọi được API đó. Storage có thể thuộc user, agent hoặc workspace userset. Yêu cầu storage ID và human recipient từ user/task context, kiểm bằng native SpiceDB graph, không enumerate toàn bộ ACL/managers hoặc tạo internal resolver RPC mới. Admission không đọc metadata private bằng cách giả actor của proposed recipient; không expose graph ownership/discovery rộng hơn request cần thiết.

Trước khi mở approval mới, kiểm root current read/write tương ứng: nếu đã đủ thì trả already_granted, không tạo request SQL, không chờ human hoặc gửi thêm outcome message. Đây chỉ là permission snapshot; file operations vẫn kiểm quyền lại. Pending request đã tồn tại cùng ID thì trả canonical request đó trước, không biến request cũ thành request mới vì permissions đã đổi.

Grantee luôn là root agent suy qua requester. Model không truyền grantee tùy ý; Leti không có graph grant riêng. Viewer nghĩa là read, editor nghĩa là write; không xin owner, chuyển quyền sở hữu hoặc xin cả workspace. Public viewer thường already_granted; public editor vẫn cần human có manage_access.

## 3. Form và response

Tool chỉ nhận questions={text,options?:string[],multiple?:bool=false}[]; không options là text, có options là single choice trừ khi multiple=true. System cấp question/option IDs theo thứ tự, suy ra typed form rồi persist immutable một lần. Title có thể bỏ, lấy label ngắn từ câu hỏi đầu trong existing title bound; không gọi thêm model. Model không sinh/copy IDs hoặc backend type. Chi tiết [tool input audit](tools.md#hitl).

Canonical stored form chứa questions array hữu hạn. Question IDs duy nhất; choice option IDs duy nhất trong question. Mỗi question chỉ một loại:

- text: answer {text}, cho phép text rỗng.
- single_choice: answer {option_id: nullable, note}; không chọn gì vẫn hợp lệ.
- multiple_choice: answer {option_ids: [], note}; empty list vẫn hợp lệ.

Submit gửi đúng một answer cho mỗi question, không ID lạ, option ID lạ hoặc duplicate selections. Question/option ID checks và size bounds là input validation thật; không required/default/answered flags, conditional forms hoặc question/answer tables. Không bắt human phải chọn option chỉ để được gửi note.

Approval response chỉ accept/deny. Storage/role/recipient/form không sửa sau open; muốn thay thì cancel pending request và tạo request ID mới. Actor lấy từ authenticated ingress hoặc trusted runtime, không nhận actor/status/outcome tùy ý trong public body. expire chỉ là internal action của workflow, không user endpoint.

## 4. Data và trạng thái

Giữ hitl_requests với 12 fields đã duyệt: id, requester_agent_id, recipient_user_id, type, title, payload, status, response, outcome, expires_at, created_at, resolved_at. Root/grantee/box suy qua requester, result message ID suy từ request ID. Không thêm field delivery_sent, attempt, grant_key, native workflow ID hoặc current-owner mirror.

Payload ask chỉ questions. Payload approval chỉ storage_id/role/reason. type/status ở scalar columns, không lặp trong payload/response.

```text
ask:
  pending → answered | cancelled | expired

approval:
  pending → accepted | denied | cancelled | expired
  accepted + outcome NULL          = đã chấp thuận, effect còn pending
  accepted + outcome granted       = grant đã được acknowledge hoặc quyền đã đủ
  accepted + outcome skipped       = không hoàn tất grant theo preconditions hiện tại
```

response chứa authenticated actor và answers/reason phù hợp; expired không có response. resolved_at là thời điểm decision, không grant completion. outcome chỉ cho accepted approval, dạng {status: granted} hoặc {status: skipped, reason: ...}; ask/deny/cancel/expire không sao chép response vào outcome.

Giữ essential CHECK pending iff resolved_at NULL và outcome chỉ accepted approval. Conditional UPDATE WHERE status='pending' ghi status/response/resolved_at cùng transaction. Type-specific transitions/JSON union kiểm tại owning function. Không thêm generic state-machine framework hoặc outbox.

## 5. Workflow và activities

Giữ đúng ba activities HITL và một bridge dùng chung:

| Activity | Kind | Trách nhiệm |
|---|---|---|
| open_hitl_request | Effect | Resolve/validate recipient, kiểm graph/preconditions, canonical insert hoặc existing/already_granted |
| resolve_hitl_request | Local SQL | Exact actor/type/liveness/deadline command checks và atomic conditional decision |
| apply_hitl_outcome | Effect | Accepted approval: current rights/liveness, LetFS grant khi cần và persist actual outcome |
| deliver_input | Shared bridge | Giao stable result vào requester inbox |

Native current-rights checks cho human response ở owning feature admission trước khi gửi Update; Local Activity không gọi SpiceDB/RPC trong SQL transaction. SQL vẫn kiểm exact recipient và allowed actor/action; apply effect kiểm quyền grant hiện tại lần nữa. Trusted cleanup cancel dùng owning internal path, không giả user response.

State workflow chỉ request snapshot nhỏ, decision lock, effects_settled và done. Updates open/resolve/settle_effects dùng cùng decision lock để không có stale open ghi đè decision. Không giữ lock qua grant hoặc result delivery.

```text
chờ open và persist canonical request
nếu already_granted:
  set effects_settled/done; drain handlers; return

chờ human decision hoặc native deadline timer
timer/resolve/cleanup chọn một terminal decision dưới decision lock
nếu accepted approval: await apply_hitl_outcome
set effects_settled
await deliver_input với stable request-derived message ID hoặc inactive skip
set done
drain handlers; return saved result
```

Tool open ACK sau SQL commit; response resolve ACK sau decision commit, không đợi grant hoàn tất. UI thấy accepted/outcome NULL thì hiển thị effect còn pending, không báo đã có quyền. Các ask/deny/cancel/expire bỏ qua grant activity, dựng inbox result từ saved decision; không lưu outcome giả chỉ để dùng chung code path.

HTTP disconnect không cancel durable request. Không whole-workflow retry policy, không lifetime timeout hoặc polling loop. Pending request không có deadline vẫn có thể chờ lâu: workflow wait không giữ worker process/agent stack; reads lấy SQL, không tạo workflow Update cho mỗi UI poll. Không cần CAN chỉ vì request chờ lâu nhưng history không tăng theo idle time.

## 6. Deadline, race và duplicate

Agent tools không nhận timeout_seconds/expires_at. Trusted product policy quyết định request lifetime; nếu có expiry hữu hạn thì workflow normalize expires_at một lần bằng workflow.now() lúc open và lưu canonical deadline cho SQL/UI/history. NULL vẫn nghĩa là không deadline; default không tự thêm TTL chưa được yêu cầu. Retry không đọc config mới để gia hạn request. Không nhét timeout vào payload hoặc thay deadline bằng một knob khác cho model.

Một clock authority cho business expiry: workflow.now(). Decision handler lấy lock, kiểm deadline và chốt timestamp/action; local SQL retry dùng lại decision đó. Nếu quá deadline khi handler xử lý thì conditional expire, không chấp nhận late answer chỉ vì timer chưa chạy. Bỏ clock_timestamp decision cùng sleep(1s) clock-skew reconciliation loop của archive.

Answer/accept/deny/cancel/timer chỉ có một terminal winner. Identical normalized decision retry trả row cũ; decision khác sau terminal conflict, không overwrite answer hoặc đổi accepted thành cancelled. Timer/cleanup gặp terminal thì dùng decision đã lưu; nếu accepted còn effect pending, cleanup đợi effect settle.

Stable request ID cho create dedupe, SQL terminal state cho response retry; không thêm receipt table riêng cho HITL. Retry không reset recipient/deadline/payload, không reopen completed request. Sau Temporal retention, SQL terminal request vẫn đọc/kiểm duplicate được; không start workflow mới để apply grant lần nữa. Pending workflows vẫn ở native history; operator termination là operational recovery, không automatic workflow reconstruction framework.

## 7. Grant qua LetFS

Accepted approval dùng root effect lock đã có, cùng barrier với root cleanup:

1. Acquire effect lock rồi đọc accepted decision/outcome; outcome đã có thì return, không regrant.
2. Kiểm root/requester/box còn active. Source đã đóng trước effect thì persist skipped; không grant cho requester đã xóa.
3. Kiểm accepting user đúng recipient và current storage.manage_access. Agent đã có đủ read/write thì persist granted, không setter lại viewer khiến một editor hiện có bị downgrade.
4. Nếu còn cần grant, gọi SetStorageAccess(workspace_id,storage_id,target=agent:root,role) bằng authenticated accepting-human identity đã ghi trong response. Không dùng root tự grant, không credentials/JWT vào SQL hoặc workflow.
5. LetFS kiểm current manage_access, actual storage parent và workspace.eligible_actor, write native relationships; sau graph ACK lưu outcome trong transaction ngắn rồi nhả effect lock.

Permission/resource/liveness failure đã xác định → skipped với reason hữu hạn; timeout/unavailable/transient error → native activity retry. Không catch-all rồi giả granted/skipped. Không SQL transaction qua LetFS/SpiceDB RPC. Nếu crash sau graph ACK trước outcome save, retry cùng accepted intent và recheck rights; không hứa distributed atomicity.

SetStorageAccess hiện là role assignment bằng native graph set/delete, không có request_id hoặc permanent grant receipt. Retry không globally exactly-once: concurrent revoke trong khi approval effect chưa settle có thể bị retry regrant. Không grant/revoke saga hoặc shadow ledger. Outcome granted là historical ACK, không chứng minh quyền hiện tại mãi mãi; requests tới LetFS vẫn native checks, bounded cached bytes dùng theo TTL đã chốt.

Grant vào root agent, không vào human creator hoặc riêng Leti. Các Leti cùng root có thể sử dụng external storage theo shared root grants. UI phải giải thích phạm vi đó trước accept; không nói đây là private grant chỉ dành cho Leti đang hỏi.

## 8. Mount sau grant

Sau outcome granted, runtime refresh dynamic mounts tại safe tool boundary theo [VFS design](filesystem.md#2-mount-và-identity). Storage xuất hiện tại /mnt/<storage_id> nếu root còn read; mode dựa current capabilities. Không đổi home storage_id hoặc gọi Platform personal-scope discovery.

Box/Leti vẫn có home containment riêng; không tạo external alias mở toàn root home storage. Grant đánh dấu discovery cần refresh ở tool boundary tiếp theo, không đợi TTL thông thường hoặc giữ HITL workflow chờ sandbox ACK. Không đổi mounts giữa command. Nếu quyền bị revoke ngay sau outcome, backend request có thể bị từ chối; cached bytes vẫn theo bounded TTL, refresh tiếp theo gỡ mount. Không mount registry hoặc delivery_sent field để theo dõi việc này.

## 9. Ai xem, trả lời, cancel

| Caller | Quyền |
|---|---|
| Requester Leti | Create/read/list/cancel requests của chính nó |
| Root agent | Read/list/cancel requests trong root scope, không accept thay human |
| Human có current agent.use | Xem requests thuộc root qua owning product API; không có quyền trả lời thay recipient |
| Human có current agent.manage | Cancel pending requests thuộc root |
| Exact ask recipient | Xem card của chính request và answer khi còn workspace.participate, không cần agent.use |
| Exact approval recipient | Xem request card giới hạn và accept/deny với current workspace participation/storage.manage_access, không cần agent.use |

Ask recipient chỉ cần current workspace.participate khi xem/answer, không agent.use. Được nhận ask không tự cấp quyền xem các requests khác của root. Cả ask/approval recipient không vì nhận card mà được đọc prompt/transcript/files riêng của Leta; card chỉ form/context cần trả lời hoặc storage ID/role/reason/phạm vi grantee cần duyệt. Incoming requests của user khác không được list/get; filtered pagination cursor đi theo candidate page đã xét, không suy hết page từ số items sau authorization filter.

Không mặc định workspace owner được xem private agent transcript hoặc accept thay addressed user. Owner transfer không retarget request cũ; human cũ có thể trả lời nếu vẫn exact recipient và current rights đủ. Nếu không, root/current manager có thể cancel pending và tạo request mới. Human membership mất không revoke grants độc lập mà agent đã có.

## 10. Result delivery và cleanup

Answered/accepted-after-outcome/denied/cancelled/expired tạo một inbox result với source_kind=hitl, source_id=request_id và stable request-derived message ID. Body chứa canonical response/outcome cần cho agent; typed request đọc bằng hitl_get. Không generic result-data bag hoặc copy form nguyên vẹn vào mỗi inbox row. Giao đúng requester, không auto-forward lên root; representative phải inbox_send nếu cần báo root.

Admission duplicate trả original message; request đã terminal không tạo nhiều input vì delivery workflow retry. Recipient/root/box đã đóng thì skip, không start lại archived Agent. Agent paused vẫn nhận result vào inbox để xử lý khi resume. Grant không đợi agent thực sự đọc result.

settle_effects dùng khi delete box/root: cancel nếu pending, nhả decision lock rồi đợi effects_settled. Accepted in-flight grant phải qua effect barrier; grant chưa bắt đầu sau source closure thì skip. Đặt effects_settled trước inbox delivery để cleanup không phải đợi bridge delivery đang xếp hàng cùng pool. Flags được set trước drain handlers; không đợi một handler đang đợi chính flag của main.

Delete box không revoke root grants đã accepted, vì grantee là root và box khác có thể đang dùng. Cancel terminal không undo grant; revoke là thao tác LetFS riêng. Xóa workspace ở core vẫn không chờ HITL/runner ACK của Leta; cleanup này thuộc user-requested Leta lifecycle.

## 11. Folder structure và khác archive

```text
src/leta/hitl.py          # typed forms/requests, feature functions, SQL, activities
src/leta/jobs/hitl.py     # deterministic HitlRequest workflow
src/leta/runtime/tools.py # tool declarations gọi feature functions
```

Types đặt cạnh owning feature; không human modules, generic approval engine hoặc per-action dispatcher framework. Native clients cụ thể, không repository interfaces. Ba activities giữ E/L/E như Temporal inventory hiện tại; grant + outcome save là cùng owning effect, không save-outcome activity/bridge riêng.

| Archive | Thiết kế mới |
|---|---|
| Creator cố định cho ask | Explicit recipient là bất kỳ current human workspace owner/member; không phụ thuộc agent owner hoặc agent.use |
| Personal scope qua Platform, /users/<user> | Storage ID cụ thể + addressed human có manage_access; LetFS direct |
| Phải scan accessible scopes để biết quyền | Native read/write permission check cho đúng root/storage |
| decision.action và outcome copy nhau | Scalar terminal status, response/outcome có vai trò riêng |
| grantee_leta_id/outcome_message_id/grant_key/resource columns | Suy root/result identity, storage/role trong typed payload |
| SQL clock + workflow timer + skew sleep | Workflow clock làm deadline authority |
| settle đợi finished gồm inbox delivery | Đợi effects_settled, không delivery barrier |
| Separate grant/save outcome helpers và class hierarchy | Một concrete apply_hitl_outcome effect, native clients |

## 12. Verification cần thiết

Viết mới focused behavior checks trong shared environment:

1. Form normalization cho ba loại, empty answer hợp lệ, unknown option/question và duplicate IDs bị từ chối.
2. Tool trả pending, agent làm việc tiếp; workspace member không có agent.use vẫn nhận/answer đúng ask được gửi tới mình, member khác/cross-workspace không trả lời được và recipient rời workspace mất quyền. Answer-vs-expiry-vs-cancel có một winner, duplicate response/result không tạo thêm inbox message.
3. Native LetFS grant dùng accepting human và root target; public viewer already_granted, private viewer/editor, requester không thể tự accept; accepted khác granted khi rights/resource mất. Grant xong dynamic mount đọc được; quyền đủ không bị downgrade bởi viewer request.
4. Delete box trong lúc grant pending đợi effect settle nhưng không đợi delivery; grant đã xong vẫn thuộc root; owner transfer/removal không tự retarget request hoặc dừng agent.

Một workflow time-skipping/race check và một shared native grant journey là đủ nền; không matrix mọi action × transport × failpoint, per-test stack, paid model calls hoặc port archived tests. Real grant/revoke ordering còn đúng giới hạn API hiện có, không test để hứa exactly-once chưa có.

Đã đọc archive [forms](../../archive/2026-11-11/apps/leta/src/leta/human.py), [tools](../../archive/2026-11-11/apps/leta/src/leta/runtime/human.py), [workflow](../../archive/2026-11-11/apps/leta/src/leta/temporal/human.py), [activities](../../archive/2026-11-11/apps/leta/src/leta/temporal/human_activities.py), [DTOs](../../archive/2026-11-11/apps/leta/src/leta/temporal/human_types.py), [HTTP](../../archive/2026-11-11/apps/leta/src/leta/http/requests.py), tổng 906 lines, cùng selected store/domain/bridges. Active [SetStorageAccess/ListStorageAccess](../../apps/letfs/internal/storage/access.go) đã đối chiếu qua CodeGraph; không copy source/tests.

Chưa triển khai/runtime tests/native HITL grant journey, không sửa SQL DDL/database, Zed, shared contracts hoặc dependencies. Explicit storage/recipient tool inputs giải quyết private-resource routing; public HTTP/SSE theo streaming.md không mở transcript cho HITL recipient. Native grant/SQL outcome không atomic, revoke trong pending retry chưa có global ordering.
