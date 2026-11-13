# Thực hiện, kiểm chứng và cutover

Đây là execution detail cho [plan](plan.md), chưa phải execution log đã pass.
Reuse contracts/runtime đang có, không mở một rewrite domain thứ hai.

## 1. File map và phạm vi ảnh hưởng

| Boundary               | Files/modules phải chạm                                                                                                    | Kết quả                                                                          |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Python dependencies    | Root `pyproject.toml`, `uv.lock`; Leta/ingest/SDK pyprojects                                                               | ChatLiteLLM/LiteLLM/Instructor pin tương thích Python3.14 và strict types        |
| Proxy/infra            | New `infra/config/litellm.yaml`, `infra/compose.yaml`, `infra/compose.test.yaml`                                           | Một stable Python service/config, native health, private auth, test gateway      |
| Shared config          | `packages/sdk-python/src/openlet_sdk/config.py`, Go config consumers                                                       | Xóa local catalog/default types, giữ typed gateway/index/resource settings       |
| Config generation      | `scripts/configure.py`, `scripts/bootstrap.py`, `infra/config/openlet.example.yaml`                                        | Least-needed secrets per role, generated env/Compose, index dimensions guard     |
| Leta admission/listing | `apps/leta/src/leta/config.py`, `api.py`, `agents.py`                                                                      | Gateway metadata cache/projection/selection; no local catalog resolver           |
| Leta execution         | `apps/leta/src/leta/runtime/agent.py`, owning filesystem/tools/history functions                                           | Reused graph/client, box context, native templates, cost callback, compaction    |
| Managed prompts        | Existing prompting draft, LF Cloud prompt versions/config/labels                                                           | Common references/variables, actual publication và runtime version proof         |
| Ingest                 | `apps/letfs-ingest/src/letfs_ingest/providers.py`, IO worker config consumers                                              | Instructor + async embedding, per-attempt observations, no direct OpenAI parse   |
| Go RAG                 | `apps/letfs/cmd/letfs/main.go`, `internal/storage/server.go`, `search.go`                                                  | Gateway SDK client, explicit float encoding, optional rerank, native cost header |
| Telemetry              | Existing Python SDK telemetry and Go/Alloy owning paths                                                                    | Preserve provider/processors/filter; minimal cost/approved attribution           |
| E2E                    | `e2e/openlet.test.yaml`, `fixtures/wiremock/*.json`, `fixtures/setup.ts`, `tests/api/*.spec.ts`                            | Existing shared suite through real Proxy, no separate Leta suite                 |
| Operations             | `docs/setup.md`, `architecture.md`, `observability.md`, `operations.md`, `api-contracts.md`, `testing.md` khi contract đổi | Current implemented setup/contracts, không target giả đã chạy                    |

Chỉ tạo module mới nếu metadata snapshot hoặc cost callback có trách nhiệm rõ,
không tạo providers/router/repository/service abstractions một caller. Phân
loại unknown JSON tại HTTP/SDK boundary, internal code dùng typed values.
Không blanket `Any`, `cast(Any,...)`, disabling strict, custom SDK fork hoặc
dummy fixtures để tránh runtime behavior.

Go storage integration tests hiện ở `storage_integration_test.go`, query/text/
request checks có owning tests riêng. Python tests có `test_runtime.py`,
ingest `test_providers.py`/`test_telemetry.py`/index/enrich tests, SDK telemetry
tests. Reuse narrow targets; không tạo test mỗi prompt sentence/LF feature.

## 2. Phase 1 — dependencies và native gateway

Suggested commit: `build(inference): add LiteLLM gateway`.

1. Inspect pinned SDK signatures + uv workspace resolution. Thêm
   `langchain-litellm`, LiteLLM cho Python callers và exact Instructor Git commit
   `aeb7e2558166caeec497e541bcfc6b4eaa2cf53b`. Proxy image/SDK versions pin theo
   compatible release verified; không downgrade OpenAI để né jiter conflict.
