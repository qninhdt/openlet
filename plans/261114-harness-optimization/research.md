# Leta harness optimization — research và đề xuất để review

Ngày 2026-11-14. Khảo sát source và thiết kế đã được user chốt sau khi review toàn bộ đề xuất, bao gồm các draft system prompt. Tài liệu giữ bằng chứng và đề xuất tại thời điểm nghiên cứu; tiến độ code, các correction sau review, Langfuse versions và checks mới nhất nằm trong [implementation.md](implementation.md). Các budget được chọn là baseline để kiểm chứng, không phải kết quả benchmark chất lượng. Không sử dụng skill. Không đụng phần LetFS ingestion đang sửa song song.

Khảo sát bổ sung sau khi chốt: [checkpoint-followup.md](checkpoint-followup.md) ghi fresh read-only audit toàn bộ49 agent và các phát hiện mới về truncated tool calls, serialization/token counting, timeout feedback và image history. User đã duyệt bốn bổ sung này trước khi triển khai.

## 1. Phạm vi và bằng chứng

Đã clone source Codex, OpenCode, Pi, Hermes Agent và OpenHands. OpenHands repository hiện trỏ phần agent/runtime sang `software-agent-sdk`, nên đã clone và đọc SDK đó cùng repository chính. Đọc implementation của system prompt, compaction, read/edit/write/execution, truncation, tool errors và subagent; không chỉ README. Không coi mọi feature trên HEAD là stable default hoặc thứ Leta cần mang sang.

Source và scripts nghiên cứu nằm tại `/tmp/openlet-harness-research/`. Checkpoint/history đã xuất ở `/tmp/openlet-journeys/checkpoint-audit/`. Pin source:

| Repository | Commit |
| --- | --- |
| openai/codex | `b1573f102413e96a6481087922bf425231222dee` |
| anomalyco/opencode | `d759c548aab33a7a6f5171cbeab40a59e91d90aa` |
| badlogic/pi-mono | `8636e211e7834e4ca46a22aec1d65dfd2eac8677` |
| NousResearch/hermes-agent | `d93e9ba4c87a62f5f7906fb7d306d39773a9dbcd` |
| OpenHands/OpenHands | `830c0459e2f6056ab81e020c22970e782ae1be75` |
| OpenHands/software-agent-sdk | `3c66af1d14d0a7fbe74b8dc4218412ec7a877b79` |

Các số token local dưới đây là ước tính bằng dependency LiteLLM đang cài. Usage provider mới là số đo provider thực sự báo; không gọi estimator là tokenizer chính xác của mọi deployment sau alias.

## 2. Leta hiện tại thực sự làm gì

### Ngân sách context và compact

Gateway `/model/info` khai báo DeepSeek hiện dùng: `max_input_tokens=65536`, `max_output_tokens=8192`. Code hiện đặt input guard tại `65536 - 8192 = 57344`, trigger native tại `floor(57344 * 0.8) = 45875`. Như vậy 65.536 là metadata gateway, không phải toàn bộ số token working messages có thể chiếm trước compact.

Root system prompt hiện khoảng 3.314 token, kèm 28 tool khoảng 4.538 token. Leti khoảng 3.129/4.075 token với 22 tool. Những số này chưa tính assignment và box context cụ thể. Compaction instruction khoảng 492 token. Prompt dài góp overhead nhưng không đủ để tự giải thích hàng chục lần compact.

`summary_max_tokens=2048` vừa được compile vào prompt vừa truyền vào model call qua `bind_tools(..., max_tokens=...)`; không chỉ là câu nhắc trong prompt. Tuy nhiên provider đã trả các summary dài hơn mục tiêu: trong một đoạn đã audit, summary dài 11.713–16.013 ký tự, ước tính khoảng 4.032–5.502 token local. Không thêm validator ép summary phải <=2048, không cắt chuỗi summary và không tiếp tục probe provider chỉ để chứng minh lại điều này. Giữ phân biệt giữa output budget yêu cầu và output provider thực hiện.

Native `SummarizationMiddleware` đang sở hữu trigger/cutoff/replacement. Custom callback chỉ tạo request cache-friendly: cùng system/model/effort và tool declarations, conversation prefix, thêm instruction cuối. Đây không phải một thuật toán không có tiền lệ: OpenCode cũng append instruction vào conversation để tận dụng prefix cache. Không cần thay bằng một agent loop hoặc compaction engine tự viết.

Native middleware còn xét usage `total_tokens` của AIMessage cuối, ngoài token estimate. Counter hiện đếm messages, guard đếm cả system/tools; cần diễn giải hai số nhất quán khi đo. Đối chiếu bốn request cuối trong checkpoint Bình An:

| Provider input | Local reconstructed input estimate |
| ---: | ---: |
| 11.110 | 8.685 |
| 15.335 | 12.848 |
| 19.118 | 16.488 |
| 22.011 | 18.784 |

Local thấp hơn khoảng 14–22% trong mẫu này. Đây chưa phải hệ số hiệu chỉnh chung: model tokenizer, tool serialization, context thực tế và reasoning forwarding đều có thể ảnh hưởng. Không tự nhân mọi token count với một hệ số suy ra từ bốn mẫu.

