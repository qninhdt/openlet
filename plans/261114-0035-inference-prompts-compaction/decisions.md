# Đối chiếu quyết định kể từ application implementation cuối

## 1. Mốc và cách đọc

Baseline `d69be44` (`refactor(leta): remove unused cancellation marker`), HEAD
`026c044`, branch `dev`. Khoảng `d69be44..026c044` có **17 commits**, 23 files
thay đổi, chủ yếu docs/research. `a6bb313` là thay đổi build/env template thật;
không gọi cả khoảng này là docs-only. Không có LiteLLM application migration
trong khoảng này.

Quyết định của người dùng sau cùng thắng proposal trước đó. Research report
committed không tự thành architecture authority. Chỉ các probe có mô tả setup/
results mới là evidence; không suy isolated proof thành full-stack acceptance.

## 2. Từng commit theo thời gian

| Commit    | Nội dung / quyết định có ích cho lượt tới                                  | Cách sử dụng                                                                              |
| --------- | -------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `c4f7371` | HTTP/SSE contracts, deployment/ops docs sau rewrite                        | Baseline; không thiết kế lại transport/domain                                             |
| `629885b` | Shared integration, crash/checkpoint/telemetry acceptance record           | Baseline có local proof; Cloud và prompt publication chưa xong                            |
| `cd6df6a` | CLI inventory, local demo prerequisites                                    | Chạy demo máy hiện tại; không đòi VPS/domain                                              |
| `a6bb313` | Một root `.env` private và tracked `.env.example`                          | Giữ convention env secrets/YAML settings; không commit credentials                        |
| `0c075d9` | Cloud login, R2 credential blocker tại thời điểm đó                        | Lịch sử; kết luận phải thao tác dashboard đã bị thay thế                                  |
| `6d729e0` | CLI tạo R2 scoped S3 credential thành công, signed list200                 | Không đòi tạo bucket/token lại; browser/upload proof còn thiếu                            |
| `4d4e726` | Grafana CLI OAuth khác runtime ingestion token                             | Phân biệt read/login và Alloy write credentials                                           |
| `7d84c48` | Vilao API/chat/tools/stream/usage compatibility                            | Native OpenAI-compatible adapter, không SDK fork; giới hạn ban đầu không còn toàn bộ đúng |
| `fdd1041` | Embedding follow-up; Grafana ingestion fixed; model/cost proposal đầu      | Giữ probes; local catalog/pricing source/retry proposals đã thay                          |
| `d3f3ac0` | Central catalog revision, Instructor pin, cache-friendly compaction        | Compaction evidence/pin giữ; local provider catalog và effort suffix bỏ                   |
| `d947b2f` | Grafana regional OTLP endpoint/user và successful ingestion statuses       | Không dùng direct Tempo paths đã404; chưa actual app Cloud proof                          |
| `c179197` | Provider-owned catalogs/unified references trong owning docs               | Là mốc lịch sử bị LiteLLM supersede; không implement parser/catalog này                   |
| `80363df` | Compaction cùng executing model/native prefix, không summary model riêng   | Giữ; code hiện tại vẫn chưa đạt                                                           |
| `1b4165d` | Stable Python LiteLLM/no-DB assessment; routing/retry/cost probes          | Dùng native Proxy, không tự viết gateway                                                  |
| `b799e86` | ChatLiteLLM/Instructor/embedding SDKs; metadata; callback/cost caveats     | Dùng client boundary đã chọn và per-attempt accounting proof                              |
| `6a3db1e` | Langfuse task config vs LiteLLM operations ownership                       | Prompt/config version cùng nhau; native cache; không default mechanism thứ hai            |
| `026c044` | Approved public groups qua Vilao/official/OpenRouter, per-deployment costs | Latest inference authority; migration vẫn pending                                         |

## 3. Quyết định cuối còn hiệu lực

