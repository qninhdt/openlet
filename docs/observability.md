# Observability

Openlet uses Grafana Cloud Metrics, Tempo and Loki, plus Langfuse Cloud for AI
observations and managed prompts. The only local collector is Alloy. Evaluation
is deferred. The [approved design](../plans/261113-1335-system-observability/plan.md)
records feature scope and hosting decisions; deployment checks are recorded in
[execution](../plans/261111-2010-leta-rewrite/execution.md).

## Configure

Fill the `observability` and `langfuse` sections of the
[configuration example](../infra/config/openlet.example.yaml). Use the regional
endpoints and instance IDs from each Cloud connection page. Grafana traces use
an OTLP HTTP base endpoint, metrics use the Prometheus remote-write endpoint,
and logs use the Loki push endpoint. Langfuse `base_url` is its regional project
host, without `/api/public/otel`.

Keep keys in private environment references. The Grafana token needs metrics,
traces and logs write scopes. `OBSERVABILITY_DB_PASSWORD` belongs to the dedicated
`pg_monitor` login created by bootstrap; Alloy does not receive application DB
passwords. The collector uses the Docker socket and read-only host mounts for
native Docker logs, Unix and cAdvisor exporters. Keep its control/OTLP ports
private.

```sh
export COMPOSE_PROFILES=leta,observability
make up OPENLET_CONFIG="$PWD/.local/openlet.yaml" ENV_FILE="$PWD/.env"
```

Render/deploy with the same profiles. `observability` also works without Leta;
Redis panels are relevant only when the Leta profile is enabled. Existing
`telemetry.otlp_endpoint` must address Alloy (`http://alloy:4317`). With no
collector, set it to `null`; normal business effects do not depend on uploads.
A cold managed-prompt fetch still requires Langfuse.

## Trace routing

Every process initializes one native OTel provider. Core OTLP exports go to
[Alloy](../infra/config/observability/alloy.alloy), which removes AI content on
the Tempo branch. Timing, status, model/usage metadata and RPC correlation stay.
Python Langfuse shares the provider and adds its own processor/exporter directly
to Cloud. Its native AI filter additionally keeps the SemanticSearch client
span. Alloy forwards only Go LetFS retrieval/query embedding/rerank observations
to Langfuse; it does not forward Python observations a second time.

An agent invocation gets a fresh AI trace and uses the agent ID as session ID.
Model/tool observations use the native LangChain callback; no observation is
created per streamed token. Ingest uses native LiteLLM and Instructor; each paid completion and embedding batch has one Langfuse observation.
File parsing/publication, queue capacity and storage health belong in Grafana;
model inputs/outputs, prompt versions, token/cost and RAG results belong in
Langfuse. Query embedding exports dimensions/counts, never vectors. Retrieval
captures only the final authorized hits returned to the caller.

JSON stdout logs retain trace/span IDs as fields. Loki labels are service,
environment and level, not workspace/agent/file/trace IDs. In Grafana Explore,
search the JSON `trace_id` and open that ID in Tempo. Use the same ID to correlate
an AI trace when both branches contain it.

## Prompts

Create text prompts `leta/common`, `leta/root`, `leta/leti`, `leta/compaction` and
`letfs/enrichment`. The Leta product instructions are maintained in the approved plan; publication versions and acceptance evidence are recorded in the inference execution report. Role prompts use Langfuse native composition with a
pinned numeric common version; runtime fetches the role once and does not append
common again. User/agent assignments remain in SQL; tools remain in code.

Apply the configured label (default `production`) to an approved version. Native
SDK caching uses its 60-second default. Each invocation retains the resolved
PromptClient and generations link to that version; compaction/enrichment use
their own prompt. To roll back, move the label to a previous version. New
invocations receive it after cache refresh; no checkpoint reset is required.
Warm stale cache can cover temporary prompt API failure. A cold miss has no
local prompt fallback in this demo design.

## Dashboards and alerts

Import the four native Grafana dashboard JSON files in
[observability assets](../infra/config/observability/) using Dashboards → Import:
`services.json`, `infrastructure.json`, `workers.json`, `leta.json`. Choose the
Grafana Cloud Prometheus data source. Panels use the pinned integrations' metric
names; confirm the first deployment's emitted names and adjust queries if an
upstream integration changes its convention. Empty idle histograms are normal.