`models.py` đặt tên `context_window_tokens` cho `max_input_tokens` của gateway. Không kết luận việc trừ output là bug chỉ từ tên field: cần xác minh giới hạn input độc lập hay dùng chung total context của deployment trước khi mở rộng budget. Đề xuất đầu tiên vẫn giữ guard/trigger bảo thủ hiện tại, tối ưu phần lãng phí có bằng chứng trước.

### Vì sao vẫn compact nhiều

Riêng root Bình An, từ 11:25 UTC sau policy mới tới khi dừng: 209 tool call, 19 compaction; gồm 103 shell, 40 file read, 33 edit, 20 Python và 13 call khác. Các chu kỳ đầy đủ có khoảng 6–19 tool call trước summary tiếp theo; không phải mọi model call lập tức summary lại chính summary trước đó.

- `file_read` trả tổng 555.828 ký tự; shell trả 505.275 ký tự.
- Có 19 large file-read result và 6 large shell result trùng nguyên văn với result trước; so bằng hash nội dung, không chỉ cùng path. Thêm một inbox-read result lớn bị lặp.
- Mỗi chu kỳ nhận hàng chục nghìn ký tự tool output mới. Đọc lại cùng nội dung sau khi compact làm tăng context trở lại dù task chưa tiến thêm tương ứng.
- Audit có 104 file-read result bị char-truncate với continuation không tương ứng phần đã trả. Đây là lỗi harness cụ thể: chẳng hạn mới thấy một phần dòng 91 nhưng cursor trả 201; có trường hợp output mất phần cuối nhưng cursor báo hết.
- Summary vẫn giữ nhiều bảng số, lịch sử sửa và chi tiết có thể đọc lại từ deliverable. Một summary dài rồi phải đọc lại báo cáo để tiếp tục tạo ra vòng lặp tốn context.

Không thể quy toàn bộ reread cho một nguyên nhân: có cả sửa tài liệu thật, yêu cầu mới, model kiểm tra thừa, dữ liệu bị bỏ sót và mất local working context. Những bằng chứng trên đủ để ưu tiên sửa harness/output và prompt trước khi kết luận model không làm được việc.

### Read và execution hiện tại

`file_read` chọn 200 dòng rồi cắt chuỗi ở 16.000 **ký tự**; cursor lại tăng cố định 200 dòng. Không có token cap cho read. `history_read` chọn 200 dòng của JSON pretty-printed, chưa có token cap; một trường `text` có escaped newline vẫn có thể là một dòng JSON rất lớn.

Shell giữ 16.000 **byte** stdout và 4.000 byte stderr đầu tiên, trả `truncated`, bỏ phần dư. Chưa trả path lấy lại output, và có thể mất error/conclusion ở cuối stdout. Ba loại đơn vị hiện đang khác nhau; không nên mô tả chung thành một token cap.

Mirage Workspace/Session được tạo lazily và tái sử dụng trong một activity invocation. Không tạo lại cho mỗi command. `exec_python` chỉ quote code rồi gọi cùng shell với runtime Python; không có một môi trường Python đầy đủ thứ hai.

Offline probe dùng Mirage + RAMVFS, allowlist và Monty thực tế, không LLM: heredoc Python, read/write qua `Path`, pipeline `sort | uniq -c` chạy được; `read_text(encoding=...)` và `statistics` lỗi như checkpoint. Vì vậy Python qua shell có thể thay tool riêng, nhưng không mở rộng Python runtime.

## 3. Read/exec output: so sánh thuật toán thật

