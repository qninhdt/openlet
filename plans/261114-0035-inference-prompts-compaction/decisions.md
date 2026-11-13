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
| Structured extraction | Instructor JSON_SCHEMA → TOOLS → MD_JSON theo deployed facts                    | Manual per-task mode catalog; JSON fixer/validation loop tự chế                |
| Dependencies          | Instructor official Git exact commit `aeb7e2558166caeec497e541bcfc6b4eaa2cf53b` | Downgrade OpenAI3.3; forced resolver override; moving main                     |
| Retry                 | Proxy transport; Instructor bounded correction; Temporal durable recovery       | SDK+app transport loops, local Router cạnh Proxy                               |
| Embedding             | Native SDKs, float encoding/dimensions; index/query cùng embedding space        | Đổi model vô tư vì dimensions giống; chat fallback cho embedding               |
| Rerank                | Optional; absent/null là off; off giữ hybrid retrieval/filter/top-k             | Required Vilao rerank; enabled+model redundant settings                        |
| Cost                  | LiteLLM tính từng deployment; LF nhận explicit request cost/aggregate           | Backend arithmetic/OpenRouter price fetch/LF pricing sync/financial ledger     |
| Compaction            | Same executing model/effort/system/tools/prefix, append instruction             | Separate compaction model, replaced system, XML flattening                     |
| Prompt release        | Native versions/production label/cache, thử qua Openlet, rollback label         | Playground setup lúc này; release service/snapshots/CI eval gate               |
| Observability         | Existing OTel/Alloy → Grafana Cloud + native LF Cloud, sample1.0 demo           | Self-host monitoring/LF; custom immortal-agent telemetry/sampling architecture |
| Demo                  | Máy hiện tại, Cloud Free, 1–10 testers                                          | Đòi VPS/domain/DB provisioning riêng bằng tay                                  |

Không còn yêu cầu model name phải có effort suffix. Ngược lại, vẫn còn yêu cầu
khi chọn model phải chọn được effort; API biểu diễn được ghi là proposal riêng,
không suy từ quyết định naming bị bỏ.

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

## 6. Ba khoảng trống không được biến thành quyết định ngầm

1. [Report2345](../reports/research-261113-2345-inference-configuration-ownership.md)
   để effort API sau bỏ suffix là open. Code còn separate fields; giữ chúng là
   recommendation tối thiểu, cần người dùng chốt tại boundary này.
2. Capability/routing compatibility là approved requirement; cụ thể group
   intersection/native routing và supplier preference chưa được chọn. Không
   lấy official capability làm group fact cho deployment Vilao không hỗ trợ.
3. Code hiện chỉ propagate TraceContext ở Go/Python; cần kiểm native LF trace/
   session association có đủ cho aggregation không trước thêm propagation.
   Owning LF design hiện không thêm baggage; narrow baggage từng được đề xuất
   nhưng chưa accepted/proven. Không tuyên bố session cost đủ cả Go RAG khi
   chưa kiểm ingestion/aggregation, cũng không mặc định thêm baggage để sửa.

Supplier prices, verified limits và Cloud inputs còn thiếu là dữ liệu vận hành,
không phải lý do tạo framework mới. Không bịa values hoặc chạy paid load test
không cần thiết để lấp các ô này.
