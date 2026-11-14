# Implementation và acceptance — 2026-11-14

Owning scope: [plan](plan.md), F01–F19 và quyết định cuối trong conversation.
Code đã triển khai; Cloud metric cardinality đang được đo sau filtering. Không
coi scrape thành công hoặc OTLP200 là proof đã ingest đủ.

## Boundary đã triển khai

| Commit | Boundary |
|---|---|
| `4b40cfe` | Pinned native LiteLLM Proxy/SDKs/Instructor Git dependency |
| `1d62802` | Shared config, native inference consumers, Instructor correction/cost, fixtures |
| `076d5e6` | Scoped LetFS search paths, generated contracts, float embedding/native cost, RAG attribution |
| `bbae09c` | Gateway model metadata/cache/selection và domain/API query batching |
| `017ac43` | Batch history/Redis projection, checkpoint DSN, inbox consumed-cursor handoff |
| `ed054ff` | Reused graph/client/Mirage, managed prompt/context, prefix-preserving compaction |

Không local model/price catalog, provider router, JSON repair/extra validator,
legacy decoder, second saver/outbox hoặc service observability mới. Local
`.env.example` comment deletion của người dùng giữ unstaged; provider/env changes
cần cho implementation được commit theo boundary, không secrets.

## Dependencies và inference

- LiteLLM1.109.1, ChatLiteLLM0.11.2, LangChain1.5.0/LangGraph1.2.21;
  Instructor official Git SHA `aeb7e2558166caeec497e541bcfc6b4eaa2cf53b`.
- Proxy stable image digest pin tại Compose. Named Vilao credential dùng native
  OpenAI-compatible adapter; public logical groups tách khỏi upstream names.
- App/SDK transport retries0; Proxy retries1. Native Instructor `max_retries=1`
  đã được kiểm là **tối đa hai completions**, gồm initial+correction.
- Tools/json_schema/text extraction modes có native tests, gồm invalid→valid và
  hết correction budget. Không additional app validation hoặc mode fallback.
- Ingest/query float encoding, dimensions và response indices/count checks.
  Rerank optional; actual demo off, fixture integration on.
- Unknown request cost omitted, explicit zero giữ; cached/reasoning counts là
  subsets được biểu diễn thành additive Langfuse categories. Instructor ghi mỗi
  paid attempt trước khi SDK cộng retry usage, không ghi aggregate lần nữa.

## Checks và integration

- `make generate`: pass, contracts/generated SDK/public descriptor đồng bộ.
- `make check test`: pass; strict Pyright0, Ruff/format, gofmt/vet/tests,
  Prettier, TypeScript, Buf lint và shell syntax. **36 Python tests pass**.
- Shared `e2e/tests/api`: **5/5 pass, 56.1s** qua real services/Temporal/Proxy,
  với WireMock upstream và isolated test storage. Không paid CI provider calls.
- Lần E2E trước phát hiện hai assertion mới sai: cứng thứ hạng search path và
  kỳ vọng400 thay vì native422. Sửa tests theo contract, không đổi sản phẩm để
  giữ expectation sai. Final suite đã chạy lại đủ5 bài.
- Native lazy filesystem concurrency test: năm parallel first-use tools chỉ tạo
  một Workspace/Session; unchanged mounts không apply lại, mode change vẫn apply.
- Native shell test: bounded returned stdout/stderr nhưng full redirected file
  vẫn chứa toàn bộ output và command được drain/settle.
- Workflow test: consumed/late/out-of-order admission không tạo activity rỗng;
  new seq đánh thức; cancellation suppress backlog cũ, new input vẫn chạy.

Raw logs/scripts ở `/tmp`, không source/CI. Shared E2E results theo convention
`.local/e2e/results`, generated files/credentials không commit.

## Checkpoint/history crash gap — PostgreSQL/Redis thật

Temporary proof dùng native AsyncPostgresSaver, real Leta schema và Redis;
PG trigger cố ý làm history INSERT fail **sau checkpoint commit**, lần lượt tại
`tool_result` và `compaction`. Đóng/mở saver rồi gọi owning projector trước
resume/prune:

- Confirmed tool effects thực thi **một lần**.
- Public history33 entries; summary seq32; pagination20+13 vẫn đọc được history
  trước compact. Summary detail đọc qua owning history API.
- `keep_latest` để lại một checkpoint row trong workload này; không hứa mọi
  native pending-write/blob workload chỉ có một SQL row.
- Ba results mới:4 data statements,1 transaction,1 Redis pipeline. Replay không
  tăng sequence/duplicate rows. Không custom saver/outbox/recovery daemon.

Artifacts tạm: `/tmp/openlet-history-proof.log` và script cùng basename. Isolated
proof containers đã remove; demo/legacy volumes không bị reset.

## Benchmark cùng workload

Real PostgreSQL/Redis; baseline functions từ `d69be44`, current code; ba tool
results mỗi sample;5 warmup+30 samples, cùng máy và fixture. Không paid LLM loop.

| Projection | Baseline | Current |
|---|---:|---:|
| Median | 15.621ms | 5.605ms |
| p95 | 16.270ms | 6.396ms |
| Data statements | 12 | 4 |
| Redis pipelines | 6 | 1 |

Median riêng bước projection giảm khoảng64%; không gọi đây là tăng tốc LLM
hoặc toàn agent. Graph/tools construction current median3.571ms/p954.118ms,
chỉ một lần/activity thay vì một lần/boundary. Client reuse và settings refresh
được native runtime test kiểm, gồm instruction/model changes và tool-safe tail.
Temporary scripts/results: `/tmp/openlet-benchmark-final.py`/`.json`.

## Prompt publication và actual inference

Năm Cloud prompts **version1**, label `production`:

- `leta/common`
- `leta/root`
- `leta/leti`
- `leta/compaction`
- `letfs/enrichment`

Root/Leti reference numeric common1 bằng native composition, compile instructions
và box_context; không unresolved references/placeholders/time context. Flat role/
enrichment config có logical model/effort/output budget; compaction không model
riêng. Model observations dùng group name, không SDK `litellm_proxy/` prefix.

Thử latest thực tế trước promote production; native temporary prompt kiểm label
switch/fresh fetch/pinned client và rollback1→2→1 rồi delete. Native SDK invalidates
local label cache khi cùng client update; pinned PromptClient vẫn version1.
Không release framework/copies hoặc Playground/eval scope mới.

Actual root→box→Leti delegation chạy với Leti prompt/box context. Native compaction
chạy actual provider qua owning ExecutionModel/SummarizationMiddleware, dùng
lower thresholds **chỉ trong temporary acceptance process**, không sửa production
0.8/0.3. Native summary+tail được giữ; Cloud generation link compaction1 và có
usage/cost/cache-read tokens. Exact system/tools/prefix equality có native test;
cache usage là provider report, không cam kết cache hits cho mọi request.

## Actual demo, R2 và streaming

Demo project `openlet-demo`, một stack trên máy hiện tại. Existing legacy
`openlet` database volumes có schema/credentials cũ: không reset/migrate chúng.
Fresh isolated demo volumes được dùng; không có duplicate running worker stack.
E2E chạy riêng sau khi dừng demo, cleanup chỉ test project, rồi demo khởi động lại.

Actual journey:

1. Presigned XLSX upload qua R2, CPU parse, IO enrichment/embedding, published
   artifacts và searchable ready state. Inline text không phải blob processing
   input; acceptance đã dùng đúng upload pipeline.
2. Agent semantic search→read evidence→shell tính270→ghi home file; không gửi
   inbox message cho người ngoài.
3. Root tạo box qua native API, delegate Leti; Leti search/read/reply root.
4. Production-label final invocation:17 live text chunks; tất cả text message IDs
   khớp canonical SQL history,6 new history entries. Tokens đi Redis/SSE, không
   PostgreSQL mỗi token.
5. R2 origin đã có `http://127.0.0.1:8765`: thêm checksum header còn thiếu vào
   existing CORS rule, giữ origin/methods/other rules. Native OPTIONS204,
   presigned PUT200, exposed ETag và CompleteUpload pass. Đây là browser-protocol
   proof; không thêm frontend product vào scope này.

## Cloud observability và cost