2. Add native Proxy config/one-worker Compose service, read-only mount, shared
   credential Vilao, server API key. Chỉ các upstream có credentials mới bật.
3. Route native SDK calls tới Proxy; giữ health/dependency behavior proportional.
   CPU parsing/Platform/database migrations không đòi provider key mới.
4. Update generated role-specific env: app roles nhận gateway key, gateway nhận
   upstream keys; API listing cần metadata access nhưng không upstream secrets.
   Không đưa master/admin key ra browser hoặc full config vào error responses.
5. Update env example khi implementation thực sự cần variables mới; reconcile
   existing dirty change trước edit, không stage secrets/user edits vô tình.
6. Thêm shared typed `services.leta.compaction.trigger_fraction` và
   `keep_fraction`, example defaults 0.8/0.3; validate một lần tại Leta startup.
   Không thêm threshold per-model/agent hoặc hardcode hai literals trong runtime.

Verification: uv lock/strict type compatibility, Compose config/native health,
unauthenticated route denied, native `/model/info`, one chat/tool stream và
embedding call qua Proxy. Existing research fixture upstreams đủ kiểm wiring;
live probe tối thiểu dùng Vilao, không paid benchmark.

Nếu dependency compatibility đòi đổi framework/public behavior ngoài plan,
dừng hỏi với exact conflict. Không force resolver hoặc thêm alternate runtime.

## 3. Phase 2 — metadata, supported models và selection

Suggested commit: `feat(leta): discover supported models from gateway`.

1. Parse metadata typed, một in-process snapshot TTL60s/refresh on demand.
2. Deduplicate native groups có access group `leta`. Model-list public projection
   tối thiểu; không leak credentials/prices/admin fields.
3. Giữ `model_id` và `reasoning_effort` hiện có, không suffix parser/dual form
   hoặc schema migration không cần thiết. LF config phẳng là default; DB selection
   ưu tiên, Leti inherit root khi chưa explicit selection.
4. Validate group/effort tại configuration boundary bằng gateway facts. Runtime
   lỗi persisted invalid selection đúng agent, không scan/rewrite mọi row.
5. Root default từ pinned LF config; Leti inheritance/explicit override giữ đúng
   agreed semantics. Đảm bảo model change không kéo effort cũ sang model khác.
6. Move route ordering/Envoy mapping nếu cần. Cập nhật API contract cùng commit,
   không tạo frontend selector mới khi scope chỉ backend.

Verification tối thiểu: multi-deployment group trả một item; group không có
access marker không xuất hiện; cache hit không HTTP request thêm; refresh nhận
config mới; selection/reset/inheritance và unsupported effort theo accepted API.
Không assert full external model registry hoặc snapshot metadata khổng lồ.

## 4. Phase 3 — Prompt Config và native inference callers

Suggested commits theo owner:

- `refactor(leta): use gateway models and managed inference settings`
- `refactor(ingest): use Instructor and gateway embeddings`
- `refactor(letfs): route search models through gateway`

1. Parse needed LF Prompt Config, pin mỗi invocation. Không task defaults cùng
   lúc trong gateway/Openlet YAML. Existing role prompt composition giữ native.
2. Replace ChatOpenAI bằng ChatLiteLLM qua native proxy provider path; tools vẫn
   inferred LangGraph. Request usage streaming/cost, app transport retries0.
3. Ingest thay `.parse` bằng Instructor; giữ Metadata model/evidence/image logic.
   Thêm YAML output_mode enum `tools | json_schema | text`, map native
   `TOOLS | JSON_SCHEMA | MD_JSON`; Vilao chọn `tools`. Instructor trả validated
   object hoặc lỗi; không validator/JSON repair thứ hai hoặc auto mode downgrade.
4. Group có thể chứa Vilao/official/OpenRouter; mode do config chọn trước call.
   Không capability intersection/filter, auto native-schema detection hoặc custom
   router. Verify native requests/required parameters và không silently drop.
5. Async embedding + Go OpenAI SDK: explicit encoding_float/dimensions,
   validate native count/index/dimension theo existing
   response boundary. Không thêm per-vector framework hoặc store embedding data
   vào Langfuse. Giữ exact index model/space, không reindex không được phép.