| Harness | Read | Exec | Lấy phần bị cắt và instruction |
| --- | --- | --- | --- |
| Codex | Local coding flow thường đọc qua shell như `rg`/`sed`; tool set tùy cấu hình, không có một read tool cố định áp cho mọi flow | Unified exec default 10.000 token; token truncation utility thực tế ước lượng 4 UTF-8 byte/token, giữ đầu + cuối, báo phần bị cắt. Capture process có giới hạn riêng | Có chunk/session cho process và `write_stdin`; output đã bị cắt không mặc nhiên lấy lại được chỉ bằng một handle. Muốn toàn bộ cần command ghi/redirect output. Không gọi đây là exact model tokenization. [Source][codex-output], [budget][codex-exec], [utility][codex-string] |
| Pi | Default/cap 2.000 dòng + 50 KiB. Head truncation giữ dòng hoàn chỉnh; offset/limit; next offset dựa trên số dòng thật đã trả. Dòng đầu quá lớn có hint shell riêng | Default 2.000 dòng/50 KiB, giữ tail. Collector chuyển sang temp file khi overflow, không giữ stdout vô hạn trong RAM | Result ghi đoạn dòng đã thấy + full output path; đọc tiếp thay vì chạy lại. Tool prompt khuyên `read` thay cat/sed. Shell vẫn dùng cho listing/search khi không có tool chuyên dụng. [Read][pi-read], [truncate][pi-truncate], [exec][pi-bash], [collector][pi-collector] |
| OpenCode | 2.000 dòng/50 KiB; offset/limit. Cắt từng dòng quá dài tại 2.000 ký tự với marker. Next chỉ số dòng dựa trên actual page | Tail bounded bởi 2.000 dòng/50 KiB mặc định; file output giữ toàn bộ command stream | Tool result trả output path và số dòng; prompt ưu tiên dedicated tools, cho phép filtering khi hữu ích, không ép mọi thao tác sang bash. [Read][oc-read], [capture][oc-shell], [defaults][oc-output], [guidance][oc-system] |
| Hermes | Default 2.000 dòng; per-line 2.000 ký tự; wrapper thêm budget khoảng 100.000 ký tự. Hoàn chỉnh dòng trong trường hợp thường và `next_offset`; riêng first oversize line có clipping rõ ràng | Default biến tên `max_bytes=50000`, nhưng đường head/tail đọc được thao tác trên Python string/ký tự; giữ 40% head/60% tail. Có bounded stream capture và spill khi bắt đầu vượt | Spill có ceiling và notice; hướng dẫn search/page file thay vì rerun. Prompt terminal lại ưu tiên file/search/patch tools, không bash-only. Không bê read dedup/guard framework của Hermes vào Leta. [Read][hermes-read], [limits][hermes-limits], [capture][hermes-capture], [terminal prompt][hermes-terminal] |
| OpenHands SDK | File editor có view range theo dòng; output response cap 16.000 ký tự, clipped notice; exact replace | Terminal model-facing cap 30.000 ký tự; generic truncator giữ head + tail. Có tùy chọn full-output save directory | Footer thông báo clipping, có file reference nếu cấu hình save. Cap cho content và cap tài nguyên là hai việc riêng. [Editor][oh-editor], [editor limit][oh-editor-limit], [terminal][oh-terminal], [terminal limit][oh-terminal-limit], [truncator][oh-truncate] |

Điểm chung hữu ích không phải một con số thần kỳ: query hẹp; result có giới hạn; clipping minh bạch; read cursor đúng; giữ kết quả cuối command; có cách lấy phần bị cắt mà không chạy mutation lại. Dòng dùng để định vị, byte dùng bảo vệ I/O/RAM, token dùng ngân sách model. Các mục đích này có thể cùng tồn tại nhưng không được lẫn đơn vị.

Không copy default 50 KiB hay 10k token một cách máy móc: model demo đang có budget khoảng 64k và tài liệu tiếng Việt; 50 KiB không tương đương một số token cố định.

## 4. System prompt và tool calling

### Những gì source thật sự hướng dẫn

- Pi có core prompt ngắn, default read/bash/edit/write, instruction theo tool được bật. `read` khuyên dùng thay cat/sed; bash dùng cho ls/rg/find nếu không có dedicated search/list. Không thể kết luận Pi khuyên làm mọi thứ bằng bash. [Assembly][pi-system]
- OpenCode core prompt rất ngắn; tool-specific descriptions giữ chi tiết offset/limit, exact edit, timeout/output. Prefer dedicated tools; full output file và no-poll instruction được đặt ngay trong result cần dùng. [System][oc-system], [subagent][oc-subagent]
- Codex prompt khác theo model/cấu hình và không phải mọi bản đều ngắn. Local base prompt có hướng dẫn tìm bằng rg, không dùng Python để dump file lớn; exec schema ghi rõ budget. Không lấy độ dài một file base rồi gọi đó là toàn bộ prompt production. [Base][codex-system]
- Hermes tách stable/context/volatile để giữ prefix cache, khuyên batch independent tool calls trong cùng model response. Prompt cũng có nhiều model/runtime-specific guidance và hệ thống guard lớn; không phải toàn bộ đều đáng học cho MVP. [Assembly][hermes-system], [batching][hermes-prompt]
- OpenHands nhắc mỗi action có chi phí, combine related commands, search có filter; task tool khuyên không delegate một grep hoặc việc đã có context, yêu cầu handoff rõ. Một số instruction của họ như environment persistence, git workflow, quyền nhận định subagent result không phù hợp để copy sang Openlet. [Efficiency][oh-system], [task][oh-task]

### Đề xuất Leta

Giữ bốn Markdown blocks: [common](../../apps/leta/prompts/common.md), [root](../../apps/leta/prompts/root.md), [leti](../../apps/leta/prompts/leti.md), [compaction](../../apps/leta/prompts/compaction.md). Một paragraph/bullet trên một dòng, không hard-wrap 80 ký tự, không Python string nối `\n` để chứa prose. Các newline phân đoạn/headings vẫn có ý nghĩa Markdown; JSON API encode `\n` trên wire là bình thường.

Common giữ product facts và các hành vi có giá trị: đúng người nhận, chỉ `inbox_send` mới gửi, hỏi/hạn quyền HITL, mounted storage, partial edits, waiting và runtime thực tế. Root chỉ thêm điều phối box; Leti chỉ thêm assignment/team context. Không chèn tên LangGraph/Mirage/Temporal hay observability backend vào instruction dành cho agent.

Điểm thay đổi về hành vi, không chỉ rút chữ:

