# Instructor, compaction và retained history

Ngày 2026-11-14. Read-only application/source investigation; không triển khai
runtime, publish prompts hoặc commit. Report là evidence cho
[plan hiện tại](../261114-0035-inference-prompts-compaction/plan.md), không tự
thay quyết định đã duyệt.

## Instructor qua LiteLLM

Plan đã ghi exact Git pin ở implementation §2 và `instructor.from_litellm`
ở design §5–6. Application pyprojects/uv.lock chưa có dependency; ingest
`providers.py:157` vẫn dùng OpenAI `chat.completions.parse`.

Đã đọc Instructor commit `aeb7e2558166caeec497e541bcfc6b4eaa2cf53b`:

- Native `from_litellm(litellm.acompletion, async_client=True)` có sẵn.
- `create_with_completion` trả validated object và raw LiteLLM response.
- Cost thuộc LiteLLM, không Instructor. Official integration docs đọc
  `raw_completion._hidden_params["response_cost"]`; usage cũng còn trong raw.
- `completion:response` hook chạy trước Instructor cộng usage các attempts.
  Raw response cuối không phải tổng cost của toàn extraction/correction chain.

Isolated SDK probe dùng đúng Git pin và LiteLLM 1.109.1: hai synthetic completions
với tool arguments lần đầu sai, lần sau đúng. Hooks thấy riêng 10/20 input tokens
và costs 0.001/0.002; object validated thành công, raw response cuối có 30 input
tokens accumulated nhưng cost vẫn 0.002. Đây là SDK contract probe, không live
provider price/cache verification. Giữ accepted per-request Langfuse observations
trước usage mutation; không thêm pricing engine hoặc extraction ledger.

Native sources:

- [LiteLLM factory](https://github.com/567-labs/instructor/blob/aeb7e2558166caeec497e541bcfc6b4eaa2cf53b/instructor/v2/providers/litellm/client.py).
- [Raw completion API](https://github.com/567-labs/instructor/blob/aeb7e2558166caeec497e541bcfc6b4eaa2cf53b/instructor/v2/core/client.py#L951).
- [Response hook before usage aggregation](https://github.com/567-labs/instructor/blob/aeb7e2558166caeec497e541bcfc6b4eaa2cf53b/instructor/v2/core/retry.py#L552).
- [Official integration and cost example](https://github.com/567-labs/instructor/blob/aeb7e2558166caeec497e541bcfc6b4eaa2cf53b/docs/integrations/litellm.md#L77).

## Coding-agent compaction source comparison

Đã resolve GitHub default branches thành immutable commits trước khi đọc:

| Source                     | Request tạo compact                                                                                                                    | Working context sau compact                                                                                                                          |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| OpenCode `f91b88e`         | Normal model request giữ conversation prefix, append summary user instruction; có provider-native branch riêng                         | Summary và recent context; giữ range qua `keepID`, render recent text vào checkpoint                                                                 |
| Codex `4413dea`            | Local branch clone history, append compact input, gọi model stream; remote branch riêng nhận provider compaction item                  | Local giữ selected bounded user/client-retained items và summary, reinsert canonical context; remote có opaque checkpoint và selected retained items |
| Repo Claude Code `6f6f12b` | Cache-sharing branch fork cùng system/tools/model/messages/thinking rồi append summary instruction; fallback thay summarization system | Full compact trả summary và attachments/hooks; partial compact giữ thêm messagesToKeep                                                               |

Không thể kết luận tất cả chỉ giữ summary, hoặc không có inference request
tóm tắt. Hai câu hỏi độc lập: request tạo summary thế nào và giữ context gì sau
đó. Same executing model không có nghĩa không phát sinh request/cost riêng.

OpenCode mới còn background/precomputed compaction và nhiều overflow fallbacks.
Codex có provider-specific opaque/native compaction. Không đưa các cơ chế đó
vào Openlet chỉ vì nguồn tham khảo có chúng. Repo Claude Code không phải nguồn
Anthropic chính thức; findings chỉ mô tả đúng revision đã đọc.

Sources:

- [OpenCode summary request and retained tail](https://github.com/anomalyco/opencode/blob/f91b88efac039856f284979984ac43cd93bce8f5/packages/core/src/session/compaction.ts#L453).
- [OpenCode native branch](https://github.com/anomalyco/opencode/blob/f91b88efac039856f284979984ac43cd93bce8f5/packages/core/src/session/compaction.ts#L562).
- [OpenCode summary client rendering](https://github.com/anomalyco/opencode/blob/f91b88efac039856f284979984ac43cd93bce8f5/packages/session-ui/src/timeline-next/compaction.tsx#L37).
- [Codex local request](https://github.com/openai/codex/blob/4413deac572eb5d4cdb49295794cbe30f8622935/codex-rs/core/src/compact.rs#L267).
- [Codex replacement context](https://github.com/openai/codex/blob/4413deac572eb5d4cdb49295794cbe30f8622935/codex-rs/core/src/compact.rs#L720).
- [Codex remote branch](https://github.com/openai/codex/blob/4413deac572eb5d4cdb49295794cbe30f8622935/codex-rs/core/src/compact_remote_v2.rs#L291).
- [Claude Code cache-sharing request](https://github.com/tanbiralam/claude-code/blob/6f6f12b37f529488b10e53928dd5508bb93535c7/src/services/compact/compact.ts#L1136).
- [Claude Code resulting context](https://github.com/tanbiralam/claude-code/blob/6f6f12b37f529488b10e53928dd5508bb93535c7/src/services/compact/compact.ts#L328).

## Openlet hiện có

Native LangChain 1.5.0 SummarizationMiddleware sở hữu trigger/cutoff/state
replacement. Public summarizer hook nhận old prefix; middleware tạo HumanMessage
`lc_source=summarization`, rồi replacement thành summary + preserved messages.
Current application callback vẫn replacement system + XML; accepted future
callback giữ stable system/tools/native prefix rồi append instruction. Cách
future request có tiền lệ rõ, nhưng không phải implementation giống từng dòng
OpenCode/Claude Code: native middleware Openlet chỉ gửi prefix được chọn để tóm
tắt, còn OpenCode ưu tiên gửi cả working conversation khi đủ budget.

Hai nơi lưu summary hiện có:

1. Native PostgreSQL checkpoint: rolling summary + tail và continuation state;
   `keep_latest` prune snapshots, không public transcript.
2. PostgreSQL `history`: `project` nhận summary marker và append
   `kind=compaction`, payload `{"text": ...}`. Các summaries cũ vẫn là timeline
   entries, dù working context chỉ giữ rolling summary mới nhất.

`project` cũng ghi inbox_input, assistant/final_note, tool_call và tool_result.
Đây là public committed transcript, không byte-for-byte provider requests:
không archive mỗi system prompt/tools schema/raw metadata/hidden reasoning.
Không có app DELETE/TRUNCATE history hoặc auto-purge job trong source đã kiểm.
MVP giữ durable history; không đổi Redis TTL/trimming hoặc checkpoint pruning.

## History API và client

- GET `/v1/workspaces/{workspace_id}/letas/{leta_id}/agents/{agent_id}/history`
  trả 20 previews mới nhất, `ORDER BY seq DESC`, optional `before` và `query`;
  `next_cursor` là seq cuối trang. Request tiếp dùng `before=<next_cursor>`.
- GET cùng path `/{entry_id}` trả body JSON dạng text, 200 dòng/trang;
  `next_start_line` tiếp tục body lớn. List preview tối đa 500 characters.
- Summary có cùng detail API vì là history kind bình thường. Redis phát
  `openlet.history` reference sau projection; client không đọc checkpoint.
- Agent có native `history_search` và `history_read` để chủ động lấy lại chi tiết
  đã ra khỏi working context. Không tự reload toàn bộ transcript vào mỗi call.

Backend pagination và summary exposure đã có; repo hiện không có frontend
timeline implementation. Client có thể lấy recent page, đảo thứ tự để render
tăng dần, cuộn lên prepend trang cũ và deduplicate theo stable entry id. Summary
render thành expandable compaction entry; mở detail mới hydrate body lớn. Không
reset timeline khi compaction xảy ra, không dùng Redis replay cho scrollback.

Source owners: `runtime/agent.py:103`, `history.py:11`, `api.py:361`,
`agents.py:161`, `events.py:89`, `migrations/0001_initial.sql:103`.

## Acceptance còn thiếu

Native in-memory graph probe trong project venv đã xác nhận summary update có
message ID và `lc_source=summarization`; checkpoint giữ summary + hai recent
messages + response mới (4 messages, từ 8 messages đầu vào). Lần chạy đầu ở
isolated LiteLLM venv thiếu `langchain`; chạy lại trong project venv thành công,
không cài thêm dependency. Probe này kiểm native contract, không PostgreSQL/API.

Không tuyên bố đã thử full compaction → worker restart → history pagination qua
application trong lượt này. Existing E2E đọc history/detail nhưng chưa ép compact
và cuộn qua nhiều trang. Khi implementation chạy focused journey: compact một
lần, đọc summary detail, paginate về entry trước compact, restart/prune rồi đọc
lại. Không cần full raw-provider archive, summary table hay retention worker.

## Follow-up: thresholds, transaction, Redis và prompt propagation

- [LangChain native reference](https://reference.langchain.com/python/langchain/agents/middleware/summarization/SummarizationMiddleware)
  ghi trigger fraction 0.8 và keep fraction 0.3 trong examples; default keep là
  20 messages. [OpenCode source](https://github.com/anomalyco/opencode/blob/f91b88efac039856f284979984ac43cd93bce8f5/packages/core/src/session/compaction.ts#L128)
  dùng reserve share 0.15 và minimum 16k. Giữ 0.8/0.3 làm initial defaults có
  configuration, không claim empirically optimal. Application hiện vẫn hardcode.
- Đã đọc public PyPI sdist `langgraph-checkpoint-postgres==3.2.0` `aio.py`:
  from_conn_string mở connection autocommit riêng; native aput/aput_writes dùng
  saver cursor/pipeline. Current application history dùng pool connection khác.
  Không có joint transaction hiện tại; native sync durability không commit
  history cùng saver. Giữ checkpoint → batched history → prune với recovery,
  không SQL transaction dài qua inference hoặc custom saver.
- Existing crash proof kill khi model tiếp theo đang chờ, không tại exact
  checkpoint/history gap. Added acceptance đòi fault-injection đúng gap, gồm
  compaction; không coi contract đã được full-stack verify ở lượt research.
- Current Live.chunk gọi Live.emit → events.publish → Redis pipeline XADD/
  EXPIRE. Vẫn stream provider text/tool-argument chunks, không chỉ SQL snapshots.
  Chunk không đồng nghĩa một token; read-side fold chỉ gộp output frames.
- Current streaming text ID dùng uuid5(agent_id, message.id), còn persisted
  history ID dùng uuid5(NAMESPACE_URL, f"{agent_id}/{message.id}"). Pure UUID
  probe xác nhận khác nhau; cần align live ID với existing canonical formula.
- [Langfuse prompt linking docs](https://langfuse.com/docs/prompt-management/features/link-to-traces)
  và public PyPI source 5.2.0 `propagation.py` xác nhận chỉ extract name/version.
  Isolated OTel span probe truyền prompt body 100k characters: attributes chỉ
  có prompt name/version và session.id, không prompt body. Không network call.
  Actual generation input logging là đường riêng, vẫn có thể chứa prompt text.