6. Make rerank nullable/absent; off trả hybrid filtered top-k, on dùng native
   endpoint sau filter. Giữ existing rerank output index validation.
7. Configure native Proxy bounded transport retry; zero SDK retry. Instructor
   correction chỉ một bounded chain. Verify no nested app transport retries,
   no partial stream concatenation, permanent config errors visible.

Verification: one tool round trip + stream finish; Instructor first-invalid/
corrected result có bounded call count; explicit unsupported mode behavior;
embedding single/batch/query cùng dimensions/space; RAG on/off giữ permission/
source/live filter và top-k ordering. Không live test tất cả model combinations.

## 5. Phase 4 — per-request costs và AI observations

Suggested commit: `feat(observability): capture gateway inference costs`.

1. Keep native LF callback + one inline cost callback tại completion boundary;
   verify callback order/current generation context bằng actual exporter output.
2. Ingest log raw paid attempt usage/cost trước Instructor mutation/aggregate;
   embedding đúng observation type. Không double native LF+LiteLLM callback export.
3. Go SDK nhận response headers, annotate existing provider spans. Unknown cost
   không zero; LF inferred manufacturer prices không report là actual supplier.
4. Confirm trace tree session/workspace/root/box/file/source-version attribution.
   Kiểm native trace/session aggregation trước; nếu đã đủ thì không thêm gì.
   Nếu chưa đủ, dừng tại gate trước thêm baggage vì owning design hiện không
   dùng nó; không claim full agent totals khi chưa aggregate đúng.
5. Gateway native operational metrics/logs/traces vào Alloy/Grafana; không
   request IDs làm Prometheus labels hoặc poll cost API every request.

Verification: stream/nonstream/embedding/rerank cost từ gateway tới LF
payload; two Instructor paid attempts đếm đúng từng attempt; cached/reasoning
subsets không inflate totals; no duplicate observations; unknown cost path.
File processing gồm LLM attempts và batch embeddings; SemanticSearch gồm query
embedding và optional rerank. Native rerank billed units/price model được giữ,
không coi missing units là free. Không dùng parent aggregates để count hai lần.
Check selected Go RAG export + Tempo content stripping vẫn đúng. Cloud verify
chỉ khi credentials sẵn, local exporter proof phải ghi rõ giới hạn.

## 6. Phase 5 — runtime, box context, compaction và prompt lifecycle

Focused commit boundaries: `refactor(leta): reuse agent execution resources`,
`refactor(leta): use managed instruction and box templates`,
`fix(leta): preserve request prefix during compaction`.

### Runtime optimization và benchmark

1. Capture baseline bằng script tạm trước edit; reuse deterministic fixtures và
   cùng history/tool/boundary workload. Không benchmark script trong source/CI.
2. Move graph/catalog/middleware construction khỏi per-step loop. Reuse model
   client, native request hooks cho config updates; outer loop chỉ điều phối
   control/resume/sync boundary. Không thay native agent routing.
   Đổi effective settings đồng bộ với system/input guard/summary budget. Khi
   model hoặc budget đổi, existing budget hook gọi native summarizer mới bằng
   public constructor; không mutate private normalized trigger hoặc compile
   graph lại. Static overhead chỉ tính lại khi inputs đổi, full request guard
   vẫn kiểm mỗi call. Reuse client không đồng nghĩa cache mọi model vô hạn.
3. Gộp current control/profile/root reads bằng runtime query, không đổi global
   get_agent cho các callers khác. Box facts đọc một lần/activity. Khi idle,
   dùng EXISTS thay pending full batch; Inbox vẫn nạp messages/cursor đúng một
   nơi. Native saver/thread/receipts/checkpoint là authority, không state mirror.
4. Chuẩn bị lazy filesystem trong file-tool execution path, độc lập node names;
   serialize initialization/refresh khi tool batch song song, giữ reuse/mount
   refresh/cleanup và retry pending tool mở lại resource ephemeral. File tools
   dùng owning Filesystem.session; bỏ Context.session và pending tool-name scan.
