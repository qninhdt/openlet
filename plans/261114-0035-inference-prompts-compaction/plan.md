# Inference, prompt management và cache-friendly compaction

Ngày 2026-11-14. **Design/implementation plan, chưa triển khai runtime.**
Đối chiếu 17 commit trong `d69be44..026c044` và các quyết định cuối cuộc trao đổi.
`d69be44` là application-code baseline; `a6bb313` sau đó có thêm env template.

## Kết quả cần đạt

Leta/Leti, enrichment, embedding và optional rerank đi qua một LiteLLM Proxy.
Langfuse quản lý prompt cùng task model/parameters, nhận actual request cost;
compaction giữ native message/tool prefix để có cơ hội tái sử dụng provider cache.
Xóa local catalog, direct-provider wiring và các implementation bị thay thế.
Giữ nguyên domain, Temporal, Mirage, inbox, streaming và checkpoint contracts đã duyệt.

## Phạm vi và authority

- [Decision ledger](decisions.md): từng commit, quyết định còn hiệu lực, proposal đã bỏ,
  bằng chứng và giới hạn; không coi mọi nội dung committed là approved.
- [Thiết kế chi tiết](design.md): ownership, config, clients, listing/selection,
  structured output, retry, costs, prompts, compaction và Cloud topology.
- [Triển khai và acceptance](implementation.md): file map, commit boundaries,
  dependency order, checks và cutover/rollback.
- [Inference đã duyệt](../261111-2010-leta-rewrite/inference.md),
  [Leta](../261111-2010-leta-rewrite/plan.md),
  [observability](../261113-1335-system-observability/plan.md) vẫn là owning scope.
  Plan này gom phần triển khai tiếp theo; các điểm đề xuất chưa duyệt ghi riêng.

Không rewrite lại toàn bộ hai plan đã có code. Không evaluation, Playground,
A/B, prompt sync/release framework, custom router/provider/pricing engine,
LiteLLM DB/Redis/response cache, Rust RC, financial ledger hoặc frontend mới.
Không skills/subagents, legacy/backward compat hoặc copy archive. Python typing
chuẩn/Pyright strict áp dụng cả Leta, ingest, SDK và scripts.

## Các phase và phụ thuộc

| Phase | Nội dung                                                            | Phụ thuộc / kết thúc                                                     |
| ----- | ------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| 1     | Pinned dependencies, stable Python Proxy, shared config/env/Compose | Boot và native metadata/chat/embedding qua Proxy                         |
| 2     | Metadata snapshot, Leta model listing và selection                  | Phase 1; chốt effort contract trước phần API/SQL liên quan               |
| 3     | Prompt Config và native clients Leta/ingest/Go                      | Phase 1–2; kiểm capability routing trước multi-provider structured calls |
| 4     | Per-request cost, usage và AI observation integration               | Phase 3; không duplicate; attribution gate độc lập                       |
| 5     | Cache-friendly compaction + managed prompt lifecycle                | Phase 3–4; wire prefix và restart proof                                  |
| 6     | Shared E2E, local demo/Cloud acceptance, docs và xóa code cũ        | Các phase trên; không inference trả phí trên mọi PR                      |

Mỗi boundary là focused conventional commit; không dồn một commit lớn.
Một phase có thể chia config/consumer/delete commits khi review dễ hơn, nhưng
không để compatibility layer thành trạng thái hoàn tất.

## Các điểm cần chốt hoặc chứng minh trước boundary tương ứng

1. **Per-agent effort API:** đề xuất giữ hai field hiện có `model_id` và
   `reasoning_effort`, group name opaque, không suffix; chi tiết PATCH/default/
   inheritance trong [design §4](design.md#4-model-listing-và-agent-selection).
   Đây là đề xuất thay contract suffix đã rút, chưa giả định được duyệt.
2. **Routing trong group:** requirement đã chốt là mọi deployment được chọn phải
   đáp ứng request. Cần proof native capability routing; nếu không đủ, đề xuất
   common capability của group. Không tự chọn supplier priority/weights hoặc
   âm thầm loại provider; xem [design §5](design.md#5-capabilities-và-structured-output).
3. **Chi phí RAG theo agent:** kiểm trước LF có aggregate Go observations theo
   trace/session hiện có không. Chỉ nếu thiếu mới trình narrow native baggage
   trong internal SemanticSearch; cần chốt trước thay propagation. Xem
   [design §7](design.md#7-cost-usage-và-attribution).

Các gate này không chặn đọc code, dependency proof hoặc thiết kế phần độc lập.
Không hỏi lại các quyết định đã chốt như dùng Proxy, Instructor, Langfuse Config,
optional rerank hoặc cùng model cho compaction.

## Acceptance cuối

- Một group name, nhiều native upstream deployments; app không giữ provider list,
  price table hoặc task default model trong YAML.
- Leta model-list lấy subset `leta` từ gateway, deduplicate; chọn group/effort đúng
  actual capability và root/Leti inheritance, không expose credentials.
- Native chat/tools/stream, Instructor schema extraction và single/batch/query
  embedding đi qua gateway; rerank tắt vẫn RAG hữu ích và đúng quyền/source version.
- Retry transport chỉ ở Proxy; Instructor correction hữu hạn; Temporal recovery
  giữ nguyên và không bị trình bày sai thành exactly-once inference.
- Actual usage/cost đến đúng LF observations cho streaming/nonstreaming/embedding;
  missing là unknown, không zero; không count Instructor aggregate hai lần.
- Prompt/version/config pin mỗi invocation; common numeric reference, label
  rollback, cache behavior và compaction link đúng; Playground/evaluation hoãn.
- Compaction giữ exact system/tools/native prefix, summary + bounded tail,
  checkpoint restart và `keep_latest`; không flatten XML hoặc model riêng.
- Narrow tests, strict Pyright, format/lint/build và shared API E2E pass.
  Cloud proof cần actual app telemetry, không chỉ empty ingestion HTTP 200.

## Trạng thái

Chưa bắt đầu implementation plan này. Các research probes và runtime baseline
đã có trước được ghi ở decision ledger; không dùng chúng thay acceptance migration.
Prompt wording vẫn draft/chưa publish. `.env.example` đang có thay đổi ngoài
phạm vi lượt lập plan này; giữ nguyên.
