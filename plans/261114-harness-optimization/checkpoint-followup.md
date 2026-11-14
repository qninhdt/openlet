# Rà soát checkpoint và khảo sát harness bổ sung — 2026-11-14

Đây là audit chỉ đọc tiếp theo của `research.md`, giữ nguyên bằng chứng tại thời điểm khảo sát. Sau đó user đã duyệt các bổ sung1–4; xem [implementation.md](implementation.md) cho phần sửa, các correction sau review và checks. Audit này không phải kết quả chạy lại agent sau tối ưu.

## Phạm vi và kết quả kiểm tra trạng thái

Đọc lại database bằng connection read-only và native AsyncPostgresSaver: 49 agent (14 Leta, 35 Leti), 47 latest checkpoint, 2.058 messages, 6.723 history entries, 159 runs. Cả database export và từng checkpoint giống byte-for-byte bản audit trước; không có hoạt động mới để coi là kết quả sau tối ưu.

Kiểm tra cấu trúc trên toàn bộ 47 checkpoint và đối chiếu history/inbox: giải mã thành công, không pending writes, duplicate message IDs, orphan tool results hoặc missing projection IDs. History seq liên tục. Mọi agent có checkpoint đều đã nhận hết inbox vào context; điều này không chứng nhận đã xử lý xong nhiệm vụ. Hai agent chưa có checkpoint là QA Verifier và Permission regression, đã ghi rõ trong bảng coverage.

159 runs gồm 148 completed, 7 cancelled, 4 paused; không running/failed. Năm tool calls chưa có result đều thuộc điểm pause/cancel/archive đã xác định trước. Không tự replay các mutation để làm snapshot đẹp. Không còn invalid_tool_calls trong latest snapshot; không thể suy ra các snapshot đã prune chưa từng có lỗi parse.

Đọc summary/trạng thái cuối của toàn bộ agent, kiểm tra metadata tool errors và các chuỗi đáng ngờ trong history. Không tái tính tất cả dữ liệu nghiệp vụ nguồn. Báo cáo từng agent ở cuối tài liệu; raw evidence/scripts ở `/tmp/openlet-journeys/checkpoint-audit-followup/`.

## 1. Mới — P1: response bị cắt vẫn thực thi mutation từ arguments được phục hồi một phần

Bằng chứng: Leti Trưởng nhóm rà soát Bình An `7f5849a5-ecda-57b5-b650-827feaae703d`, checkpoint AI message 1: `finish_reason=length`, output usage 16.000, raw arguments của `file_write` là JSON chưa đóng. Native AIMessageChunk dùng `parse_partial_json`, tạo lại args hợp lệ với `path` và `content` 31.447 ký tự. Content kết thúc giữa hàng M1: `**BA-02 và BA-12 có`.

History seq211 ghi call này, seq212 trả success path. Sau đó agent compact (213), dùng file_edit (214–215) bổ sung phần thiếu và kiểm tra file (216–219). Ca cụ thể hồi phục; không khẳng định mọi lần truncated đều an toàn. Đây là một trường hợp được giữ trong 975 AI messages của latest snapshots, không phải tần suất trên toàn bộ lịch sử đã prune.

Đây là lỗi harness tích hợp với partial parsing, không phải lỗi thiếu field thông thường và khác issue33504 (invalid-only call). Offline đã dựng lại bằng AIMessageChunk: raw JSON invalid, parsed args lại qua schema của file_write; không thực thi tool trong probe.

Đề xuất nhỏ: trước dispatch, khi AI response có finish_reason=length, trả named ToolMessage error cho các tool calls thuộc response đó và không thực thi chúng. Giữ call/result IDs, cho native agent loop nhận feedback để tự chia nhỏ và gọi lại. Đặt trong middleware hiện có; không tự sửa JSON, không retry engine, không thêm model call ngoài loop. Test quan trọng: một file đang có không được thay đổi bởi truncated overwrite. Chính sách chặn cả batch có thể từ chối một call đã hoàn chỉnh đứng trước call bị cắt, nhưng tránh phải đoán call nào đáng tin; Pi dùng chính sách này. Chưa implement.

