# Phạm vi triển khai hợp nhất: inference, Leta và observability

Ngày 2026-11-14. **Runtime đã triển khai; acceptance/evidence tại [execution](execution.md).**
Đối chiếu 17 commit trong `d69be44..026c044` và các quyết định cuối cuộc trao đổi.
`d69be44` là application-code baseline; `a6bb313` sau đó có thêm env template.

Đây là đầu mối tổng hợp toàn bộ scope đã chốt từ các diff Leta/inference/
prompting/Temporal/observability và F01–F19. Design/report giữ chi tiết và evidence;
không là các dự án riêng phải rewrite lại. Không tạo thêm plan tổng hợp khác.

## Toàn bộ công việc sẽ triển khai

### 1. Gateway, dependencies và cấu hình

- Thêm một stable Python LiteLLM Proxy trong Compose, một worker; native config
  tại `infra/config/litellm.yaml`, mount read-only, server key/private endpoints/
  health. Không Rust RC, DB/Redis/response cache riêng cho gateway ở demo này.
- Pin compatible LiteLLM/ChatLiteLLM và Instructor official Git commit
  `aeb7e2558166caeec497e541bcfc6b4eaa2cf53b`; kiểm uv workspace/Python3.14.
  Không SDK fork, force resolver hoặc downgrade OpenAI để né dependency conflict.
- App nhận gateway URL/key/timeout; gateway nhận upstream credentials từ root
  `.env`. Vilao dùng native OpenAI-compatible adapter/named credential và
  `OPENAI_BASE_URL`/`OPENAI_API_KEY`. Tên upstream tạm không slash.
- Public group như `openai/gpt-6.1-sol` có thể có Vilao/official/OpenRouter
  deployments. App/LF chọn group, Proxy route; không backend parser/router.
  Chỉ bật upstream có credentials thực, không tự chọn priorities/weights.
- Update shared Python/Go config, configure/bootstrap, Compose/env example/docs.
  Không ép CPU parse/Platform/migrations phải có provider credentials.
- Openlet YAML giữ connection, embedding group/dimensions/index identity,
  nullable reranking group, enrichment output mode và resource/image budgets.
  Xóa local catalog/prices/Leta-enrichment task default model khỏi YAML.

### 2. Model listing và lựa chọn model/effort

- Model-list lấy `/model/info` server-side, một typed RAM snapshot/process,
  TTL60s/refresh theo nhu cầu; không Redis/polling/request mỗi token/tool.
- Chỉ list groups có `model_info.access_groups: [leta]`, deduplicate deployments
  thành một item/group. Giữ existing workspace authorization/route, không lộ
  credentials/upstream config/deployment IDs/price table ra client.
- Response giữ model ID và verified effort choices khi có metadata. Context/
  output limits dùng server-side; thiếu facts thì kiểm native metadata override,
  không tạo catalog/hardcoded capability list thứ hai.
- Giữ hai fields `model_id`, `reasoning_effort`. Root chưa chọn dùng pinned LF
  defaults; Leti chưa chọn inherit root effective pair. Explicit DB pair ưu tiên.
- Explicit model + effort absent/null là không gửi override; không tự đổi thành
  `none` hoặc kế thừa effort của model khác. LF config phẳng, không default wrapper.
- PATCH omit giữ field, riêng đổi model bỏ effort thì clear effort cũ.
  `model_id:null` reset default/inheritance và clear effort. Effort-only cần
  explicit model. Validate effective pair, không silently drop unsupported params.
- LF giữ task default effort/temperature/top_p/top_k/output budget khi cần và
  support; typed parse tại boundary, không arbitrary kwargs/null-filled options.

### 3. Native clients, Instructor và retry

| Caller             | Client đích                                                          |
| ------------------ | -------------------------------------------------------------------- |
| Leta/Leti          | `langchain_litellm.ChatLiteLLM` qua Proxy, native tools/create_agent |
| Ingest enrichment  | Async `instructor.from_litellm`, existing Metadata model             |
| Ingest embedding   | `litellm.aembedding`                                                 |
| Go query embedding | Existing official OpenAI Go SDK qua Proxy                            |
| Optional rerank    | Native Proxy rerank HTTP endpoint                                    |