1. Đọc để trả lời câu hỏi cụ thể; search trước khi tải nhiều nguồn. Follow continuation khi cần phần thiếu, không mặc định đọc tất cả.
2. Batch independent reads/search/calculations; shell có lợi khi một pipeline/script xử lý được nhiều file và chỉ in kết luận. Không batch các mutation phụ thuộc hoặc cùng file rồi để chạy song song.
3. Giữ report/table ở file, handoff chỉ kết luận + evidence + path + blocker. Không gửi cùng báo cáo dài cả qua inbox lẫn activity note.
4. Kiểm tra coverage và inconsistency đáng kể; không tự lặp toàn bộ phân tích của Leti, tạo các vòng reviewer và reread thành mặc định.
5. Python là subset, chỉ module/API đã biết; ví dụ heredoc ngắn và thao tác Path không encoding keyword. List modules đúng yêu cầu user, không biến prompt thành tài liệu Python.
6. Lỗi phải thay đổi bước tiếp theo. Phân biệt unsupported command/API với storage access denied; không retry cùng lỗi vô ích.
7. Đợi bằng kết thúc turn khi phụ thuộc inbox, không ping/poll/schedule để kiểm tra. Không nhấn mạnh "chạy 24/7" như một mục tiêu.

Tool description giữ tiêu chí chọn tool, format đầu vào hay bị sai và cách xử lý result bị cắt; không lặp nguyên schema trong system prompt. Vẫn dùng `@tool`/Pydantic native, không tạo JSON registry hoặc sửa JSON tool call bằng parser tự chế. Dependency hiện có xử lý validation/runtime errors thành tool result; lỗi invalid-only tool calls ở LangGraph vẫn theo TODO/link đã chốt, không mở một recovery subsystem.

Langfuse vẫn manage version/config/label và composition. Publish common trước, root/Leti reference numeric version bằng cơ chế đang có; runtime dùng `compile(agent_instructions=..., box_context=...)`. Không thêm prompt-sync service hay fallback copy. Draft mới chưa publish.

Đo draft bằng cùng local counter, chưa có assignment/box context động:

| Nội dung | Hiện tại | Draft | Thay đổi |
| --- | ---: | ---: | ---: |
| Root prose | 3.314 | 1.825 | -45% |
| Root prose + tool declarations | 4.538 / 28 tools | 2.996 / 27 tools | -34% |
| Leti prose | 3.129 | 1.681 | -46% |
| Leti prose + tool declarations | 4.075 / 22 tools | 2.574 / 21 tools | -37% |
| Compaction instruction | 492 | 353 | -28% |

Các hàng tool giả định chốt xóa `exec_python`; phần prose giảm độc lập với việc đó. Đây là giảm kích thước input tĩnh, không phải mức giảm tổng bill hay benchmark chất lượng. Trong audit, nguồn context lớn nhất vẫn là output/tool arguments tích lũy và công việc bị lặp, nên chỉ rút prompt là chưa đủ.

## 5. Compaction phù hợp cho Leta

### So sánh

| Harness | Trigger / replacement | Điều nên học |
| --- | --- | --- |
| Codex local | Handoff summary; giữ bounded user messages tới 20k approximate tokens, cùng các retained items theo policy; remote/native compaction là nhánh khác | Không khẳng định summary-only tuyệt đối. Giữ user intent/next action, tool transcript không phải nội dung phải bảo tồn hết. [Implementation][codex-compact], [prompt][codex-compact-prompt] |
| Pi | Window trừ reserve16.384; keepRecentTokens20.000 mặc định; latest valid provider usage + estimate phần sau, invalidated khi compact/context edit; summary riêng, structured Goal/Progress/Decisions/Next Steps | Giữ tail và ranh giới an toàn; append-only transcript khác model context. Pi serialize transcript cho summary nên không cache-friendly giống request Leta hiện tại. [Implementation][pi-compact], [docs][pi-compact-doc] |
| OpenCode | Default buffer15%, ít nhất16k; keep15k; precompute mặc định false tại commit khảo sát. Summary request giữ conversation prefix, append prompt; có native/overflow fallback riêng | Cache-friendly hiện tại của Leta có tiền lệ. Summary mới ưu tiên active state, bỏ dữ liệu recoverable và không chép lại setup; không copy precompute/shrink/retry engine. [Implementation][oc-compact] |
| Hermes | Nhiều policy: native compaction, local summary, pruning, lean/legacy tail, watermark/fallback. ContextCompressor constructor có threshold50% và tail riêng; không coi một constructor default là mọi runtime config | Cache-stable prompt, bounded handoff, giữ user asks. Hệ thống hiện lớn và nhiều cơ chế hơn nhu cầu Leta; không chọn làm kiến trúc mẫu nguyên khối. [Compressor][hermes-compact], [tail][hermes-tail] |
| OpenHands | Condenser giữ prefix, summary phần bị quên, recent suffix; event-count/token triggers, token path aim hạ view về khoảng nửa ngưỡng | Durable history khác view gửi model; event boundaries và recent context quan trọng. Không cần đổi sang event condenser của họ. [Implementation][oh-compact], [docs][oh-compact-doc] |