5. Batch history writes một transaction/boundary; giữ stable IDs/sequence,
   projection recovery trước prune và cancellation chờ durable boundary.
   Dùng một agent lock, batched existing-ID lookup/counter allocation/inserts;
   native saver vẫn độc lập, không giữ SQL transaction qua inference/tool calls.
   Align live text message IDs với persisted IDs hiện hữu, không identity table.
   Dedupe trong batch trước SQL, gồm preserved tail được emit lại khi compact;
   chỉ cấp seq cho IDs mới. Giữ Redis event/notification recovery contract khi
   entry đã tồn tại, không thêm outbox để bảo đảm notification exactly-once.
   Thay per-entry record writer bằng multi-row batch insert, cập nhật normal
   projection và startup recovery; không chỉ thêm outer transaction quanh
   record loop cũ. Sau commit, reuse events publisher để gửi ordered projection
   events bằng một Redis pipeline/boundary, XADD từng event và EXPIRE một lần.
   Giữ individual event schema/order/maxlen/TTL và best-effort behavior; không
   delay live token streaming hoặc thêm background batching mechanism.
6. Sửa ToolEffects outcome theo native ToolMessage.status. Chỉ thêm TODO/link
   issue33504 tại create_agent; không implement recovery/retry middleware.
   Outer LF scope giữ session/trace/metadata/tags; inner scope chỉ role prompt,
   compaction override đúng version. Không loại callback để giảm overhead giả.
7. Chạy cùng benchmark sau edit; report median/p95/setup, graph setup và DB
   request/transaction counts cùng Redis pipeline executions/commands. Không
   gọi fixture overhead gain là tốc độ LLM.
   Xóa process/tài nguyên benchmark khi xong; raw results giữ thư mục tạm.

### Box context và managed templates

1. Reuse existing box description, không migration. Render own name/box purpose,
   teammate names/descriptions/representative và allowed recipient IDs; root
   recipient chỉ với representative. Không full edge matrix/teammate prompts.
2. Native LF common numeric references; role template dùng `Your instructions`
   với `{{agent_instructions}}`, Leti thêm `{{box_context}}`. Runtime compile
   variables khi effective instruction inputs đổi, không instruction
   concatenation; bỏ clock/timezone hoàn toàn.
3. Pin LF PromptClient/config một lần/activity; DB model/effort override theo
   contract đã chốt, LF default config phẳng, không `default` wrapper.

### Cache-friendly compaction

1. Same executing client/settings, stable system + ordered tools + original
   native message prefix + appended compaction user instruction.
2. Remove XML flatten/get_buffer_string and replacement-system summarizer;
   không inject clock/timezone vào system hoặc user input thay thế.
3. Native middleware trigger/cutoff/keep; `trim_tokens_to_summarize=None`.
   Budget includes appended instruction + output reserve trước request.
   Resolve native token thresholds từ configurable 0.8/0.3 trên history budget H;
   test changed settings áp dụng đúng budget, không đổi đơn vị sang full window.
4. Keep native summary+tail/checkpoint/sync projection/prune under writer lock;
   no SQL summary table hoặc rerun effects từ public transcript.
5. Exact prompt link override cho compaction, restore role scope sau đó.
6. Hoàn thiện/review wording và **publish/update versions thật lên LF Cloud**:
   common trước, role references pin numeric version, compaction/enrichment và
   flat config tương ứng. Kiểm resolved text/variables qua native SDK; thử qua
   Openlet rồi production label/cache/rollback và observation prompt links.
   Không dừng ở Markdown/fixtures; Playground/evaluation vẫn hoãn, không prompt
   sync service hoặc release automation mới.