Pi có `failToolCallsFromTruncatedMessage` cho cả batch. OpenCode phân biệt malformed/incomplete input với kết thúc length và ghi lỗi rõ; không đồng nhất hai implementation.

## 2. Mới — P2: serializer gửi request và serializer đếm context không giống nhau

`ExecutionModel.count_tokens()` dùng langchain-core `convert_to_openai_messages`. ChatLiteLLM 0.11.2 đang cài dùng serializer riêng `_convert_message_to_dict`:

- Generic conversion bỏ `additional_kwargs.reasoning_content`; ChatLiteLLM gửi trường này. Có 328/975 AI messages giữ reasoning_content, tổng 549.048 ký tự trong 47 working contexts.
- Generic conversion serialize tool arguments với ensure_ascii=False; ChatLiteLLM dùng json.dumps mặc định ensure_ascii=True. Tiếng Việt trong arguments lịch sử thành chuỗi literal \u.... Đây là JSON string lồng bên trong request, không chỉ là cách HTTP hiển thị Unicode: provider phải nhận và đọc argument string có escape trừ khi gateway chủ động parse/serialize lại.
- LiteLLM proxy client transformer giữ nguyên messages. Chưa gọi provider để chứng minh endpoint Vilao cuối cùng có normalize/count các trường như local estimator hay không.

Offline cùng tokenizer LiteLLM và cùng message data, chỉ đổi representation:

| Working context | Generic estimate | SDK representation | Nếu arguments giữ Unicode | Phần reasoning ước tính |
| --- | ---: | ---: | ---: | ---: |
| Bình An — trưởng nhóm rà soát | 34.574 | 58.341 | 35.428 | 878 |
| Mộc Trà — vận hành | 31.561 | 69.211 | 55.839 | 24.337 |
| Mộc Trà — tài chính | 32.256 | 68.288 | 60.041 | 27.848 |

Các số là working messages, chưa cộng system/tools; không phải billed provider tokens hoặc benchmark tiết kiệm tiền. Toàn bộ snapshots: ước tính phần escaping tăng 248.439 tokens và phần reasoning 177.260 tokens. Không cộng chúng thành một request, không coi đây là cost đã chi hoặc số chắc chắn sẽ tiết kiệm.

Đối chiếu lại prefix cuối của root Bình An với usage đã lưu: provider input22.011; counter hiện tại18.784; estimate theo SDK representation22.217 (lệch khoảng0,94%). Các prefix sớm hơn vẫn lệch, nên đây chỉ là một bằng chứng nhất quán, không phải calibration đã chứng minh mọi request.

Hai vấn đề có tác động khác nhau: escaping là overhead có thể tránh; reasoning cần được đếm đúng nếu thực sự replay, không được tự xóa vì một số model yêu cầu nó trong tool loop. Guard/trigger/tail đang dùng representation thấp hơn đường gửi, nên chỉ sửa prompt/tail chưa giải quyết hết độ lệch. Sửa counter có thể làm compact sớm hơn; giảm escaping mới là giảm dữ liệu thực gửi.

Đề xuất: thống nhất token estimation với serialization thực tế của SDK ở một chỗ, giữ native SummarizationMiddleware; ưu tiên sửa Unicode serialization ở dependency nếu có public option/upstream fix. Phiên bản đang cài chưa thấy option công khai cho ensure_ascii. Không monkeypatch site-packages, không fork toàn SDK, không import private function vào production chỉ để có benchmark đẹp. Cách sửa dependency là điểm cần chọn khi triển khai; chưa thay pin hay thêm wrapper trong audit này.

Pi giữ reasoning theo same model và serialize arguments bằng JSON.stringify; OpenCode scope native signatures theo model/provider; OpenHands có send_reasoning_content; Hermes tính riêng replayed reasoning. Bài học phù hợp là count what is sent, không copy bộ provider compatibility của họ vào Leta.

## 3. Mới — P2: timeout trở thành tool error rỗng