| Chủ đề                | Chốt cuối                                                                       | Proposal không còn dùng                                                        |
| --------------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Gateway               | Một stable Python LiteLLM Proxy, native adapters, Compose, một worker           | Rust RC; custom SDK/provider/router                                            |
| Model identity        | Public logical group như `openai/gpt-6.1-sol`; supplier là deployment           | Public provider-prefixed choice bắt buộc; suffix `:effort` parser              |
| Catalog               | LiteLLM `model_list`/metadata, access group `leta`                              | Root catalog, `providers.*.models.*` trong Openlet                             |
| Task defaults         | Langfuse Prompt Config                                                          | `models.leta.default`, enrichment model YAML, `default_for` custom metadata    |
| Parameters            | Native effort/temperature/top_p/top_k/output khi cần và support                 | Null-filled universal options; backend provider-specific reasoning mapping     |
| Leta choices          | Supported subset từ gateway, explicit user selection/inheritance ở product      | Hardcoded list; mất model/effort selection chỉ vì đổi gateway                  |
| Structured extraction | YAML output_mode: `tools`, `json_schema`, `text`; Vilao dùng Instructor TOOLS   | Automatic capability discovery/downgrade; JSON fixer/validator thứ hai         |
| Dependencies          | Instructor official Git exact commit `aeb7e2558166caeec497e541bcfc6b4eaa2cf53b` | Downgrade OpenAI3.3; forced resolver override; moving main                     |
| Retry                 | Proxy transport; Instructor bounded correction; Temporal durable recovery       | SDK+app transport loops, local Router cạnh Proxy                               |
| Embedding             | Native SDKs, float encoding/dimensions; index/query cùng embedding space        | Đổi model vô tư vì dimensions giống; chat fallback cho embedding               |
| Rerank                | Optional; absent/null là off; off giữ hybrid retrieval/filter/top-k             | Required Vilao rerank; enabled+model redundant settings                        |
| Cost                  | LiteLLM tính từng deployment; LF nhận explicit request cost/aggregate           | Backend arithmetic/OpenRouter price fetch/LF pricing sync/financial ledger     |
| Compaction            | Same executing model/effort/system/tools/prefix, append instruction             | Separate compaction model, replaced system, XML flattening                     |
| Prompt release        | Native versions/production label/cache, thử qua Openlet, rollback label         | Playground setup lúc này; release service/snapshots/CI eval gate               |
| Observability         | Existing OTel/Alloy → Grafana Cloud + native LF Cloud, sample1.0 demo           | Self-host monitoring/LF; custom immortal-agent telemetry/sampling architecture |
| Demo                  | Máy hiện tại, Cloud Free, 1–10 testers                                          | Đòi VPS/domain/DB provisioning riêng bằng tay                                  |

Người dùng đã chốt giữ hai field `model_id` và `reasoning_effort` hiện có.
Không suffix parser. Config Langfuse phẳng là default; effective DB selection
ghi đè model/effort, Leti giữ root inheritance. Không `default` wrapper.

## 4. Prompt management vừa chốt, bổ sung ở lượt này

- Năm text prompts: `leta/common`, `leta/root`, `leta/leti`, `leta/compaction`,
  `letfs/enrichment`; không prompt riêng mỗi agent/workspace.
- Root/Leti native references pin **numeric common version**. Runtime lấy outer
  prompt một lần, không tự fetch/concat common lần hai hoặc inherit config từ common.
- Task default model/parameters version cùng prompt; compaction không có default
  model riêng. Agent mission SQL, tool/output schemas ở owning code.
- Pin PromptClient/config mỗi invocation; SDK RAM cache60s, stale-while-revalidate;
  exact prompt links, scoped compaction override.
- Thử qua Openlet → move `production` label → quan sát → rollback label nếu cần.
  `latest` cho development; staging khi thực sự có staging deployment.
- **Playground hoãn**. Không cần expose local gateway thành public endpoint hoặc
  tạo Langfuse LLM connection chỉ để prompt management hoạt động.
- A/B, evaluation, GitHub sync, webhooks/Slack và n8n hoãn/không áp dụng.
  Agentic CLI/API cho authorized operator, không cho agent tự sửa system prompts.
- Cold cache khi LF prompt API down có thể fail invocation; demo chấp nhận,
  không fallback copies/release artifact framework.
- System prompt wording còn draft; chốt integration không phải chốt publish
  nguyên văn mọi draft đã viết.

## 5. Bằng chứng hiện có và điều chưa chứng minh

### Application baseline