### Đề xuất cụ thể

Giữ native `SummarizationMiddleware` và public summarizer hook. Summary dùng cùng model/effort của agent, system/tool prefix ổn định và instruction thêm cuối. Không có model compaction riêng, recursive summarization, background summary hay model tự gọi tool compact.

Đề xuất config:

```yaml
compaction:
  trigger_fraction: 0.8
  keep_tokens: 8192
  summary_max_tokens: 2048
```

`keep_tokens` thay `keep_fraction`, không giữ cả hai hoặc alias compatibility. Đây là ngân sách tail khởi đầu để thử trên model64k hiện tại, không phải con số đã chứng minh tối ưu. Dùng native `keep=("tokens", keep_tokens)` và cutoff an toàn cho AI tool-call/results. Tail có thể lệch ngân sách khi phải giữ một nhóm message nguyên vẹn; không cắt giữa arguments/result. Validate với input budget ở config/model boundary, không thêm một tầng clipping state sau native middleware.

8k thấp hơn default15–20k của OpenCode/Pi vì budget demo nhỏ hơn, vẫn đủ giữ các thao tác ngay trước đó. Giữ absolute budget giúp không tự thành vài chục nghìn tail khi chọn model context lớn hơn. Giữ 80% và guard hiện tại trong lượt tối ưu đầu để không đồng thời thay mọi biến. Chưa mở rộng gateway context hoặc tạo hệ số calibration tự học.

Luồng:

```text
Trước: system + previous summary + older messages + recent complete exchanges
                                      | summarize | | preserve ~8k tokens |
Sau:   system + new rolling summary                 + preserved exchanges
```

Summary mới chỉ tóm tắt prefix bị bỏ; tail giữ nguyên native roles/call IDs. Nội dung summary: goal/constraints, current state, pending/waiting, next actions/references. Omit empty headings. Merge summary cũ với evidence mới, bỏ completed/obsolete details; không chứa lịch sử toàn bộ chỉnh sửa, bảng số có trong file, roster hay assignment được inject riêng.

2048 vẫn là output budget/target đã chốt, không hard length validator và không cắt summary sau khi sinh. Provider có thể không tuân thủ; summary rỗng hoặc response báo length/incomplete không thay checkpoint đang dùng. Giữ failure behavior hiện tại trước khi có bằng chứng cần đổi.

Provider usage và local estimate hiện native đều có vai trò. Đảm bảo counter/guard xét đúng system và tools ở nơi cần, nhưng không thêm cursor token engine chỉ để tránh đếm một history64k. Nếu cần đổi cách dùng provider input+new tail phải benchmark riêng với native API; chưa đưa vào baseline này.

Tail tăng có thể làm compact sớm hơn nếu giữ nguyên lượng output. Lợi ích mong đợi là ít mất working context, ít đọc lại và ít lặp công việc; không hứa chỉ bật tail là số compaction tự giảm. Đo theo một task hoàn thành, không chỉ theo số tool call.

Checkpoint vẫn latest working state (summary+tail). Public history giữ đầy đủ messages/tool calls/results/summaries, pagination và history search như hiện tại. Summary append ở thời điểm compact; không chèn lại vào seq cũ. Không gộp checkpoint+history transaction hoặc thêm reconciliation loop.

## 6. Tool surface, execution và output đề xuất

### Giữ những tool có giá trị riêng

Giữ `file_read` cho text/image/artifacts, `file_edit`, `file_write`, `file_semantic_search`, inbox/HITL/schedule/box tools. `file_list` có cursor và storage metadata, không đơn giản tương đương một dòng `ls`; chưa xóa chỉ vì shell có `ls`.

Đề xuất xóa `exec_python` khỏi root/Leti catalog và implementation; dùng `exec_shell` với Python heredoc. Offline đã kiểm chứng đường này chạy được. Giảm một tool và một lựa chọn trùng, không phải thay Monty bằng CPython. Không thêm `exec_code` router, fake stdlib, package installer hoặc bash wrapper mới.

Giữ exact literal `file_edit`. Các upstream có fuzzy matching hoặc batch edit arrays, nhưng không có bằng chứng rằng phải bê sang Leta. Narrow replacements ưu tiên hơn rewrite toàn file; một script có thể thực hiện biến đổi dữ liệu thực sự khi phù hợp. Không tạo một edit DSL/patch protocol mới trong đợt này.

### Read