Release QA `7f61a392-6083-53a7-be66-52fb3aabd1e7`: history76 gọi exec_python, history77 sau khoảng30 giây trả name=null, text="". `shell()` dùng asyncio.timeout(30); TimeoutError là OSError, ToolEffects bắt rồi dùng str(error), vốn rỗng. Native checkpoint cũ của boundary này đã prune nên không khẳng định traceback lịch sử còn nguyên; thời gian và code path khớp timeout, khác script in ra stdout rỗng thành công.

Đề xuất sửa tại handler hiện có: TimeoutError trả lỗi rõ command exceeded execution time limit, có name/status/call ID. Nếu có thể đã ghi file trước timeout thì nói outcome có thể chưa đầy đủ, kiểm tra file trước khi chạy lại. Không tăng timeout mặc định hoặc tự retry mutation. Đây là bổ sung nhỏ cho fix name/status đã chốt.

## 4. Mới — P2: public history của image read mất ý nghĩa kết quả

12 tool-result history entries có text rỗng: 11 là file_read ảnh, 1 là timeout ở mục3. Sáu checkpoint cũ còn native image_url blocks; projection chỉ lưu message.text nên ảnh thành text rỗng. Những lượt ảnh mới có thể đã compact khỏi working context, nhưng history calls còn exact source paths.

Không phải model không nhìn thấy ảnh: native ToolMessage còn image block. Hạn chế ở public history/replay và history_read: người đọc không biết kết quả ảnh ngoài việc quay lại tool call. Không được giải quyết bằng lưu/stream base64 vào history.

Đề xuất tối thiểu khi làm projection: giữ authorized file reference và nhãn image preview trong public tool result, dựa trên call/path hoặc existing node metadata; client dùng đường đọc file sẵn có. Không thêm blob store/table/snapshot ảnh bất biến. Reference không hứa ảnh không đổi hoặc còn đọc được sau revoke/delete. Cần kiểm tra client contract trước khi thêm shape; chưa implement.

## 5. Những vấn đề cũ vẫn còn, chưa được tối ưu ở runtime

| Vấn đề | Trạng thái hiện tại |
| --- | --- |
| file_read mất nội dung do cap ký tự rồi cursor +200 | Chưa sửa; 104 results trong năm journeys. User đã chốt line window + token budget + continuation chính xác. |
| Shell chỉ giữ đầu stdout/stderr, mất phần cuối/full output | Chưa sửa; user đã chốt head/tail và bounded overflow capture qua VFS. |
| Error thiếu name, projection thiếu status | Chưa sửa; 25 nameless results, 2.754 result rows không có status. Không dùng grep chữ error để tính success rate. |
| Tail0 và summaries phình, đọc lại nhiều | Runtime vẫn policy cũ; keep_tokens8192 và prompt summary gọn đã được chốt nhưng chưa rollout. |
| Monty không hỗ trợ nhiều CPython APIs | Runtime limitation; 60 lỗi thuộc các nhóm đã audit trên18/19 agents hiện tại. Prompt nói rõ capability và cách thay thế đã chốt; không giả lập stdlib. |
| Duplicate Python tool | exec_python vẫn tồn tại; xóa tool riêng, giữ Python qua exec_shell đã chốt, chưa code. |
| Vòng review và handoff dài | Trong năm journeys có60 large file_read results,6 shell,5 inbox_read trùng nguyên văn lần trước. Có thể có lý do hợp lệ, không coi tất cả là lỗi. Handoff dài nhất10.899 ký tự; hai specialists gửi lead khoảng10k mỗi tin. Giữ conclusion + evidence path thay vì report dump như prompt draft. |

## 6. Kết quả nghiệp vụ còn mở và multi-agent