[Execution record](../261111-2010-leta-rewrite/execution.md) ghi strict type/
format/generation checks, 26 Python tests, Go tests, shared API E2E5/5, native
checkpoint/Temporal/crash/Mirage proofs. Đây là results của implementation cũ
trước gateway migration; phải chạy checks liên quan sau thay đổi.

### Provider và SDK

[Vilao](../reports/research-261113-2054-vilao-provider.md) và
[catalog follow-up](../reports/design-261113-2119-model-configuration-costs.md)
đã thử chat/tools/stream, single/batch/dimensions embeddings và Go SDK embedding.
Không native response schema ở các model đã thử; tools/text extraction dùng
Instructor khả thi; rerank endpoint404. Không suy mọi model Vilao đều cùng facts.

[Gateway](../reports/research-261113-2251-litellm-gateway.md),
[SDK](../reports/research-261113-2324-litellm-sdk-capabilities.md) và
[ownership probes](../reports/research-261113-2345-inference-configuration-ownership.md)
chứng minh no-DB config, aliases/groups/shared credentials, metadata overrides,
stream cost/nonstream headers, native retry và per-attempt Instructor caveat.
Local SDK capability helpers cho arbitrary proxy aliases không đáng tin như
gateway deployment facts. Không dùng gateway native LF callback đã thấy sai
Instructor accumulated usage hoặc embedding observation type.

Chưa có authenticated same-group calls cả Vilao/OpenAI/OpenRouter; chưa có
heterogeneous native routing proof, full application cost/Cloud migration hoặc
real cache-hit proof cho implementation compaction sắp viết.

### Cloud/infra

[Readiness record](../reports/infra-261113-2008-cloud-cli-readiness.md) có nhiều
follow-ups; đọc kết luận mới nhất, không lấy blockers cũ làm trạng thái hiện tại.

- R2 bucket `openlet-dev` đã có, scoped credential tạo bằng CLI, signed list200.
  Presigned/browser writes và CORS theo browser origin thực vẫn cần kiểm.
- Grafana CLI login hoạt động; runtime write token khác OAuth login. Metrics200,
  Loki204, OTLP200 sau fix. Base traces regional OTLP gateway, Basic user là
  stackID; không phải direct Tempo endpoint/tenant đã thử thất bại.
- Các successful Grafana requests là auth/route probes, chưa actual service
  metrics/traces/logs/dashboard/alert acceptance.
- Langfuse project URL/keys còn thiếu tại **lần ghi readiness gần nhất**. Chưa
  đọc lại secrets trong lượt lập plan này; implementation kiểm presence privately
  trước khi hỏi, không khẳng định chúng vẫn trống hôm nay.
- Secret nằm private root `.env`, không trong report/config committed. Existing
  dirty `.env.example` không bị sửa/stage bởi lượt lập plan.

## 6. Quyết định thay thế các proposal trong plan ban đầu

- Giữ separate model/effort fields đã được duyệt, không còn effort API gate từ
  [report2345](../reports/research-261113-2345-inference-configuration-ownership.md).
- Backend không biết deployment được gateway chọn trước request; `/model/info`
  không giải quyết được mode của mixed-provider group. Người dùng đã chấp nhận
  một YAML output mode cho enrichment: `tools`, `json_schema`, `text`, tương ứng
  Instructor `TOOLS`, `JSON_SCHEMA`, `MD_JSON`. Vilao dùng `tools`; không tự thử
  lần lượt ba modes, không filter model/tool capability hoặc dựng intersection.
- Instructor trả object đã validate hoặc báo lỗi sau bounded correction. Không
  duplicate Pydantic validation/JSON fixing trong ứng dụng. Ordinary agent tools
  tiếp tục native LangChain/LangGraph, không đi qua Instructor.
- Cost scope bao gồm **LLM, embedding và reranker**: file processing gồm enrichment
  và batch embeddings; semantic search gồm query embedding và rerank khi bật.
  LiteLLM tính cost; LF nhận/aggregate; không backend price calculator.
- Code hiện chỉ propagate TraceContext ở Go/Python; cần kiểm native LF trace/
  session association có đủ cho aggregation không trước thêm propagation.
  Owning LF design hiện không thêm baggage; narrow baggage từng được đề xuất
  nhưng chưa accepted/proven. Không tuyên bố session cost đủ cả Go RAG khi
  chưa kiểm ingestion/aggregation, cũng không mặc định thêm baggage để sửa.