- Actual Langfuse observations: streaming agent generations, enrichment paid
  attempts, file embedding và Go retrieval/query embedding. Usage/cost/prompt
  links có dữ liệu thật; không observations mỗi token/vector/per chunk.
- Cloud chứng minh Go trace association tự nó không đủ cho session aggregation.
  User đã duyệt native baggage **chỉ existing SemanticSearch**, không thêm RPC
  hoặc request. Production ToolNode/Mirage/RPC proof: both retrieval/query
  embedding có cùng trace/session agent. Provider request không mang baggage
  được focused test kiểm. Attribution labels không dùng làm permissions.
- Go embedding/RAG spans export qua Alloy đúng một lần; Python native LF exporter
  giữ callbacks/processor. Native inline cost callback update existing generation,
  không tạo generation thứ hai. Sum paid leaves, không parent aggregates.
- Bốn native Grafana dashboards đã import vào folder Openlet: infrastructure,
  Leta, services, workers. Ten native scrape targets từng verify `up=1`.
- Actual app metrics có ingestion-stage durations, inbox/process/resource series;
  Loki có JSON app logs; Tempo có real agent/RAG trace và không AI input/output
  content attributes. Empty idle/error histograms không tự là lỗi.
- Alert assets có datasource/folder placeholders; scrape selector sửa đúng native
  postgres/redis job names và LiteLLM. Không activate notification/contact point
  hoặc gửi alert test cho người khác.
- **Vilao supplier rates chưa được cung cấp/xác thực.** LiteLLM native registry
  totals có thể là manufacturer estimates; không coi là bill Vilao thật. Không
  invented prices, backend calculator hoặc tự claim đã test cả3 suppliers.

## Cloud metric cardinality follow-up

Full native dependency collection vượt quota ngay khi idle. Actual Temporal
endpoint khoảng20000 samples; riêng poll/pri_poll buckets4000. Cloud log native
429 ghi limit15000; usage datasource có old active-series count cao hơn sau nhiều
restarts. Không cần account mới; đây là active cardinality, không monthly quota.

User yêu cầu filter giữ operational coverage, preserve workflow/activity traces,
và báo số active thực + idle estimate. Một native `prometheus.relabel.essential`
áp trước remote_write cho cả OTLP metrics và scrape paths. Không đổi sample1.0,
trace/log/Langfuse paths hoặc thêm quota controller. `alloy validate` pass.

Initial same-endpoint filter counts: Temporal20038→104, SpiceDB711→16,
Envoy1423→2, Alloy775→54. Đây là sample counts trên endpoints, **không phải tổng
active series Cloud sau lọc**.

Đo lúc idle23:11UTC ngày2026-11-13 (06:11 ngày14 tại Việt Nam):

| Số đo | Giá trị | Ý nghĩa |
|---|---:|---|
| Unique labelsets đầu ra filter | 1160 | Native Alloy live debugging, capture65s sau sửa mount, đủ16 jobs |
| Cloud active series | 419 | Cloud Usage thực tế, **chưa nhận đủ** series mới |
| Cloud memory series | 36913 | Series cũ vẫn nằm trong TSDB head |
| Memory-series limit | 36000 | Native `max_global_series_per_user` |
| Active-series limit của tenant hiện tại | 15000 | Native `max_active_series_per_user`; không coi đây là Free allowance5000 |

Local output gồm LetFS232, PostgreSQL162, host145, Leta worker127, Temporal105,
Alloy86, LiteLLM68, Platform62, Leta API58, SpiceDB17, cAdvisor71, Redis8,
ingest CPU6, ingest IO6, Qdrant4 và Envoy3. Native debug chỉ bật tạm trong
generated config để đo, đã tắt/reload; không thêm collector hoặc source script.

Sau filtering, remote-write pending0/failed0 và không thêm429. Tuy nhiên Cloud
`samples_discarded{reason="per_user_series_limit"}` vẫn tăng: ingester memory
limit khác active-series limit. Vì vậy419 **không** được dùng làm steady-state
idle total hoặc claim mọi panel đã đủ dữ liệu. Native debug xác nhận actual
Leta tool/state và RPC/process metric labelsets qua filter; Cloud acceptance
những metric này còn chờ old-series head compaction, có thể mất vài giờ.
Không xóa metrics/WAL/data hoặc tạo account mới để né giới hạn.