- Release: root/engineer/QA đã trao đổi được, báo cáo điều kiện phát hành và giới hạn staging được nêu. Không có staging replay trên bản sửa, đúng giới hạn quyền; không đổi thành PASS production.
- Campaign: các specialists giao kết quả và root đã xác nhận hủy lịch; quyết định nghiệp vụ còn cần người dùng không phải lỗi inbox.
- Procurement: communication graph từ chối route sai rồi agent chuyển đúng tuyến; một technical reviewer bị cancel/archive, các báo cáo được lưu/đính chính. Không suy ra mọi kỹ thuật đã được xác nhận vì các điều kiện ADF/LTE còn mở.
- Finance: hai Leti bị pause trong vòng rebuild cuối, accountant còn call chưa có result. Root đã gửi2.2 và công bố thiếu second independent rebuild; chưa thể coi vòng đối soát cuối hoàn tất.
- Continuity/Bình An: bản1.4 vẫn có lỗi áp dụng nguồn: nhầm người có SCAN với người đã đào tạo; phương án chờ ở Phú Lâm lúc đóng cửa chưa có xác nhận quyền/người quản lý. Summary vẫn giữ các ràng buộc cần thiết nên chưa có bằng chứng đổ cho compaction làm quên. Đây là lỗi reasoning/tổng hợp nghiệp vụ, prompt/source checks có thể giúp nhưng không đảm bảo chữa model.

Các agent thực sự giao tiếp và hồi phục; không có bằng chứng inbox transport làm mất message trong latest snapshots. Cursor consumed không tương đương đã trả lời, completed run không tương đương task passed.

## 7. Khảo sát bổ sung cả năm harness — chọn ít thứ hữu ích

| Harness | Đã đọc thêm | Áp dụng hoặc không áp dụng cho Leta |
| --- | --- | --- |
| Codex | parallel.rs/registry.rs, base instructions, compact.rs image handling | Có parallel vs exclusive gate theo tool; hướng dẫn tránh reread sau patch thành công. Chưa cần mang gate sang vì snapshot không có same-path write batch; giữ existing permission/version semantics. |
| Pi | agent-loop.ts, file-mutation-queue.ts, edit.ts/edit-diff.ts, api/openai-completions.ts, transform-messages.ts | Truncated call guard có case thật nên đề xuất thêm. Per-file queue và fuzzy/edit compatibility chưa có bằng chứng cần copy. Edit result model nhận acknowledgement ngắn, diff nằm details: không tuyên bố Pi đẩy full diff vào LLM. |
| OpenCode | runner/to-llm-message.ts, publish-llm-event.ts, max-steps.ts, retry.ts | Phân biệt incomplete input/length, model-scoped metadata. Delta batching và max-step prompt là lựa chọn của họ, không tự thay streaming/retry/termination đã chốt của Leta. |
| Hermes | tool_executor.py, tool_dispatch_helpers.py, tool_guardrails.py, replayed_reasoning.py | Có bounded output, conflict-aware batching, repeated-call warnings/stops. Bộ guardrails lớn và dễ false positive khi kiểm sau edit; không bê sang trước khi sửa output/tail và đo lại. |
| OpenHands SDK | llm/message.py, conversation/stuck_detector.py, file_editor/definition.py | Typed reasoning replay và file resource locks; stuck detector xét chuỗi action/results. Không thêm stuck engine, file locks xuyên service hoặc edit undo layer chỉ để giống họ. |

17 checkpoint AI batches có shell/Python hoặc nhiều mutation cần xem concurrency; không có batch file_edit/file_write trùng exact path. Không đủ kết luận không có race trong snapshots đã prune hay từ shell scripts, nhưng chưa có cơ sở thêm distributed locks. Independent reads vẫn nên parallel; same-file dependent changes phải sequential như prompt đã chốt.

Giữ native agent loop, native tool validation, existing cache/VFS và permission boundary. Không thêm task planner service, automatic reviewer, model aliases chữa hallucination, provider retry thứ hai, memory ledger hoặc automatic compaction retry. Đây không phải audit chỉ tập trung vào steered messages: đã kiểm prompt/context, compaction, serialization, read/edit/write/exec, errors, delegation/inbox, completion/waiting, concurrency, projection/replay và retry ownership.

## 8. Thứ tự đề xuất triển khai sau user review