Supplier prices, verified limits và Cloud inputs còn thiếu là dữ liệu vận hành,
không phải lý do tạo framework mới. Không bịa values hoặc chạy paid load test
không cần thiết để lấp các ô này.

## 7. Runtime/prompt review đã chốt ngày 2026-11-14

- Native `create_agent` có history repair cho identifiable `invalid_tool_calls`
  trước model request tiếp theo, nhưng không tự loop-back khi chỉ có invalid calls.
  Đối chứng trên LangChain1.5.0/LangGraph1.2.21 xác nhận cả vanilla và middleware
  graph đều kết thúc sớm; native `after_model` jump có thể dùng history repair.
- Người dùng **chọn defer workaround**: chỉ TODO ngắn/link
  [issue33504](https://github.com/langchain-ai/langchain/issues/33504) tại graph
  construction. Không suy tần suất thực tế từ synthetic probes; chấp nhận giới
  hạn có thể kết thúc lượt sớm, không thêm parser/retry middleware ở lượt tới.
- Review chứng minh thêm `after_model` hook đổi pending node thành hook node;
  runtime hiện chỉ mở Mirage khi `tools` trong `state.next` nên file tool gặp
  AssertionError. Optimization phải bỏ phụ thuộc tên node, dù workaround hoãn.
- Graph/middleware một lần mỗi activity; client reuse, control/config refresh
  bằng native hooks; giảm repeated SQL và batch history transaction mỗi boundary.
  Giữ sync checkpoint → projection → keep_latest và cooperative cancellation.
- Benchmark trước/sau trong implementation; scripts/results thô ở thư mục tạm,
  không thêm benchmark source/CI. Không gọi fixture overhead reduction là tốc độ
  LLM thực hoặc suy performance từ LoC.
- Box `description` đã có trong DTO/SQL; không thêm field/migration. Leti nhận
  box name/purpose, own name, teammate descriptions/representative và routable
  recipient IDs; không teammate prompts/full edge matrix hoặc time context.
- Heading `Your instructions`, placeholder `agent_instructions`; Leti thêm
  `box_context`. Common composition bằng native numeric references. Không concat
  prompt instructions trong runtime hoặc thêm prompt riêng mỗi box/agent.
- Implementation bao gồm cập nhật versions/config thật trên LF Cloud, kiểm
  resolved references/variables, thử qua Openlet và production label/rollback.
  Actual prompt wording còn cần hoàn thiện/review; local fixtures không thay
  Cloud publication. Config vẫn phẳng sau khi người dùng rút `default` wrapper.

Các runtime probes/5 focused tests pass là bằng chứng review baseline, chưa phải
acceptance cho optimization/gateway migration chưa triển khai. Không sửa app code
hoặc publish Cloud trong lượt cập nhật plan này.

## 8. Chốt whole-Leta review và phạm vi trước implementation

- F01–F19 được chấp nhận trong owning paths, không rewrite domain lần nữa.
- F04: activity result trả durable inbox_cursor; workflow so admitted seq với
  cursor để bỏ empty inbox wake, gồm late/out-of-order admission completions.
  Control/cancel semantics giữ riêng; không DB cursor hoặc activity mới.
- F07: LetFS search hits trả relative paths; proto/Go/generated SDK cùng đổi,
  bỏ adapter parent-walk/tree prefetch. Không path cache trong Leta.
- F18: bounded native stream capture cho output trả agent, giữ full file
  redirection và command drain/settlement; không custom runner framework.
- PATCH giữ model_id/reasoning_effort: đổi model không gửi effort thì clear
  effort cũ; effort-only chỉ hợp lệ khi có explicit model. Đây là intentional
  correction so với current API, không claim giữ nguyên mọi PATCH behavior.
- Không còn known architecture/product decision cản bắt đầu implementation.
  Native SDK/Cloud proofs, workflow history cutover và prompt wording review là
  verification/content work. Nếu proof buộc vượt scope thì trình đúng khác biệt;
  không tự thêm compatibility, recovery service, propagation hoặc data reset.