- Định vị bằng `start_line`, thêm `limit` theo số dòng để đọc đoạn cần thiết thay vì luôn200. Đề xuất default200, max2000; đây là mức xin đọc, không phải ngân sách model.
- Giới hạn response khoảng4.096 token ước tính, do hệ thống quản lý, không yêu cầu model tự chọn `max_output_tokens`. Correction khi triển khai: preview dùng quy tắc đơn giản4 byte UTF-8/token tương tự Codex; không thêm tokenizer/dependency trực tiếp. Context vẫn dùng LiteLLM token_counter với payload SDK, không đổi sang character estimator.
- Trả các dòng hoàn chỉnh nằm trong budget; continuation là dòng chưa trả đầu tiên. Nếu một dòng đơn lẻ đã quá budget, trả thông báo rõ để dùng jq/Python chọn fields; không âm thầm bỏ phần còn lại rồi báo đọc xong.
- Không suy ra token cap từ16k ký tự, không thêm một char cap thứ hai để rồi lại cắt sau khi tính cursor.
- Áp dụng cùng ý nghĩa continuation cho history text. Không giải quyết long JSON `text` bằng cách serialize escaped string thành một dòng vô hạn; metadata riêng và body text đọc theo dòng có ích hơn cho agent.
- Không auto-follow toàn bộ cursor trong backend rồi trả toàn file cho LLM.

### Exec

- Bounded preview khoảng4.096 token ước tính tổng stdout/stderr, ưu tiên head+tail để không mất error/conclusion cuối. Giữ exit code và phân biệt truncation với command failure.
- Khi output vượt preview, đề xuất ghi capture vào file riêng trong home agent/box và trả path để đọc/search, dùng VFS có sẵn. Không chạy lại command chỉ để lấy phần bị cắt; không ghi log cho mọi command nhỏ. Đây là thay đổi hành vi để review, chưa implement.
- Capture phải có resource ceiling hữu hạn (đề xuất1MiB) và báo rõ nếu capture cũng bị cắt; không gọi file đó là full output khi không đầy đủ. Token budget là response policy; byte ceiling là bảo vệ bộ nhớ/I/O, không một tham số token thứ hai cho model.
- Dùng native Mirage streamed events, bounded RAM capture và tối đa một write VFS sau command khi overflow; không RPC/SQL mỗi chunk, không stream-spill service, index hoặc retention worker mới.
- Kết quả được lấy lại qua file tools hiện có. Không thêm fetch-output tool hay public API mới. Tool call ID tạo path ổn định để tránh ghi đè một output khác.

Đây là đánh đổi nhỏ có chủ đích: output quá lớn cần một write VFS thêm, thay cho mất kết quả hoặc rerun command. Nếu user chọn chưa lưu capture, tối thiểu phải có head+tail + clipping notice; không tuyên bố recoverable như Pi/OpenCode khi thực tế không có nơi đọc lại.

### Tool errors

Fix nhỏ đã được user đồng ý: mọi ToolMessage error có đúng `name`/tool_call_id; history projection giữ `status`. Không parse chữ "error" trong nội dung để kết luận thất bại. `grep` exit1 có thể chỉ là no match; không đổi thành claim permission denied. Giữ native validation feedback và domain authorization.

## 7. Box/Leti và context

Codex hỗ trợ child context/fork và lifecycle tools; Pi extension minh họa scout/planner/worker với bounded handoff; OpenCode có child sessions nhận completion notification, cấm poll; OpenHands Task truyền prompt/resume trong conversation riêng; Hermes có child run và lifecycle framework lớn. Không có lý do chuyển box/inbox sang một task scheduler mới chỉ để giống họ. [Codex spawn][codex-spawn], [Pi example][pi-subagent], [OpenCode child][oc-subagent], [OpenHands task][oh-task], [Hermes delegate][hermes-delegate]

Leta đã có context riêng mỗi Leti, home chung, allowed links và representative. `box_context()` hiện có box name/purpose, own name, teammate descriptions, representative marker và recipient IDs chỉ cho các links được phép; root recipient chỉ inject cho representative. Context đó đủ về cấu trúc, không cần nhét toàn bộ topology, teammate prompts hay root history.

Giữ snapshot context hiện tại và Langfuse placeholder; dùng heading Markdown cho dễ đọc. Không thêm clock/time context, full storage inventory hoặc toàn bộ source documents vào system. Nhiệm vụ và evidence đi qua inbox, stable role đi qua system assignment.

Chất lượng delegation chủ yếu sửa instruction/handoff: goal, bounded scope, accessible sources, expected evidence/result, reporting destination. Representative tích hợp một lần; specialist không phải mặc định reviewer của mọi người. Root không làm lại tất cả công việc vì đã delegate. File chứa long analysis; inbox chứa kết luận cần hành động. Chưa thêm machine-enforced message quota, dedup engine, vòng approval hay team-depth framework.

## 8. Phân biệt nguyên nhân