Verification: outgoing main/summary wire-prefix equality, budget and tool-pair
integrity, checkpoint close/reopen/keep_latest tiếp tục pending work. One real
provider request pair đọc actual cache usage khi endpoint hỗ trợ; absent usage
không được biến thành proof hit. Manual LF label rollback/cache version proof
đủ, không tạo prompt-release automation/evaluation suite. Chạy thêm focused
checks cho resource reuse, box context, parallel filesystem, configuration
override, history ordering/recovery, metric outcomes và cooperative cancellation.
Đếm graph/client construction với nhiều model/tool boundaries; đổi model/effort/
instructions ở safe boundary phải đổi đúng request và budget mà không dựng lại
graph. Parallel first-use file tools chỉ tạo một Workspace/Session, vẫn refresh
mount sau TTL/HITL invalidation. Idle EXISTS không thay đổi batch/cursor semantics.
History journey phải đọc được summary `kind=compaction`, paginate bằng `before`
về entries trước compact và vẫn đọc được sau restart/prune. MVP không auto-purge
public history; không thêm raw-provider archive hoặc frontend mới vào phase này.
Fault-injection tại checkpoint commit trước history commit phải recover missing
entries đúng thứ tự/identity trước resume/prune, kể cả khi vừa compact; không
repeat confirmed tool effects. Kiểm stream/canonical message IDs khớp nhau và
Redis notification chỉ phát sau history transaction commit.
Với ba tool results mới, verify một history transaction với batched statements
và một Redis pipeline chứa sáu ordered XADD + một EXPIRE. Replay batch không
tăng counter hoặc duplicate rows; Redis outage không rollback durable history.

### Các owning paths còn lại của Leta

Áp dụng [full review F01–F19](../reports/review-261114-leta-efficiency.md) vào
Phase5, không coi việc sửa riêng agent.py là hoàn tất optimization:

- F03: known domain rejections qua Temporal wrappers thành existing tool error
  feedback; infrastructure errors giữ retry semantics, issue33504 vẫn defer.
- F05: dsn/pool nhận startup Config đã có; setup CLI load một lần. Không thêm
  config cache hoặc cho saver tự reload sang DB khác process pool.
- F08–F12: bounded parallel read searches, root preview projection, scoped
  recipient/ownership lookups và native SpiceDB bulk permission checks. Giữ
  cursor/input schemas, admission gates/locks và current permission semantics.
- F13–F15: bỏ forecast RPC khỏi schedule PATCH/DELETE, RETURNING cho write
  readback, batch box members/edges, gộp worker/control/HITL reads đúng lock phase.
- F16–F17: skip archived recipients khi refresh, reuse loaded root/box facts,
  batch terminal events và bỏ redundant range read chỉ sau cursor-gap proof.
  Cleanup phase ordering giữ nguyên; không unbounded fanout.
- F18–F19: slice trước khi format cached file window; gom duplicate native
  workflow submission glue về existing owners, xóa confirmed unused callers/
  fields/dependencies và brittle count-only assertions. Không mở reader framework.

F04/F07/F18 đã được chốt, triển khai cùng owning contracts:

- F04: runtime result status + durable inbox_cursor; reconcile admitted seq với
  returned cursor trong workflow và late receive handlers, giữ control/cancel.
  Không thêm DB state/activity; kiểm existing workflow histories trước cutover.
- F07: relative path trong TextHit/SemanticHit, cập nhật Go owner, proto và SDK;
  bỏ parent Stat walk/ReadTree mapping trong Leta. Giữ search scope/permissions.
- F18: native stream capture giữ stdout/stderr hữu hạn cho agent, tiếp tục drain
  và settle command. Giữ nguyên full redirection vào file, không cap producer
  bằng @all hoặc tạo collector/runner framework. Nếu API không đáp ứng, trình
  exact limitation trước đổi behavior.

SQL indexes chỉ đổi khi có EXPLAIN evidence. Reuse existing focused tests:
permission filtering không grant nhầm, business rejection không retry vô ích,
schedule mutation không gọi forecast, box batch giữ constraints/atomicity và
stream gap detection vẫn đúng. Không một test/suite mới cho mỗi query.

## 7. Phase 6 — integration, deletion và local/Cloud acceptance