1. Ngăn truncated tool calls thực thi; trả timeout có ích và giữ name/status. Đây là correctness trước token tuning.
2. Giải quyết serializer/counter mismatch; đo current root prefix với provider usage hiện có, không inference mới. Sửa Unicode ở dependency theo cách được review, không vá SDK ngầm.
3. Làm các thay đổi đã chốt trong research.md: read/history/output, tail, bỏ exec_python riêng, Markdown prompts/composition. Với image projection chỉ thêm reference tối thiểu theo public contract.
4. Offline focused tests và strict Pyright/Ruff. Sau khi được cho phép chạy inference mới dùng một task/handoff nhỏ để đo completion, reread, context, compaction và chi phí. Chưa bung lại5 journeys.

Không có cơ sở tuyên bố prompt mới sẽ chữa hết lỗi hoặc mọi output nghiệp vụ đã đúng. Không kiểm Grafana/Langfuse live, provider bill/normalization, full frontend rendering hoặc tất cả dữ liệu nguồn trong audit này.

## Coverage từng agent

Bảng này ghi cấu trúc checkpoint và trạng thái dừng, không gắn nhãn PASS nghiệp vụ cho từng agent.

| Nhóm | Agent | ID | Messages | Tool errors giữ trong checkpoint | Trạng thái |
| --- | --- | --- | ---: | ---: | --- |
| older trial | Fulfill Allocation Release Review | `1124cf52-6849-44a2-abe0-fbed5dee7598` | 54 | 4 | call chưa có result tại pause/cancel/archive |
| older trial | Release Lead | `caa708b2-9415-59cf-8211-5a401f1a955f` | 55 | 7 | latest pairing/projection nhất quán |
| older trial | QA Verifier | `d915c9d7-27f7-5282-b8fe-334d30905535` | — | — | chưa có checkpoint |
| older trial | Allocation Engineer | `b8b3fe8b-5b12-5a36-b950-2abf6c593cff` | 51 | 9 | call chưa có result tại pause/cancel/archive |
| older trial | Requests 2.32.5 integration and release handover | `119d2fab-b45a-4ee5-8167-e5b1a6de17bb` | 33 | 2 | latest pairing/projection nhất quán |
| older trial | Beacon - continuity tabletop | `6f03ce10-0c72-4c53-a653-c50cb56d1bf5` | 65 | 2 | latest pairing/projection nhất quán |
| older trial | risk-reviewer | `d9e9fe6c-445f-5433-a18f-17b0cde85efb` | 31 | 2 | latest pairing/projection nhất quán |
| older trial | operations-planner | `4928db67-d794-5f83-be95-754362d37fb7` | 34 | 0 | latest pairing/projection nhất quán |
| older trial | coordinator | `0c60add3-9810-5e74-ac09-4ecbf99e159b` | 53 | 2 | call chưa có result tại pause/cancel/archive |
| release | Fulfill Allocation Release Review — corrected baseline | `738086f7-04b3-4d29-9114-63411ac18839` | 59 | 4 | latest pairing/projection nhất quán |
| release | Kỹ sư Allocation | `b0007d0f-54d7-5aab-95a4-714f0b850da2` | 51 | 1 | latest pairing/projection nhất quán |
| release | QA Độc lập | `7f61a392-6083-53a7-be66-52fb3aabd1e7` | 58 | 1 | latest pairing/projection nhất quán |
| older trial | Juniper - release readiness | `74e992f5-ef62-42bc-925b-a58e0a78aa90` | 82 | 4 | latest pairing/projection nhất quán |
| older trial | release | `f4fb8303-1613-5378-babe-51abe48d489a` | 72 | 3 | latest pairing/projection nhất quán |
| older trial | engineer | `038fec89-c8ba-51d4-8d36-f4e0e02407c2` | 49 | 4 | latest pairing/projection nhất quán |
| older trial | qa | `ca134e03-ee4a-5f79-9cb1-67d2011ded83` | 64 | 6 | latest pairing/projection nhất quán |
| finance | An Phú Finance | `7d5fd95f-c07d-4d9d-bec7-865eb2075f30` | 42 | 0 | latest pairing/projection nhất quán |
| finance | Người rà soát độc lập | `17b6beba-08f0-5b16-b429-37dbee36d3c8` | 37 | 0 | pause vòng rebuild cuối |
| finance | Kế toán đối soát | `ef4cd800-aeea-52e2-a38d-528c927e1e02` | 26 | 1 | call chưa có result tại pause/cancel/archive |
| older trial | Cedar - weekend launch | `a547ea14-6ef3-4764-8768-6293e460d995` | 113 | 4 | latest pairing/projection nhất quán |
| older trial | inventory | `d27778bd-d93c-531a-9293-234032d9d85e` | 24 | 2 | latest pairing/projection nhất quán |
| older trial | finance | `adad203e-852c-589b-82df-9953575a5088` | 26 | 2 | latest pairing/projection nhất quán |
| older trial | lead | `0e74b2fb-fe44-5df1-b730-bbf80e6a529a` | 58 | 5 | latest pairing/projection nhất quán |
| older trial | Cloud acceptance assistant | `bd8065c3-2b5c-4b4e-acb5-052f5db4bb18` | 24 | 0 | latest pairing/projection nhất quán |
| older trial | Researcher | `d9deae4c-2ee3-56b4-ac40-44c9b85820f7` | 8 | 0 | latest pairing/projection nhất quán |
| campaign | Mộc Trà — phương án quà thành viên | `c55dcdc2-4a85-4cbf-9be0-1c7ffa0ad7e9` | 56 | 0 | latest pairing/projection nhất quán |
| campaign | Trưởng nhóm rà soát | `02e06919-c71d-575f-9dcc-585a37f3c660` | 17 | 0 | latest pairing/projection nhất quán |
| campaign | Phụ trách vận hành | `198c3d7d-b3e4-5e41-8291-a34fe8ccc618` | 32 | 0 | latest pairing/projection nhất quán |
| campaign | Kiểm tra tài chính | `c27e0646-7b88-54eb-84db-ff30279b8121` | 34 | 0 | latest pairing/projection nhất quán |
| older trial | Permission regression | `c5c805fb-45f4-47af-9c6d-d550bd3530c9` | — | — | chưa có checkpoint |
| older trial | Harbor - monitor procurement | `e256f744-44c2-4d51-bd3a-eb367d9ff602` | 91 | 3 | latest pairing/projection nhất quán |
| older trial | Commercial lead | `478c81bd-41e3-577c-8178-2d338c10ed02` | 35 | 4 | latest pairing/projection nhất quán |
| older trial | Commercial analyst | `cea70642-a51f-5c4e-af04-be0897edc50b` | 28 | 5 | latest pairing/projection nhất quán |
| older trial | Assurance lead | `bda5315b-6294-5cd8-9e45-d74da23d23fb` | 34 | 3 | latest pairing/projection nhất quán |
| older trial | Specification and risk checker | `e2b69f90-7a77-50f4-88d0-c0ac289f6bf4` | 26 | 5 | latest pairing/projection nhất quán |
| older trial | Northstar - November close | `e71b160c-e8ff-4317-ab05-bc427800fbad` | 141 | 6 | latest pairing/projection nhất quán |
| older trial | reconciler | `0c7dd193-f348-5a9f-832e-2f0411c902d4` | 46 | 2 | latest pairing/projection nhất quán |
| older trial | policy | `32ef0208-c6a6-5288-8627-493fc749b000` | 26 | 4 | latest pairing/projection nhất quán |
| older trial | lead | `3e05f508-9b98-59f2-abe6-352636818600` | 43 | 6 | latest pairing/projection nhất quán |
| older trial | reviewer | `7746161e-1401-5c0c-ab89-e38167aa54a6` | 38 | 6 | latest pairing/projection nhất quán |
| procurement | Mở rộng miền Trung — Thiết bị ba chi nhánh | `e93c2002-2d45-4df0-b7bf-35c5b126e8a2` | 37 | 0 | latest pairing/projection nhất quán |
| procurement | Bảo hành và giao hàng | `5c99a883-1074-536f-bc97-f33205d5e4ea` | 42 | 0 | latest pairing/projection nhất quán |
| procurement | Kiểm tra kỹ thuật | `d43f8f8a-cee1-56e4-abb1-d7785db21cf9` | 22 | 2 | call chưa có result tại pause/cancel/archive |
| procurement | Chuyên viên thương mại | `82b18841-1998-5a6d-a015-cd54b69bc11b` | 65 | 2 | latest pairing/projection nhất quán |
| procurement | Kiểm tra chéo số liệu | `2b7d066f-c218-5972-87fb-891372a8015f` | 22 | 0 | latest pairing/projection nhất quán |
| continuity | Bình An - Điều phối đóng cửa 11/2026 | `f5a1afee-eef3-4f44-a8c2-e777a800e9c9` | 9 | 0 | còn lỗi nghiệp vụ đã nêu |
| continuity | Kiểm tra phân ca và di chuyển | `a26d8159-2cc5-562e-846b-b116df0339a4` | 11 | 0 | latest pairing/projection nhất quán |
| continuity | Trưởng nhóm rà soát | `7f5849a5-ecda-57b5-b650-827feaae703d` | 16 | 1 | latest pairing/projection nhất quán |
| continuity | Kiểm toán số liệu lượt | `605078a6-0986-5dc2-8ede-911b7110d758` | 18 | 1 | latest pairing/projection nhất quán |