- YAML `models.enrichment.output_mode: tools | json_schema | text` map đúng
  Instructor `TOOLS | JSON_SCHEMA | MD_JSON`; Vilao dùng `tools`.
- Instructor sở hữu parsing/Pydantic validation/bounded correction: validated
  object hoặc lỗi. Không validator/JSON fixer/correction loop thứ hai.
- Không actual-deployment autodetect, mode downgrade chain/capability intersection
  hoặc ép ordinary agent tools qua Instructor/strict tool calling đại trà.
- App/SDK transport retry0; Proxy bounded transport retry/backoff/failover;
  Instructor bounded validation feedback; Temporal durable recovery giữ riêng.
  Initial tuning: một transport retry, tối đa hai Instructor completions, kiểm
  native counter semantics trước config. Không app Router/nested retry loops.
- Partial stream không nối với full retry thành cùng completion. Permanent
  config/unsupported parameter lỗi hiện rõ; không repair hoặc silent downgrade.

### 4. Embedding, RAG và optional reranker

- Ingest/query explicit float encoding/dimensions, giữ count/index/dimension
  checks. Query/index phải cùng embedding space/preprocessing; cùng dimensions
  không cho phép đổi model tùy ý. Không tự reset/reindex/cross-model fallback.
- Reranking absent/null là off, không enabled field thừa. Off vẫn query embedding
  → dense + BM25/RRF → SQL permission/live/source-version filters → top-k.
  On thêm rerank sau filter; lỗi khi bật vẫn visible.
- F07: TextHit/SemanticHit trả relative path từ LetFS; sửa proto/Go/generated SDK
  cùng nhau. Leta bỏ parent Stat walk và ReadTree1.000 nodes để map search paths.
- F08: tối đa năm search paths chạy reads độc lập song song có bound, giữ result
  order/errors/ranking từng scope; không cross-mount fusion/query cache.
  Concurrency chỉ giảm chờ, không giảm paid embedding/rerank call count.

### 5. Runtime agent và context

- F01: graph/tools/middleware/hooks dựng một lần/activity; reuse client qua model/
  tool boundaries. Outer loop chỉ control/resume/checkpoint-history-prune.
- Giữ native create_agent/typed tools, static model/tools interrupts, sync saver,
  input guard, heartbeat, writer lock, receipt-expiry guard và cancellation settle.
  Không soft slices/timer hoặc workflow từng LLM/tool để tối ưu LoC.
- Gộp current control/profile/root selection reads thành runtime query. F05:
  DSN/saver dùng startup config đã có; không parse YAML lại mỗi saver hoặc để
  saver và process pool trỏ hai DB vì file config đổi giữa process.
- DB model/effort/instructions áp ở safe boundary; client/system/input guard/
  summary budget đồng bộ effective settings. Static overhead chỉ tính khi đổi.
  Full outgoing request guard vẫn kiểm mỗi call.
- Model/budget đổi dùng native SummarizationMiddleware constructor mới qua
  existing hook; không mutate private trigger/recompile graph mỗi bước.
- Box graph/recipient facts snapshot một lần/activity; tên/description đọc lại
  invocation sau, không thêm invalidation service. Reuse box description hiện có.
- Leti context chỉ box name/purpose, own name, teammates/descriptions/
  representative và routable recipient IDs; root recipient chỉ representative.
  Không teammate prompts/full edge matrix/own UUID/storage IDs/model config.
- Role template dùng `Your instructions` + `{{agent_instructions}}`, Leti thêm
  `{{box_context}}`; native LF composition/compile. Bỏ time/timezone hoàn toàn.
- F03: known Temporal-wrapped business rejections thành tool error feedback;
  infrastructure failures vẫn raise. Metric outcome đọc ToolMessage.status.
  Issue33504 chỉ TODO/link, không recovery/parser/retry middleware.

### 6. Cache-friendly compaction

- Native SummarizationMiddleware sở hữu trigger/cutoff/tool-pair-safe tail/state
  replacement; custom summarizer chỉ dựng request qua public hook.