| Vấn đề | Phân loại | Hành động |
| --- | --- | --- |
| Read cắt text nhưng cursor nhảy qua phần chưa trả | Harness bug | Sửa page boundary và continuation, test bằng dòng dài/tiếng Việt |
| Shell cắt đầu và mất phần cuối, không lấy lại được | Tool result contract hạn chế | Head+tail, clipping rõ; capture path nếu chốt |
| Error thiếu name, history thiếu status | Harness/projection | Giữ native metadata; sửa tại chỗ dùng chung |
| Gọi `statistics`, `io`, encoding keyword không được hỗ trợ | Runtime không tương thích với CPython đầy đủ, cộng model chọn sai API | Prompt nói đúng khả năng, ví dụ nhỏ; không giả lập stdlib |
| Gọi tool `bash` thay tên thật | Model/tool selection | Native error và prompt/tool naming rõ, không alias compatibility |
| Đọc trùng report, vòng review, report/inbox quá dài | Hành vi model có thể bị khuếch đại bởi harness/prompt | Tail + narrow reads + concise handoffs; đo trên task hoàn chỉnh |
| Tính sai/khẳng định điều kiện chưa được xác nhận | Chất lượng model/task reasoning | Source-based check và prompt; không hứa output cap hay thêm tool chữa được |
| Provider trả summary dài hơn budget | Provider/model behavior | Ghi đúng measurement; prompt summary gọn; không thêm hard-cut/retry cascade |
| Invalid-only parsed tool calls, issue33504 | Upstream issue đã biết | Giữ TODO/reference đã chốt; không speculative recovery |

## 9. Scope implementation sau review và verification nhỏ nhất

1. Read/history continuation, bounded output và tool error metadata: runtime tools, filesystem shell, history projection/read, các caller và focused tests.
2. Compaction tail config: runtime `ExecutionModel`, shared config typing/validation, example/local config và runtime tests. Xóa keep_fraction nếu chuyển keep_tokens; không backward compatibility.
3. Markdown prompts/tool catalog: các draft mới, LF common/root/Leti/compaction versions/config, tool contracts và API test fixtures; bỏ exec_python references trong caller/tests nếu chốt xóa. Không bỏ execution capability Python.
4. Small offline verification: line pages nối lại không mất/trùng nội dung; oversize line có hành động tiếp theo; head/tail và capture path chính xác; malformed tool arguments trở thành named error; native summary giữ tool pairs/tail và prefix; prompt paragraphs không hard-wrap.
5. Strict Pyright/Ruff và focused tests của phần đổi. Benchmark script giữ ngoài source. Đo CPU/VFS writes nếu thêm capture, không gọi fake fixture speedup là LLM speedup.
6. Sau khi user cho chạy lại model: dùng cùng một task có nguồn/đầu ra xác định, thêm một handoff thật root–Leti; so total input/output/cache usage, số byte/token tool results, reread, tool errors, compactions và completion correctness. Sau đó mới chạy lại các journey cần thiết, không bung thêm19 agent để lấy một con số.

Không có benchmark A/B model mới ở lượt nghiên cứu này. Prompt ngắn hơn là số đo tĩnh, chưa phải bằng chứng chất lượng cao hơn. Mục tiêu là task hoàn thành đúng với ít vòng/cost hơn, không tối ưu chỉ số tool count bằng cách giấu output hoặc bypass acceptance.