Suggested commits: owner-specific deadcode deletion nếu chưa xóa cùng migration;
`test(api): verify gateway inference integration`; docs theo implemented result.

1. Migrate shared WireMock fixtures cho real Proxy upstream, metadata/prompt
   config/stream usage/output modes. Giữ test suite trong `e2e/tests/api`.
2. Delete obsolete callers/types/config/docs/examples sau migration: catalog,
   provider-specific reasoning body, direct upstream setup, compaction XML,
   local pricing/retry experiments **nếu còn active**. Không xóa valid domain
   constraints, security filters hoặc tests có outcome còn đúng.
3. Focused Python/Go checks trước, sau đó `make check`, relevant tests,
   `make generate` drift, build và shared API E2E. Không broaden paid CI vô hạn.
4. Existing Cloud setup reuse: Grafana token/routes fixed, R2 bucket/scoped keys
   đã có. Check env presence privately trước hỏi credentials; không gửi secrets
   chat hoặc in nguyên config. Langfuse prompt publication cần approved wording.
5. Local demo journey: file upload/process/search → agent tool/stream/inbox →
   Leti delegation → compaction/restart → final response; inspect actual Cloud
   tree/cost/prompt links và Grafana service metrics/traces/logs.
6. Verify R2 presigned browser write/CORS theo actual origin, không tự sửa
   lifecycle policies. Export/inspect dashboard assets; alert receiver/contact
   chỉ cấu hình/gửi thử nếu scope/authorization có, không nhắn người khác tự ý.

## 8. Những thứ xóa, giữ và không thêm

**Xóa/thay:** `ModelEntry`/`LetaModels` local catalog, YAML default/catalog,
direct-provider Python wiring, provider-specific reasoning construction,
mandatory rerank requirement, XML summarizer, obsolete config fixtures/tests
chỉ bảo vệ cấu trúc bị bỏ; per-step graph/client construction, instruction
concatenation và time context. Xóa `langchain-openai` dependency nếu không còn caller;
không xóa `openai` transitive/native SDK need một cách máy móc.

**Giữ:** typed native tools, Pydantic output contract, durable receipts,
permissions/version checks trên mutations, SQL RAG validity filter, native
checkpoint/saver/projection, Temporal orchestration/heartbeats, Redis/Mirage
policy và SSE snapshot/replay. Không giải quyết gateway integration bằng rewrite
domain/storage security hoặc tước functionality đã chốt.

**Không thêm:** catalog/parser/price service, local Router, retry middleware,
JSON repair, spend ledger, summary table, release artifact worker, prompt cache
service, LiteLLM DB/Redis, fallback copies, perpetual polling, enterprise eval.

## 9. Cutover, rollback và acceptance evidence

- Trước đổi local runtime, xác định running processes/stack owner; reuse hoặc
  clean stop services đang dùng, không bật duplicate gateway/worker/ports.
- Backup config/DB/index theo existing procedures trước migrations cần thiết.
  Plan này không authorize destructive data reset/reindex hoặc recreate workspace.
- Runtime/config migration phải đi cùng caller changes, không hỗ trợ song song
  legacy catalog. Stop/restart affected roles tại deployment boundary hiện có.
- Rollback prompt: move LF label; invocation đang chạy giữ pinned version.
  Rollback gateway: previous pinned image/config. Rollback application: previous
  coherent commit+config snapshot, không shim. Không đổi embedding space nên
  thông thường không vector-data rollback; nếu phải đổi, chốt reindex riêng.
- Ghi execution record: exact commit/dependency versions, commands/results,
  real vs fixture provider, Cloud vs local export, prices supplied vs unknown,
  pending acceptance. Không ghi secrets hoặc claim cả ba suppliers nếu chỉ test
  alias cùng upstream fixture.

Chỉ mark complete khi agreed outcomes đạt và runtime evidence đủ. Chưa có
credentials/approved prompt wording thì đánh dấu chính xác Cloud/publication
acceptance pending, không che bằng mock hoặc tuyên bố implementation hoàn tất.