- Same executing model/effort/settings, stable system, ordered tools và native
  prefix do middleware chọn; append compaction user instruction. Không model
  riêng, replacement system hoặc flatten XML; summary call không thực thi tools.
- `trim_tokens_to_summarize=None`. Budget gồm system/tools/messages/compaction
  instruction/output reserve. Configurable `trigger_fraction: 0.8`,
  `keep_fraction: 0.3` dưới `services.leta.compaction`; validate tại startup.
  Tính trên usable history budget H sau overhead, không toàn context window.
- Checkpoint giữ rolling summary + bounded recent tail + continuation/cursor;
  summary cũ tích hợp vào summary mới. Không summary table hoặc adaptive engine.
- Summary giữ goals/decisions/confirmed-or-unknown effects/pending work/IDs/
  paths/recipients. Compaction là paid call với prompt/cost riêng.
- Capture outgoing main/summary prefix/cache usage để kiểm thực; stable prefix
  không là cam kết provider cache hit, 0.8/0.3 chưa là empirically optimal.

### 7. Checkpoint, history và streaming

```text
native graph step + sync checkpoint
→ một public-history transaction
→ một Redis projection pipeline sau commit
→ native keep_latest pruning
→ bước kế tiếp
```

- F02: thay record-per-entry bằng batch thật: ordered entries/dedupe trong RAM,
  một connection/transaction/agent lock, batched existing-ID lookup, một counter
  allocation cho entries mới và multi-row insert. Áp cả startup recovery.
- Redis projection giữ individual events/order/schema/IDs/maxlen/TTL; XADD từng
  event + EXPIRE một lần trong một pipeline sau SQL commit. Ba tool results từ
  3 transactions/12 data statements/6 pipelines xuống một transaction/một pipeline
  chứa sáu events. Không chỉ bọc outer transaction quanh record loop cũ.
- Checkpoint/history vẫn hai transactions. Projection lỗi thì không resume/prune;
  restart project missing entries từ checkpoint theo stable IDs trước tiếp tục.
  Không gọi lại model/tools để dựng transcript, outbox/recovery daemon/custom saver
  hoặc transaction dài qua inference/tool execution.
- Native keep_latest vẫn giữ required pending writes/blobs khi cần, không hứa
  chỉ một SQL row. Public history giữ inputs/assistant/tool calls/results/summaries,
  MVP không purge. Summary append lúc compact, không renumber/chèn ngược timeline.
- Giữ history recent20 + before/next_cursor, detail200 lines/next_start_line,
  kind=compaction; scrollback qua PostgreSQL, client không đọc checkpoint/Redis
  làm full transcript. Không frontend/raw-provider archive mới.
- Provider text/tool-argument chunks vẫn live Redis, không SQL mỗi token/timer
  buffer. Align Live text ID với canonical persisted history ID hiện có.
- F17: batch terminal events có sẵn; bỏ pre-XREAD range read chỉ sau proof
  missing stream/cursor gap/trim vẫn resync đúng. Giữ bounded replay/snapshot.

### 8. Temporal inbox wake

- F04: runtime result thêm status + durable checkpoint inbox_cursor. Workflow
  giữ highest admitted seq/last returned cursor bằng max; chỉ wake do inbox khi
  có seq mới hơn, gồm late/out-of-order receive handler completions.
- Không clear wake vô điều kiện khi activity kết thúc; tin có thể tới sau final
  idle check. Control start/resume/pause/cancel giữ riêng; backlog cũ không tự
  restart lượt user vừa cancel. Idle dùng EXISTS, middleware duy nhất nạp batch.
- Cursor nói đã vào context/checkpoint, không khẳng định task đã giải quyết xong.
  Không DB state/polling/RPC/activity mới hoặc đọc saver từ workflow.
- Giữ workflows/queues/native rollover hiện có. Kiểm actual histories trước
  đổi result/deploy; không tự reset/terminate hoặc thêm legacy decoder framework.

### 9. Mirage/filesystem và tối ưu domain/API