[codex-output]: https://github.com/openai/codex/blob/b1573f102413e96a6481087922bf425231222dee/codex-rs/utils/output-truncation/src/lib.rs
[codex-exec]: https://github.com/openai/codex/blob/b1573f102413e96a6481087922bf425231222dee/codex-rs/core/src/unified_exec/mod.rs#L74
[codex-string]: https://github.com/openai/codex/blob/b1573f102413e96a6481087922bf425231222dee/codex-rs/utils/string/src/truncate.rs
[codex-system]: https://github.com/openai/codex/blob/b1573f102413e96a6481087922bf425231222dee/codex-rs/protocol/src/prompts/base_instructions/default.md
[codex-compact]: https://github.com/openai/codex/blob/b1573f102413e96a6481087922bf425231222dee/codex-rs/core/src/compact.rs#L720
[codex-compact-prompt]: https://github.com/openai/codex/blob/b1573f102413e96a6481087922bf425231222dee/codex-rs/prompts/templates/compact/prompt.md
[codex-spawn]: https://github.com/openai/codex/blob/b1573f102413e96a6481087922bf425231222dee/codex-rs/core/src/tools/handlers/multi_agents/spawn.rs
[pi-read]: https://github.com/badlogic/pi-mono/blob/8636e211e7834e4ca46a22aec1d65dfd2eac8677/packages/coding-agent/src/core/tools/read.ts
[pi-truncate]: https://github.com/badlogic/pi-mono/blob/8636e211e7834e4ca46a22aec1d65dfd2eac8677/packages/coding-agent/src/core/tools/truncate.ts
[pi-bash]: https://github.com/badlogic/pi-mono/blob/8636e211e7834e4ca46a22aec1d65dfd2eac8677/packages/coding-agent/src/core/tools/bash.ts
[pi-collector]: https://github.com/badlogic/pi-mono/blob/8636e211e7834e4ca46a22aec1d65dfd2eac8677/packages/coding-agent/src/core/tools/output-accumulator.ts
[pi-system]: https://github.com/badlogic/pi-mono/blob/8636e211e7834e4ca46a22aec1d65dfd2eac8677/packages/coding-agent/src/core/system-prompt.ts
[pi-compact]: https://github.com/badlogic/pi-mono/blob/8636e211e7834e4ca46a22aec1d65dfd2eac8677/packages/coding-agent/src/core/compaction/compaction.ts
[pi-compact-doc]: https://github.com/badlogic/pi-mono/blob/8636e211e7834e4ca46a22aec1d65dfd2eac8677/packages/coding-agent/docs/compaction.md
[pi-subagent]: https://github.com/badlogic/pi-mono/blob/8636e211e7834e4ca46a22aec1d65dfd2eac8677/packages/coding-agent/examples/extensions/subagent/index.ts
[oc-read]: https://github.com/anomalyco/opencode/blob/d759c548aab33a7a6f5171cbeab40a59e91d90aa/packages/core/src/tool/read-filesystem.ts
[oc-shell]: https://github.com/anomalyco/opencode/blob/d759c548aab33a7a6f5171cbeab40a59e91d90aa/packages/core/src/shell.ts#L817
[oc-output]: https://github.com/anomalyco/opencode/blob/d759c548aab33a7a6f5171cbeab40a59e91d90aa/packages/core/src/tool-output.ts
[oc-system]: https://github.com/anomalyco/opencode/blob/d759c548aab33a7a6f5171cbeab40a59e91d90aa/packages/core/src/session/system-prompt.ts
[oc-compact]: https://github.com/anomalyco/opencode/blob/d759c548aab33a7a6f5171cbeab40a59e91d90aa/packages/core/src/session/compaction.ts
[oc-subagent]: https://github.com/anomalyco/opencode/blob/d759c548aab33a7a6f5171cbeab40a59e91d90aa/packages/core/src/tool/plugin/subagent.ts
[hermes-read]: https://github.com/NousResearch/hermes-agent/blob/d93e9ba4c87a62f5f7906fb7d306d39773a9dbcd/tools/file_tools.py
[hermes-limits]: https://github.com/NousResearch/hermes-agent/blob/d93e9ba4c87a62f5f7906fb7d306d39773a9dbcd/tools/tool_output_limits.py
[hermes-capture]: https://github.com/NousResearch/hermes-agent/blob/d93e9ba4c87a62f5f7906fb7d306d39773a9dbcd/tools/environments/base_output.py
[hermes-terminal]: https://github.com/NousResearch/hermes-agent/blob/d93e9ba4c87a62f5f7906fb7d306d39773a9dbcd/tools/terminal_tool.py#L178
[hermes-system]: https://github.com/NousResearch/hermes-agent/blob/d93e9ba4c87a62f5f7906fb7d306d39773a9dbcd/agent/system_prompt.py
[hermes-prompt]: https://github.com/NousResearch/hermes-agent/blob/d93e9ba4c87a62f5f7906fb7d306d39773a9dbcd/agent/prompt_builder.py#L411
[hermes-compact]: https://github.com/NousResearch/hermes-agent/blob/d93e9ba4c87a62f5f7906fb7d306d39773a9dbcd/agent/context_compressor.py
[hermes-tail]: https://github.com/NousResearch/hermes-agent/blob/d93e9ba4c87a62f5f7906fb7d306d39773a9dbcd/agent/context_compressor_tail.py
[hermes-delegate]: https://github.com/NousResearch/hermes-agent/blob/d93e9ba4c87a62f5f7906fb7d306d39773a9dbcd/tools/delegate_tool.py
[oh-editor]: https://github.com/OpenHands/software-agent-sdk/blob/3c66af1d14d0a7fbe74b8dc4218412ec7a877b79/openhands-tools/openhands/tools/file_editor/editor.py
[oh-editor-limit]: https://github.com/OpenHands/software-agent-sdk/blob/3c66af1d14d0a7fbe74b8dc4218412ec7a877b79/openhands-tools/openhands/tools/file_editor/utils/constants.py
[oh-terminal]: https://github.com/OpenHands/software-agent-sdk/blob/3c66af1d14d0a7fbe74b8dc4218412ec7a877b79/openhands-tools/openhands/tools/terminal/definition.py#L180
[oh-terminal-limit]: https://github.com/OpenHands/software-agent-sdk/blob/3c66af1d14d0a7fbe74b8dc4218412ec7a877b79/openhands-tools/openhands/tools/terminal/constants.py#L18
[oh-truncate]: https://github.com/OpenHands/software-agent-sdk/blob/3c66af1d14d0a7fbe74b8dc4218412ec7a877b79/openhands-sdk/openhands/sdk/utils/truncate.py
[oh-system]: https://github.com/OpenHands/software-agent-sdk/blob/3c66af1d14d0a7fbe74b8dc4218412ec7a877b79/openhands-sdk/openhands/sdk/context/prompts/sections/static.py
[oh-task]: https://github.com/OpenHands/software-agent-sdk/blob/3c66af1d14d0a7fbe74b8dc4218412ec7a877b79/openhands-tools/openhands/tools/task/definition.py#L121
[oh-compact]: https://github.com/OpenHands/software-agent-sdk/blob/3c66af1d14d0a7fbe74b8dc4218412ec7a877b79/openhands-sdk/openhands/sdk/context/condenser/llm_summarizing_condenser.py
[oh-compact-doc]: https://github.com/OpenHands/software-agent-sdk/blob/3c66af1d14d0a7fbe74b8dc4218412ec7a877b79/openhands-sdk/openhands/sdk/context/condenser/README.md