Ước tính cùng topology lúc idle: khoảng1.3k series gồm1160 forwarded và Cloud
generated series; thấp hơn Free allowance5k, còn khoảng3.7k headroom. Idle
không tự cộng dồn active series theo thời gian nếu labelsets giữ nguyên.
Restarts/replicas/model/tool combinations tạo labelsets mới, nên đây không phải
load forecast cho mọi workload. Trace/log/Langfuse quotas tách riêng. Số active
đầy đủ phải đo lại sau khi memory-series quota giải phóng.

Final `make check` và native deployed `alloy validate` đều pass. Acceptance cũng
phát hiện cAdvisor chỉ thấy root cgroup vì `/sys` mount nhầm tại `/host/sys`.
Temporary isolated native collector chứng minh mount `/sys:/sys:ro` sửa được
CPU/RAM từng container mà không privileged. Đã áp cùng path cho Unix exporter;
cAdvisor dùng native Docker-only, CPU/memory/network và không arbitrary Docker
labels. Deployed endpoint có CPU/RAM của đủ14 demo containers; không `container_fs`
families thừa. Temporary collector đã xóa.

## Giới hạn

Không paid load test, supplier failover bằng ba live credentials, index tuning,
full UI browser journey, production alert delivery, multi-replica/load benchmark
hoặc evaluation. Cold Langfuse prompt-cache miss vẫn cần Cloud theo accepted
MVP limit. Known invalid-only tool-call LangChain issue33504 chỉ TODO/link như
đã chốt. Không thay bằng custom retry/repair middleware.

## Golden-journey follow-up: workspace read-after-create

Real preparation phát hiện `CreateWorkspace` bỏ mất final storage ZedToken mà
workflow đã trả về. Đọc ngay workspace/storage có thể bị permission denied hoặc
thiếu storage vì caller chỉ có revision cũ. RPC nay trả header
`x-openlet-zed-token` giống `Onboard`; không thêm retry hoặc consistency layer.
Native caller truyền header đó sang `ListStorages`: workspace mới đọc ngay đủ
Shared/Personal và upload R2 thành công, không polling quyền. Go platform tests
và vet pass. Golden scripts/materials nằm ngoài source tại `/tmp`.

## Golden-journey follow-up: enrichment semaphore deadlock

Microsoft FY25Q4 workbook thật tạo116 artifacts, gồm91 CSV. Pipeline giữ
`ai.slots` khi fetch artifact/generate metadata, nhưng `Models.describe` lại
acquire cùng semaphore. Đủ concurrent artifacts sẽ giữ hết outer slots rồi
chờ inner slots: không request inference nào bắt đầu, heartbeat vẫn còn.
Bỏ inner acquire; giữ existing outer admission cho download/vision/correction
và existing embedding admission. Không tăng concurrency hoặc thêm semaphore.

Existing Instructor tests nay chạy khi pipeline đã giữ slot với concurrency1,
bounded timeout để bắt regression; cả3 modes/correction vẫn pass. Toàn bộ23
ingest tests và strict Pyright/format/lint pass. Deployed IO worker được cập
nhật, workflow tiếp tục từ parsed artifacts cũ và native paid requests trả200;
full ready/search/output acceptance tiếp tục trong5 golden journeys.

## Compact synthetic golden-journey follow-up: Python dispatch

Live Python calculations exposed two integration mistakes: passing Python source
as a shell line (the `runtime` argument selects an interpreter binding, not the
shell language), and mounting agent home as WRITE although Mirage requires an
EXEC mount even for inline Python. `exec_python` now uses native `python -c`
with standard shell quoting; only agent home becomes EXEC. External mounts keep
their existing read/write permissions; the only Python runtime remains Monty.
No host runtime, network callback, custom interpreter or execution layer added.

The existing native ToolNode test now executes a Python calculation containing
an apostrophe and checks its result. The filesystem test checks the home mount
while retaining its external read-to-write permission coverage. Four targeted
tests, strict Pyright, Ruff lint and formatting pass. Live journey verification
continues with the deployed worker; fixtures and runners stay under `/tmp`.