- F06: file tools tự lấy lazy Filesystem session, một Workspace+Session/activity;
  async lock nhỏ cho first-init/mount refresh. Bỏ Context.session/node-name scan.
  Giữ cleanup khi activity thoát, retry mở lại ephemeral resources.
- Giữ Redis-only allowlist, whole-file bounded cache TTL600s, mount discovery
  TTL30s/HITL invalidation và write invalidation. Skip mount diff khi không đổi;
  cached hit không thêm remote Stat/auth/version RPC.
- F18: slice file window trước format; không enumerate/format cả file để lấy200
  lines hoặc đổi thành range RPC mỗi read. History-read tối ưu khi có số đo,
  không truncate rồi claim đọc được full body.
- Native shell streaming chỉ giữ bounded stdout/stderr trả agent, vẫn drain/
  settle command và full redirection vào file. Không @all producer cap hoặc
  custom runner/watchdog/collector framework.

| Finding / owning path | Thay đổi                                                                                                                        |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| F09 root notification | SQL preview/routing projection thay full body, giữ budget/cursor/grouping; Leti vẫn full bounded batch                          |
| F10 inbox routing     | Resolve box/agent trước user permission check; reuse held same-root gate sau scope validation; durable admission vẫn revalidate |
| F11 permission lists  | Native SpiceDB CheckBulkPermissions, dedupe workspace IDs/page; fully consistent, errors không thành grants                     |
| F12 narrow reads      | Scoped lookup/JOIN cho representative/ownership/existence; rich box_get giữ đủ members/edges                                    |
| F13 schedules         | PATCH/DELETE bỏ forecast Describe RPC; GET/calendar giữ; INSERT/UPDATE RETURNING cho normal readback                            |
| F14 box create        | Bulk insert members/edges thành hai batches trong existing atomic transaction/gate/receipt                                      |
| F15 worker/HITL       | JOIN control+unfinished run, owner/update-returning; HITL facts re-read đúng effect-lock phase                                  |
| F16 refresh/cleanup   | Skip archived agents, reuse root/box facts; bounded independent fanout trong mỗi phase, giữ teardown barriers                   |
| F19 wiring            | API/tools dùng chung existing owner cho native HITL/schedule submission; bỏ redundant wait chỉ sau readiness proof              |

Không bỏ permission/mutation locks/receipts/atomic edit/source-version filter
hoặc cleanup ordering để giảm query count. Index tuning chờ EXPLAIN, không sửa
initial migration đã áp dụng hoặc thêm index cho mọi optional filter.

### 10. Chi phí LLM, embedding và rerank

- LiteLLM native registry/custom deployment prices tính cost; LF nhận explicit
  request cost/aggregate. Supplier cùng group có giá riêng. Không backend price
  calculator/OpenRouter price fetch/LF pricing sync; chỉ dùng supplier rates thật.
- Coverage: agent LLM + compaction; file processing enrichment attempts/corrections
  - embedding batches; semantic search query embedding + rerank khi bật.
- Streaming bật include_usage + include_cost_in_streaming_usage; final usage.cost
  qua ChatLiteLLM metadata. Nonstream/embedding/rerank đọc native cost headers/
  metadata. Rerank giữ native billed units/pricing, không bịa tokens từ hit count.
- Small inline cost callback gắn total vào existing LF generation trước native
  callback hoàn tất; không subclass/export generation thứ hai.
- Ingest ghi từng raw completion trước Instructor cộng usage; không count raw
  attempts và aggregated response hai lần. Embedding đúng observation type,
  không vectors hoặc observation mỗi chunk.
- Go annotate provider spans từ native cost/usage. Missing/final chunk mất là
  unknown, không zero; cached/reasoning tokens là subsets. Sum paid leaves,
  không cộng parent aggregates; inferred manufacturer price không là actual cost.
- Session agent ID/trace mỗi graph invocation, Leti session riêng và root/box/
  workspace/run metadata. Ingest theo file/source_version/stage, không gán owner
  thành actor hoặc mọi ingestion vào agent session.
