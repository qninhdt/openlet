# Scheduler Leta: thiết kế cuối đề xuất

Ngày 2026-11-12. Đối chiếu scheduler archive và [Temporal plan](temporal.md#9-schedulechanges). Đây là thiết kế cho app viết mới, chưa triển khai. Giữ architecture PostgreSQL definitions + native Temporal Schedule + ScheduleChanges + ScheduleDelivery; không thêm service, bảng, workflow type hoặc activity. Public transport theo [HTTP/streaming đã chốt](streaming.md); scheduler routes/DTOs chi tiết còn review theo owning feature.

## 1. Kết quả và phạm vi

Agent đặt lịch gửi instruction vào inbox của chính nó hoặc một box được phép. Scheduling chỉ đảm bảo admission input theo timing/policy, không đảm bảo model hoàn thành công việc vào đúng giờ. Agent có thể luôn bận và vẫn nhận scheduled inputs; xử lý chúng bằng inbox/runtime hiện có.

Giữ absolute/relative at, anchored interval, calendar/timezone, recurring end, title/content edit, pause/resume/delete, list/get/upcoming/calendar. Giữ schema đã duyệt: type ngoài JSON, spec chỉ timing, không copied box_id/leta_id/end_at/updated_at trong schedules. Không next_run_at/last_run_at, completed/fired flag, occurrence table, cron parser hoặc polling loop.

## 2. Ba schedule types

| Type | Canonical spec được lưu | Native mapping |
|---|---|---|
| at | at UTC | Exact ScheduleCalendarSpec đủ year/month/day/hour/minute/second, timezone UTC |
| interval | every_seconds > 0, anchor_at UTC, optional end_at | ScheduleIntervalSpec(every,offset), start_at=anchor_at, end_at |
| calendar | timezone IANA, calendar fields/ranges, optional end_at UTC | ScheduleCalendarSpec/ScheduleRange, time_zone_name, end_at |

Create at nhận đúng một trong at có timezone hoặc after_seconds >= 0. Workflow normalize relative time đúng một lần dưới serialized change lock bằng workflow.now(); canonical timestamp nằm trong native history. Retry không cộng delay từ wall clock mới. Interval không có anchor thì lấy accepted workflow time một lần; offset neo vào UTC epoch để không drift theo worker start.

Native timing có độ phân giải giây; ceil timestamps sang giây, không chạy sớm hơn thời điểm requested. end_at chỉ interval/calendar. Không parse cron strings, không thêm custom syntax có nhiều đường biểu diễn tương đương. Calendar defaults/ranges theo native fields; validate unknown fields, field bounds và IANA timezone tại owning input boundary. DST theo Temporal, không tự tính next time ở Leta.

Canonical API input/row có scalar type và spec tương ứng; spec không lặp type. Tên hoặc timezone hợp lệ không phải permission. Các bounds thật như interval dương, input size và target scope vẫn được kiểm.

Agent tool input được tách khỏi canonical API/storage form theo [tool audit](tools.md#scheduler). Model chọn đúng một trong at/after_seconds/every_seconds/calendar; calendar là map native field→integer[] mong muốn chạy. System suy type, map values sang native ranges, áp dụng defaults và normalize times một lần trong serialized command. Không model-supplied type/spec/compiled ranges, cron parser hoặc DSL mới. Canonical SQL/native representation và toàn bộ ranges support của owning API vẫn giữ.

Title optional ở tool, default label ngắn từ content. timezone mặc định từ trusted business context/fallback UTC; starts_at cho explicit interval anchor, ends_at cho recurring cutoff. Đây là business timing intent, không execution timeout. Timing selector thay pattern; khi chỉ đổi starts_at/ends_at/timezone thì existing coordinator lấy current canonical definition dưới change lock và sửa field tương ứng, không bắt model dựng lại full spec. ends_at:null clear cutoff; không generic deep-merge framework.

## 3. Ai được tạo và quản lý

- Root Leta tạo lịch cho root hoặc box representative. Khi caller chọn box, resolve thành stable target_agent_id một lần lúc create.
- Leti chỉ tạo lịch cho chính nó; không schedule peer hoặc root bằng cách bỏ qua graph.
- Root quản lý lịch trong root scope, gồm các box; Leti chỉ xem/sửa/xóa lịch target chính nó. Human calls phải qua current Leta authorization của owning API.
- creator_agent_id và target_agent_id cố định. Timing/title/content/paused có thể đổi; đổi target cần schedule mới. Box của target suy từ agents.box_id.
- Xóa box dọn schedules có creator hoặc target nằm trong box, gồm root-created schedules target representative. Xóa root đóng toàn bộ schedules thuộc root.

Không agent owner-membership gate. Agent giữ lịch và quyền riêng khi human owner rời workspace; quyền human quản lý vẫn theo graph hiện tại.

## 4. State ownership

| Owner | Giữ gì |
|---|---|
| schedules SQL | id, creator_agent_id, target_agent_id, title, content, type, spec, paused, deleted_at, created_at |
| Native Schedule schedule/{id} | Timing, overlap/catchup policy, paused state và start delivery workflows |
| ScheduleChanges schedule-changes/{id} | Serialized commands/pending native effect và rollover; không mirror definition history |
| Agent inbox | Committed occurrence message và nominal scheduled_at |
| Native saver/Agent workflow | Agent tiếp nhận và xử lý input; không chạy timer schedule |
| idempotency_keys SQL | Finalized mutation result theo caller/method/key/hash, không pending journal |

SQL là desired product definition. Native Temporal là execution authority. Nếu native apply chưa ACK, mutation còn pending; không nói SQL+Temporal atomic. Reads vẫn có SQL definitions khi Temporal preview lỗi. Không thêm sync_state/status/version fields để làm reconciliation framework.

## 5. ScheduleChanges: một coordinator cho mỗi schedule

Commands create/edit/pause/resume/delete đi qua cùng native Update-with-Start và change lock. Hai activities đã có:

- save_schedule_change (Local): authorized scope/target/liveness + finalized receipt/hash check; persist canonical desired definition. Metadata-only edit finalize receipt cùng SQL transaction.
- apply_native_schedule (Effect): native create/update/pause/delete/backfill cần thiết; ACK xong finalize serialized response receipt trong SQL transaction ngắn.

```text
change(command):
  trong change lock:
    canonical = normalize(command, workflow.now())
    saved = await save_schedule_change(canonical)
    nếu finalized receipt: return previous result
    nếu có native effect: await apply_native_schedule(canonical, saved)
    return applied result

main:
  chờ delete hoặc native rotation suggestion
  đóng admission trên execution cũ, drain handlers
  delete thì return; nếu không Continue-As-New với IDs
```

Giữ lock qua native effect để edit sau không vượt edit trước; không SQL transaction/SQL lock qua network. Lịch khác và inference vẫn hoạt động. Transient dependency error dùng native activity retry. Không optimistic success rồi best-effort signal hoặc background resync.

Canonical pending command thuộc Temporal history. Crash sau SQL/native effect nhưng trước receipt thì replay cùng command, apply idempotently, finalize trước command sau/CAN. Duplicate cùng key khác raw intent conflict; hash không bao gồm timestamp mới sinh khi retry. Finalized old command qua CAN trả receipt cũ, không apply definition cũ lên edit mới. Không processed-ID set hoặc permanent effect ledger riêng.

Native Update duplicate handling chỉ có trong execution; SQL receipt dùng cùng sáu fields như Platform/LetFS để giữ behavior qua CAN. Guarantee trong retention đã cam kết; receipt retention vô hạn theo resource lifetime vẫn là đề xuất của schema, không suy ra core file receipts vô hạn.

## 6. Native apply theo loại thay đổi

| Thay đổi | Effect |
|---|---|
| Create | Create native Schedule, action chỉ mang root/schedule IDs |
| Title/content-only edit | SQL và finalized receipt; không gọi native Schedule API |
| Type/spec/end edit | Apply native spec canonical mới |
| Pause/resume | Apply native paused state, không reanchor interval hoặc đổi relative at |
| Delete | SQL tombstone trước, native delete sau; NotFound là đã xóa |

Không so semantic equality toàn bộ server-expanded ScheduleSpec để đoán command có đổi timing không. Request fields/canonical command đã cho biết effect nào cần chạy. Native handle update dùng SDK update semantics; chỉ gán fields owning mutation cần thay, không reset native runtime info/counters. Không hai nhánh HTTP/tool apply khác nhau.

At chỉ có đúng một calendar match nên không cần limited_actions/remaining_actions. Sau native ACK, nếu at đã tới và không paused, create/timing edit/resume dùng native backfill (at-1s,at]. Không direct-start delivery hoặc vòng wall-clock recheck để tự làm scheduler. Native tick và backfill đều tạo cùng nominal occurrence identity; duplicate delivery executions có thể xảy ra nhưng inbox chỉ có một message. Title/content-only edit không backfill; resume cùng at đã giao cũng không tạo message mới.

At đã chạy không có SQL completed flag. Nếu muốn chạy lần nữa thì đổi at sang nominal instant mới hoặc tạo schedule mới; resume không có nghĩa rerun. Native auto-cleanup expired schedule không xóa SQL definition; metadata-only edit không recreate. Explicit timing/resume operation xử lý native NotFound bằng cùng canonical create/apply/backfill path khi cần.

Recurring interval/calendar không backfill toàn bộ thời gian pause khi resume. Giữ anchor/spec và native future matching. Temporal server outage dùng server-configured catchup window, không custom catchup loop. Python SDK 1.35.0 mô tả default hiện tại của server là một năm; giá trị thực thuộc config/deployment, không là promise giữ mọi tick một năm.

## 7. ScheduleDelivery và inbox

Native Schedule action start workflow ScheduleDelivery trên queue orchestration; mỗi occurrence workflow ngắn:

```text
đọc schedule ID và TemporalScheduledStartTime từ native start metadata
snapshot = await load_schedule_occurrence
nếu schedule paused/deleted hoặc root/target/box inactive: return skipped
message ID = stable UUID(schedule ID, canonical UTC nominal time)
await deliver_input bằng Update-with-Start của Agent
return committed receipt hoặc inactive skip
```

load_schedule_occurrence là Local Activity thứ ba của scheduler; deliver_input là bridge dùng chung. Không chờ inference/tool chain. Không SQL row riêng cho execution, không workflow mỗi retry và không temporal child workflow cho model call.

Authorized scope và occurrence identity được kiểm trước duplicate lookup. Nếu message đã admit thì trả original row, không dựng lại body từ definition mới rồi conflict. Occurrence chưa admit lấy bounded content snapshot khi load; admission kiểm lại source/root/box/target trong cùng INSERT transaction. Không dùng actual start/worker clock làm message identity; không drift khi delivery bị chậm hoặc workflow retry.

Pause/delete chỉ chặn occurrence chưa commit. Message đã commit không bị retract; timing edit cũng không hủy deliveries đã start. Content edit áp dụng cho snapshots load sau đó, không sửa body inbox cũ. Không revision/generation protocol để thu hồi mọi tick đang bay.

Pause toàn Leta chỉ dừng agent execution; scheduled messages vẫn có thể vào inbox và đợi resume. paused của từng schedule mới đóng source đó. Hai controls có mục đích khác nhau, không fanout native pause chỉ vì root đang nghỉ.

## 8. Overlap, nhiều năm và tải

Giữ BUFFER_ONE như archive: khi delivery trước chưa xong, native chỉ giữ thêm một start. Các tick sau có thể bị bỏ/coalesce; đây là scheduling reminders/instructions, không guaranteed accounting của mọi interval. Không BUFFER_ALL backlog vô hạn hoặc sửa thành một task queue engine khác.

Overlap chỉ bao thời gian ScheduleDelivery giao inbox. Model chạy một giờ không khóa native schedule một giờ; ticks sau vẫn vào inbox khi delivery đã ACK. Agent inbox/context có budgets theo runtime, scheduled input không bypass admission/compaction. Native Schedule tồn tại độc lập worker; không loop sleep cả năm trong Python.

ScheduleChanges Continue-As-New khi native đề nghị và handlers đã drain; không lifetime timeout, không chờ schedule hết việc. Native timing không cần migrate qua CAN. ScheduleDelivery finite, retry native activities; permanent permission/liveness failure là skip/failure rõ ràng, không retry revoked resources vô hạn. pause_on_failure không tự tắt lịch vì một delivery failure; giữ native policy như archive.

## 9. List, upcoming và calendar

Các capabilities giữ: schedule_create, schedule_list, schedule_get, schedule_update, schedule_delete và calendar occurrence query. Pause/resume là update paused, không thêm workflow hoặc transport riêng. Tools và HTTP API dùng cùng feature functions; cụ thể hóa routes/DTO/errors trước code API theo streaming.md và plan, không là decision kiến trúc còn mở.

List/get lấy SQL definitions bằng keyset/filter target/box. get có bounded upcoming preview từ native describe; preview unavailable thì vẫn trả definition và trạng thái unavailable, không biến thành upcoming=[] như thể chắc chắn không có lịch.

Calendar là dự báo nominal times, không execution log hoặc guarantee đã chạy. At lọc trực tiếp canonical time; recurring gọi native ListScheduleMatchingTimes, không tự tính cron. Giữ bounds đã có: (start,end], tối đa 366 ngày, 32 definitions, 32 native RPCs và 1000 results. Native pagination giữ exact last instant làm exclusive start, không +1s làm mất occurrence. Vượt budget thì yêu cầu hẹp range/filter, không silently truncate hoặc thêm pagination state table.

Paused definitions có thể được hiển thị cùng paused flag để UI giải thích pattern; không coi đó là actual delivery. deleted schedules không forecast. Trong lúc mutation còn pending, SQL desired và native preview có thể tạm lệch; ACK applied chỉ sau native effect. Forecast failure không che definitions và không tự tạo/rearm schedule để phục vụ read.

## 10. Khác archive ở đâu

| Phần | Archive | Bản viết mới |
|---|---|---|
| Architecture | SQL + native Schedule + hai workflow types | Giữ |
| One-shot | limited-actions counters, spec_key normalization, wall-clock checks, direct-start past-at | Exact calendar + native backfill + inbox dedupe |
| Metadata edit | Đi qua apply_temporal_schedule và spec comparison | Chỉ SQL/receipt, không native effect |
| Command retries | Workflow Update cùng HTTP reservation/completion mechanics cũ | Canonical command trong history, finalized core-shaped receipt qua CAN |
| Rows | type trong spec, end_at/box_id/leta_id/updated_at mirrors | Schema đã chốt, type column, end trong spec, joins qua agents |
| Timing normalization | requested_at từ từng caller path | workflow.now một authority, canonical command giữ qua retry |
| Delivery | Native time → stable message → inbox | Giữ; duplicate trả body đã admit dù definition đã edit |
| Calendar | Native preview và bounded result | Giữ; không custom forecast engine |

Scheduler không đổi kiến trúc Temporal tổng; inventory hiện sáu workflow types / 22 activities / ba queues một worker process sau workspace cleanup. Ba activities scheduler là save_schedule_change, apply_native_schedule, load_schedule_occurrence; delivery dùng chung deliver_input. Code mới từng dòng, không port classes/fixtures/helpers từ archive.

## 11. Verification cần thiết

Viết mới focused checks, dùng shared dependency environment:

1. Small pure-function check cho canonical relative-at/interval anchor/calendar mapping và invalid basic input. Không test toàn bộ Temporal range/DST engine.
2. Native smoke cho exact at, interval, calendar; past-at/backfill cho cùng một inbox message; metadata edit/resume đã consumed không rearm. Đây là native Schedule behavior nên không chỉ time-skipping workflow unit test.
3. Crash/retry command trước final receipt và old retry sau CAN không ghi đè definition mới; occurrence retry sau content edit trả original delivery.
4. Pause/delete trong khoảng load-to-admit chặn delivery mới; box cleanup dọn cả root-created target schedules; root execution pause giữ inbox inputs để resume.

Không per-type × every transport × every failure matrix, dedicated stack từng test, paid model calls hoặc test run một năm. Kiểm native SDK calls/receipt boundary thật, không tests mirror exact helper/class structure.

## 12. Nguồn và giới hạn

Đã đọc sáu archive modules: [definitions/compiler/calendar](../../archive/2026-11-11/apps/leta/src/leta/schedules.py), [runtime tools](../../archive/2026-11-11/apps/leta/src/leta/runtime/schedules.py), [workflows](../../archive/2026-11-11/apps/leta/src/leta/temporal/schedules.py), [activities](../../archive/2026-11-11/apps/leta/src/leta/temporal/schedule_activities.py), [DTOs](../../archive/2026-11-11/apps/leta/src/leta/temporal/schedule_types.py), [HTTP](../../archive/2026-11-11/apps/leta/src/leta/http/schedules.py), tổng 1.125 lines, cùng selected store/domain operations. Chỉ tham khảo behavior, không copy implementation/tests.

Native semantics đối chiếu [Temporal Python SDK 1.35.0 source](https://github.com/temporalio/sdk-python/blob/1.35.0/temporalio/client/_schedule.py) cho ScheduleSpec/Calendar/Policy/State/Backfill và [official Schedule docs](https://docs.temporal.io/develop/python/schedules). Không install dependency hoặc mở runtime mới.

Chưa triển khai app Leta, chạy native Schedule/backfill/retention smoke hoặc benchmark. BUFFER_ONE không giữ mọi tick; SQL/native apply không atomic; mutation receipt guarantees theo retention. Không sửa shared contracts, database, Zed hoặc archive source trong lượt đề xuất này.