`alert-rules.json` contains Grafana Alerting provisioning API request bodies.
Replace `PROMETHEUS_UID` and `OPENLET_FOLDER_UID` with the deployment's data-source
and folder UIDs, then POST each rule to `/api/v1/provisioning/alert-rules` using a
Grafana service-account token. Rule UIDs are stable; use PUT on the same UID to
update existing rules. This is an explicit operator action, not application
startup. Configure notification policies/contact points in Cloud before enabling
notifications. Initial defaults cover failed scrapes, disk pressure, exporter
failures and Temporal scheduling delay; tune with observed workload.

All metrics pass through the native `prometheus.relabel.essential` allowlist in
Alloy before remote write. It keeps the dashboard/alert families, Openlet runtime
and processing metrics, service request/error/latency, process/host/container
resources and dependency health. Full Temporal server polling/persistence/shard
histograms and unused dependency internals are excluded: they exceeded Cloud's
active-series limit even while idle. The filter does not change traces, logs,
Langfuse observations or sampling. Add a metric family when a dashboard or a real
investigation needs it, rather than enabling every dependency metric.

After changing the filter, distinguish newly forwarded series from Cloud's active
series: old series remain active until the Cloud window expires. Inspect
`grafanacloud_instance_active_series` using the **Grafana Cloud Usage** data source,
not the application Prometheus data source. Check Alloy remote-write 429s too;
a successful scrape alone does not prove Cloud ingestion.

Also inspect `grafanacloud_instance_memory_series` against
`grafanacloud_instance_metrics_limits{limit_name="max_global_series_per_user"}`
and `grafanacloud_instance_samples_discarded{reason="per_user_series_limit"}`.
Old inactive series can still occupy ingester memory after the active count
falls. Until head compaction frees them, new series can be discarded even when
remote write succeeds. This can take hours; do not interpret a reduced active
count as proof of complete ingestion or create a new account to work around it.

Use native Langfuse trace/session views, Agent Graphs, prompt metrics,
model latency/token/cache/cost and Usage dashboards. Start demo sampling at 1.0.
Do not reduce the shared OTel provider ratio to reduce only Tempo volume: that
also drops observations before Langfuse can export them. No separate sampler or
quota controller is installed. Track actual Cloud usage for the free tiers.

## Verify and recover

Validate the pinned collector before starting it:

```sh
docker compose run --rm --no-deps alloy validate /etc/alloy/alloy.alloy
```

After deployment, run a message/tool and semantic-search journey. Verify one
model observation per provider call, usage when returned, prompt/version links,
new invocation trace in the same agent session, and a connected RAG tree. Search
for a known test-content marker in Langfuse and ensure it is absent from Tempo.
Verify logs, scrapes and remote-write freshness in Cloud. Stop telemetry uploads
and confirm business effects still succeed; test cold prompt availability
separately. Cloud authentication, actual quotas/cost and dashboard rendering
require the real deployment and are not proven by local tests.

Alloy has a bounded container/memory-limiter budget, batching, and a volume for
remote-write WAL/log positions. Docker logs rotate locally. SDK/export queues
are bounded and may drop during outages. PostgreSQL backup includes Leta domain
and native checkpoint tables; Redis contains disposable events/cache. Follow
[backup/restore](operations.md), keeping matching Temporal and SpiceDB state.

LiteLLM exposes native Prometheus metrics to the authenticated Alloy scrape.
The gateway computes request costs, including streaming usage. Applications attach
those native totals to existing Langfuse observations; they do not maintain a price
catalog. Unknown cost is omitted, and zero is kept. Configure verified supplier
rates in LiteLLM: registry manufacturer estimates do not establish Vilao billing.
Cached and reasoning token detail counts are subsets, represented as disjoint
Langfuse usage categories to avoid adding them twice.

For agent semantic searches, native Langfuse baggage carries the session and
workspace/agent/root/box/run IDs on the existing internal RPC. LetFS attaches
only these UUID attribution labels to its retriever/embedding/rerank spans.
This adds no RPC or lookup; permission checks continue to use the actor.
Baggage is scoped to SemanticSearch and is not forwarded to model providers.