- Cloud proof xác nhận Go RAG cùng trace nhưng thiếu session. Người dùng đã
  duyệt native baggage chỉ trong SemanticSearch nội bộ, không thêm RPC/request.
  Go copy allowlisted UUID attribution vào existing spans; không forward provider.
  Cloud đã xác nhận retrieval/query embedding cùng session agent.

### 11. Observability và Cloud acceptance

```text
Python shared OTel provider/context
  ├─ core processor/exporter → Alloy → Grafana Cloud Tempo
  └─ native LF processor/exporter → Langfuse Cloud
Go selected AI spans → Alloy → Langfuse Cloud OTLP
Metrics → Alloy → Grafana Cloud Mimir
Container JSON logs → Alloy → Grafana Cloud Loki
```

- Reuse existing native instrumentation/Alloy/dashboard assets. Local chỉ Alloy
  và native state/WAL; không self-host Prometheus/Tempo/Loki/Grafana/LF backends.
- Native LF callback run_inline, trace mỗi invocation/session agent ID; preserve
  Temporal tracing. LF default AI filter + đúng SemanticSearch client nối cây.
  Go retriever/embedding/rerank qua Alloy; Python LF spans không forward lần hai.
- RAG tree tool→RPC client→server retriever→embedding/optional rerank; capture
  final authorized hits, không rejected candidates/vectors/per-hit observations.
  Supported native gen_ai.* attributes; không custom attribute mapper framework.
- Grafana theo dõi toàn file pipeline queue/parse/export/enrich/embed/upsert/commit/
  errors/process/dependencies; LF đi sâu AI content/usage/cost/prompt version.
  Correlate trace/file/source_version trong spans/logs, không metric/Loki ID labels.
- Tempo strip AI content, giữ operational timings/models/errors. Sample ratio1.0
  cho demo, native bounded batches/queues/flush shutdown; telemetry outage không
  rollback business effects. Không span/observation mỗi token/heartbeat.
- Verify bốn dashboard groups: services, infra/datastores, Temporal/workers,
  Leta runtime/stream/state; native scrapes/container logs/exporter failures.
  Alert tuning theo workload, không tự gửi contact/webhook test.
- Acceptance cần actual app data trong Grafana/LF, không empty OTLP200/local sink.
  Cloud proof phát hiện full dependency metrics vượt active-series limit khi idle.
  Native Alloy metric allowlist giữ dashboard/alert và essentials; traces/logs/LF
  giữ nguyên. Báo actual Cloud Usage series và idle estimate; không quota/sampling
  controller. Xem execution cho số đo và old-series window.

### 12. Langfuse prompt management và publication

- Năm prompts: leta/common, leta/root, leta/leti, leta/compaction, letfs/enrichment.
  Root/Leti pin numeric common version bằng native references; không runtime
  fetch/concat common lần hai. Defaults/config version cùng prompt; mission ở SQL.
- Pin role/compaction PromptClient/config một lần/activity; enrichment resolve
  tại owning call. Native RAM cache60s/stale-while-revalidate; compile variables,
  chỉ compile lại khi instruction inputs đổi. Production label change không thay
  pinned prompt giữa lượt; DB overrides vẫn áp ở safe boundary.
- propagate_attributes(prompt=...) chỉ link name/version, không snapshot copy;
  compaction scoped override đúng prompt, giữ native generation input capture.
- Hoàn thiện/review wording, publish versions/config thật lên Cloud; common trước,
  rồi role references. Verify resolved variables/root/Leti/enrich/compact calls.
  Thử qua Openlet → production label → theo dõi → rollback label khi cần.
- Không coi Markdown/fixture là publication. Cold prompt miss khi LF down vẫn
  có thể fail theo accepted demo limit; không fallback artifact/release service.

### 13. Xóa và không triển khai

- Xóa local catalog/types/YAML defaults, direct ChatOpenAI/provider wiring,
  provider-specific reasoning body, per-step runtime construction, XML summary,
  clock/string-concat prompt, duplicate session ownership và per-entry writer.
- Xóa confirmed-unused public Services.platform/imports, config.settings alias,
  LetFS.read_text_lines và direct dependencies khi không còn caller/owner.
  Giữ internal Platform client và actual native SDK/transitive needs.