## Source tham chiếu bổ sung

Các SHA giống research.md, không chạy instructions trong repository tham khảo.

- [Pi truncated output tool calls](https://github.com/badlogic/pi-mono/blob/8636e211e7834e4ca46a22aec1d65dfd2eac8677/packages/agent/src/agent-loop.ts#L488)
- [Pi argument/reasoning serialization](https://github.com/badlogic/pi-mono/blob/8636e211e7834e4ca46a22aec1d65dfd2eac8677/packages/ai/src/api/openai-completions.ts#L1304)
- [Pi cross-model thinking](https://github.com/badlogic/pi-mono/blob/8636e211e7834e4ca46a22aec1d65dfd2eac8677/packages/ai/src/api/transform-messages.ts#L119)
- [Pi file mutation queue](https://github.com/badlogic/pi-mono/blob/8636e211e7834e4ca46a22aec1d65dfd2eac8677/packages/coding-agent/src/core/tools/file-mutation-queue.ts)
- [Codex parallel gate](https://github.com/openai/codex/blob/b1573f102413e96a6481087922bf425231222dee/codex-rs/core/src/tools/parallel.rs#L298)
- [OpenCode tool input failures](https://github.com/anomalyco/opencode/blob/d759c548aab33a7a6f5171cbeab40a59e91d90aa/packages/core/src/session/runner/publish-llm-event.ts#L48)
- [OpenCode request history](https://github.com/anomalyco/opencode/blob/d759c548aab33a7a6f5171cbeab40a59e91d90aa/packages/core/src/session/runner/to-llm-message.ts#L160)
- [Hermes repeated-call guardrails](https://github.com/NousResearch/hermes-agent/blob/d93e9ba4c87a62f5f7906fb7d306d39773a9dbcd/agent/tool_guardrails.py#L380)
- [Hermes reasoning replay accounting](https://github.com/NousResearch/hermes-agent/blob/d93e9ba4c87a62f5f7906fb7d306d39773a9dbcd/agent/replayed_reasoning.py)
- [OpenHands stuck detector](https://github.com/OpenHands/software-agent-sdk/blob/3c66af1d14d0a7fbe74b8dc4218412ec7a877b79/openhands-sdk/openhands/sdk/conversation/stuck_detector.py)
- [OpenHands reasoning serialization](https://github.com/OpenHands/software-agent-sdk/blob/3c66af1d14d0a7fbe74b8dc4218412ec7a877b79/openhands-sdk/openhands/sdk/llm/message.py#L335)

Evidence: database.json/inventory.json/analysis.json/deeper.json cho mọi agent; serialization.json/encoding.json cho local representation estimates; root-wire.json cho comparison với usage đã lưu. Probe scripts chỉ ở /tmp.