- Xóa duplicate submission glue, brittle tool-count-only assertions và tests chỉ
  bảo vệ cấu trúc đã bỏ; giữ permission/schema/runtime-injection/business tests.
- Không legacy/backward compat/deadcode/copy archive, custom router/provider/
  pricing/JSON repair, outbox/recovery daemon/summary table/telemetry service.
- Không frontend, evaluation/Playground/A-B, prompt sync/release framework,
  retention purge, ownership transfer hoặc storage visibility API scope mới.

### 14. Checks, benchmark và cutover

- Python typing chuẩn/Pyright strict cho Leta/ingest/SDK/scripts; không blanket
  Any/cast Any/tắt strict. Format/lint/Go/TS/build/generation checks theo project.
- Reuse existing narrow suites cho model selection/cache, tool stream, Instructor
  invalid→valid bounded attempts/modes, embedding space và RAG rerank on/off.
- Verify graph/client reuse/settings updates, one parallel lazy Mirage session,
  bounded returned shell output nhưng full file redirection/settlement.
- Batch history seq/identity/order/replay/Redis counts; fault-inject đúng
  checkpoint-committed/history-not-committed gap, gồm compact; recover trước
  resume/prune, không rerun confirmed effects chỉ để tạo public transcript.
- Test late inbox/cancel/pause/resume, summary detail/older history pagination
  sau compact/restart/prune, cursor-gap resync; schedule mutation không forecast,
  permission bulk không grant nhầm, box atomicity và cleanup ordering.
- Temporary before/after benchmark cùng fixtures/workload, warm-up/repeats;
  report setup/median/p95/graph construction/SQL/Redis counts. Scripts/raw results
  ở /tmp, không source/CI; không gọi overhead gain là tốc độ provider/LLM.
- Focused checks trước, relevant full checks/shared e2e/api sau; không Leta E2E
  suite riêng hoặc paid model load test mỗi PR. Commit theo owning boundaries
  khi thực hiện implementation, không tự commit trong lượt tổng hợp này.
- Demo upload/process/search→agent tools/stream/inbox→Leti→compact/restart→final;
  kiểm actual Cloud tree/cost/prompt links/Grafana signals và R2 presigned/CORS
  theo origin thực. Reuse existing Cloud/R2 setup, kiểm secret presence privately.
- Không duplicate stack/process/ports, reset DB/Temporal/index/recreate workspace
  hoặc tự reindex. Kiểm existing histories trước result-contract cutover.
  Rollback prompt bằng label, gateway bằng image/config, app bằng coherent code/
  config; không shim. Ghi execution evidence và limitations thật, không secret.

## Kết quả cần đạt

Leta/Leti, enrichment, embedding và optional rerank đi qua một LiteLLM Proxy.
Langfuse quản lý prompt cùng task model/parameters, nhận actual request cost;
compaction giữ native message/tool prefix để có cơ hội tái sử dụng provider cache.
Runtime tái sử dụng graph/client, cung cấp đủ box context cho Leti và tận dụng
Langfuse variables/composition. Publish các prompt đã review lên Langfuse Cloud.
Xóa local catalog, direct-provider wiring và các implementation bị thay thế.
Giữ domain, Mirage, inbox, streaming và checkpoint guarantees đã duyệt; hai
contract changes được chốt thêm là runtime result cursor và LetFS search hit path.

## Phạm vi và authority

- [Decision ledger](decisions.md): từng commit, quyết định còn hiệu lực, proposal đã bỏ,
  bằng chứng và giới hạn; không coi mọi nội dung committed là approved.
- [Thiết kế chi tiết](design.md): ownership, config, clients, listing/selection,
  structured output, retry, costs, prompts, compaction và Cloud topology.
- [Triển khai và acceptance](implementation.md): file map, commit boundaries,
  dependency order, checks và cutover/rollback.
- [Rà soát toàn bộ agent.py](design.md#11-runtime-optimization-và-box-context):
  từng vị trí cần tối ưu/sửa, phần giữ nguyên và cách reuse graph khi settings đổi.
- [Rà soát toàn bộ Leta](../reports/review-261114-leta-efficiency.md): 29 files,
  F01–F19, I/O thừa ngoài agent.py, native probes và phạm vi optimization đã chốt.
- [Đối chiếu Instructor/compaction/history](../reports/research-261114-0228-compaction-instructor-history.md):
  pinned SDK source, OpenCode/Codex/Claude Code và pagination/summary exposure hiện có.
- [Inference đã duyệt](../261111-2010-leta-rewrite/inference.md),
  [Leta](../261111-2010-leta-rewrite/plan.md),
  [observability](../261113-1335-system-observability/plan.md) vẫn là owning scope.
  Plan này gom phần triển khai tiếp theo, cập nhật quyết định đến 2026-11-14 02:02.
  Các proposal automatic output mode/capability filter trước đó đã bị thay thế.

Không rewrite lại toàn bộ hai plan đã có code. Không evaluation, Playground,
A/B, prompt sync/release framework, custom router/provider/pricing engine,
LiteLLM DB/Redis/response cache, Rust RC, financial ledger hoặc frontend mới.
Không skills/subagents, legacy/backward compat hoặc copy archive. Python typing
chuẩn/Pyright strict áp dụng cả Leta, ingest, SDK và scripts.

## Các phase và phụ thuộc

| Phase | Nội dung                                                            | Phụ thuộc / kết thúc                                                     |
| ----- | ------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| 1     | Pinned dependencies, stable Python Proxy, shared config/env/Compose | Boot và native metadata/chat/embedding qua Proxy                         |
| 2     | Metadata snapshot, Leta model listing và selection                  | Phase 1; giữ `model_id` và `reasoning_effort` hiện có                    |
| 3     | Prompt Config và native clients Leta/ingest/Go                      | Phase 1–2; YAML chọn output mode, Vilao dùng Instructor TOOLS            |
| 4     | Per-request cost, usage và AI observation integration               | Phase 3; không duplicate; attribution gate độc lập                       |
| 5     | Runtime optimization, box context, prompts và compaction            | Phase 3–4; benchmark trước/sau, publish LF, wire prefix và restart proof |
| 6     | Shared E2E, local demo/Cloud acceptance, docs và xóa code cũ        | Các phase trên; không inference trả phí trên mọi PR                      |

Mỗi boundary là focused conventional commit; không dồn một commit lớn.
Một phase có thể chia config/consumer/delete commits khi review dễ hơn, nhưng
không để compatibility layer thành trạng thái hoàn tất.

## Quyết định cuối và verification còn lại

- Giữ hai field `model_id` và `reasoning_effort`; DB selection ưu tiên hơn
  Langfuse defaults, Leti giữ inheritance. Config LF phẳng, không `default` wrapper.
- Ingest có `output_mode: tools | json_schema | text` trong YAML; Vilao dùng
  `tools`. Instructor sở hữu parsing/validation/correction, không validator thứ hai.
  Không automatic mode fallback hoặc custom capability intersection/filter.
- LangChain invalid-tool-call issue chỉ thêm TODO/link tại `create_agent`;
  không workaround/retry middleware. Giữ giới hạn đã biết theo [design §11](design.md#11-runtime-optimization-và-box-context).
- **Chi phí RAG theo agent:** đã kiểm Cloud và chốt native baggage trong đúng
  internal SemanticSearch; không thêm RPC/request hoặc provider propagation.
  Session attribution đã được verify, xem [execution](execution.md).
- Supplier prices/credentials/verified limits là input vận hành: kiểm những gì
  đã có trước khi hỏi. Không tự chọn supplier priority/weights hoặc bịa values.

Không hỏi lại các quyết định đã chốt. Dừng hỏi khi implementation thật sự đòi
trade-off hoặc thay contract chưa được duyệt; không biến verification thành
thiết kế capability/router mới.

Người dùng đã chốt F04 consumed-cursor handoff để tránh empty wake activity,
F07 relative paths trong LetFS search hits và F18 bounded shell output capture
giữ nguyên full file redirection/command settlement. Đã chốt thêm PATCH model:
đổi model bỏ effort thì clear effort cũ; effort-only cần explicit model.
Các tối ưu SQL/RPC cùng semantics vào Phase5 theo owning functions.

Không còn quyết định kiến trúc/sản phẩm đã biết phải chốt trước khi bắt đầu.
Verification còn lại không cho phép tự mở rộng scope:

- F04: kiểm existing workflow histories trước đổi result; không tự reset,
  terminate executions hoặc thêm legacy result decoder/versioning layer.
- RAG cost: gate đã giải quyết bằng Cloud proof và user approval cho scoped
  native baggage; không thêm lookup/service/ledger.
- F18: dùng native Mirage stream, giữ capture hữu hạn nhưng drain/settle đầy đủ;
  nếu public API không đáp ứng thì trình limitation, không tự dựng runner mới.
- Review prompt wording trước Cloud publication; đây là content review đã định,
  không thiết kế lại prompt management.
- Demo bật upstream đã có credentials; không tự chọn multi-provider priorities,
  bịa giá hoặc đổi embedding space. Index tuning chờ EXPLAIN.

Chỉ dừng hỏi khi bằng chứng buộc thay contract/guarantee ngoài phạm vi này;
đưa vấn đề cụ thể và phương án nhỏ nhất. Các chi tiết code/test/SDK thông thường
tự xử lý trong thiết kế đã duyệt, không biến mỗi verification thành approval gate.

## Acceptance cuối

- Một group name, nhiều native upstream deployments; app không giữ provider list,
  price table hoặc task default model trong YAML.
- Leta model-list lấy subset `leta` từ gateway, deduplicate; chọn group/effort đúng
  actual capability và root/Leti inheritance, không expose credentials.
- Native chat/tools/stream, Instructor schema extraction và single/batch/query
  embedding đi qua gateway; rerank tắt vẫn RAG hữu ích và đúng quyền/source version.
- Retry transport chỉ ở Proxy; Instructor correction hữu hạn; Temporal recovery
  giữ nguyên và không bị trình bày sai thành exactly-once inference.
- Actual usage/cost của LLM, embedding và rerank đến đúng LF observations;
  file processing và semantic search có attribution đúng, kể cả paid corrections;
  missing là unknown, không zero; không count Instructor aggregate hai lần.
- Prompt/version/config pin mỗi invocation; common numeric reference, label
  rollback, cache behavior và compaction link đúng. Templates dùng variables,
  heading `Your instructions`, Leti nhận box context cần thiết, không time context.
  Prompt versions/config thực sự cập nhật lên LF Cloud và chạy qua Openlet;
  không coi local draft hoặc fixture là publication acceptance.
- Graph/middleware dựng một lần mỗi activity; clients được reuse. Boundary
  checkpoint/projection/prune/cancel vẫn đúng; benchmark trước/sau có setup và
  giới hạn rõ, script chỉ ở thư mục tạm, không source/CI.
- Compaction giữ exact system/tools/native prefix, summary + bounded tail,
  checkpoint restart và `keep_latest`; không flatten XML hoặc model riêng.
- Compaction thresholds cấu hình được, initial defaults 0.8/0.3 trên usable
  history budget. Batch history transaction độc lập native saver, recover gap
  trước resume/prune; live text identity khớp canonical history.
  Projection Redis dùng một pipeline/boundary sau SQL commit, giữ individual
  events/order và live token streaming; không per-entry transaction/pipeline.
- Narrow tests, strict Pyright, format/lint/build và shared API E2E pass.
  Cloud proof cần actual app telemetry, không chỉ empty ingestion HTTP 200.

## Trạng thái

Application changes đã triển khai và chia commit theo boundary. Năm prompt
version1 đã publish lên Langfuse Cloud với production label; native composition,
variables, pinning/cache/label rollback đã kiểm. RAG session propagation được
chốt trong lúc acceptance sau khi Cloud chứng minh thiếu session.

Xem [execution](execution.md) cho kết quả checks, benchmark, crash recovery,
Cloud/demo và giới hạn chưa kiểm. `.env.example` giữ riêng thay đổi local xóa
comments của người dùng; không commit secrets hoặc raw acceptance payloads.
