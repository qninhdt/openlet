> Historical snapshot, superseded on 2026-10-30 by the user-approved [direct-child artifact plan](../261029-1624-artifact-file-processing/plan.md). Its schema, path, ownership and pending-review statements describe the previous draft; do not execute them. Use the current plan and [validation report](./validation-261030-0737-hybrid-artifact-plan.md). General runtime/source evidence remains useful where the current plan retains it.

# Processor Runtime Research

Research conducted 2026-10-29 (Asia/Ho_Chi_Minh). This report is intentionally implementation-oriented; it does not modify source, containers, databases, credentials, or dependencies.

## Recommendation

Implement one Rust `ProcessFile` Workflow that schedules exactly one Python Activity on a dedicated activity-only task queue. Place the Python worker under `services/letfs/processor/`; its async Activity supervisor should launch one bounded child process for CPU-bound Docling conversion and terminate that child on cancellation/timeout. This is one Temporal Activity, not a ProcessPool framework. The Activity should:

1. call a letfs prepare API with `(operation_id, source_node_id)`; letfs reads the captured content identity from the durable operation;
2. download one immutable source snapshot through a short-lived letfs-issued presigned `GET`, or receive inline bytes for an inline source;
3. convert only `.pdf`, `.docx`, `.xlsx`, and `.pptx` with Docling v2;
4. write outputs to a bounded per-attempt temporary directory;
5. upload large/binary output to unique letfs staging keys using short-lived presigned `PUT` URLs, and send small UTF-8 Markdown through an authenticated inline API;
6. call one letfs complete API that revalidates source liveness, content identity, and operation state, validates every output, performs quota admission, server-side copies staging objects to immutable final keys, creates the detached artifact root, and publishes all nodes atomically while setting the source-owned `artifact_dir_id`.

Do not expose final object keys to the Python worker or publish directly to a mutable final key. A presigned URL is a bearer capability and can be replayed until expiry; a unique staging key plus server-owned finalization is the smallest design that remains safe after response loss and late `PUT`s.

## Local Evidence

- `services/letfs/Cargo.toml` pins `temporalio-{client,common,macros,sdk,workflow}=1.1.0`, `object_store=0.14.2`, Rust 1.96, and the current Compose server is Temporal `1.32.1`.
- `services/letfs/src/storage/mod.rs` stores `Arc<dyn object_store::ObjectStore>` and currently supports authenticated server-side I/O only; it has no URL-generation route.
- `services/letfs/src/fs/uploads.rs` already has useful safety patterns: random candidate keys, a 120-second transfer deadline, max file size, bounded multipart buffering, quota admission, inline text classification, and durable object-deletion records for ambiguous writes.
- `services/letfs/src/http/mod.rs` currently has authenticated internal routes for node actions, inline content, and upload transfer, but no processor prepare/stage/complete contract.
- `services/letfs/migrations/0001_foundation.sql` through `0006_durable_copy.sql` contain no `artifact_dir_id`, processor operation, or processing-output tables. Those are required integration points, not existing APIs.
- `deploy/compose.test.yaml` uses SeaweedFS `4.19` (digest-pinned). The requested `scripts/test-e2e.sh` does not exist; the repository uses `scripts/test-integration.sh`, `scripts/test-workflow.sh`, and `make test-e2e`/`verify-foundation.sh` instead.
- Existing operations docs require draining HTTP/workers, pausing maintenance, and stopping storage writers before coordinated backup. A processor worker and outstanding presigned staging writes must be included in that quiescence.

## Runtime Shape

```text
Rust ProcessFile Workflow (letfs worker, workflow queue)
  |
  +-- one Activity task: process-file (dedicated activity queue)
          |
          +-- letfs prepare: validate source content identity + issue GET/inline
          +-- download snapshot
          +-- Docling convert/export in bounded local scratch
          +-- letfs stage-inline or presigned PUT to unique staging keys
          +-- letfs complete: verify, quota, server-side copy, atomic publish
```

The Python worker contains no Workflow definitions and should be configured with only the `process-file` Activity, the dedicated activity task queue, bounded activity concurrency, and no S3 credentials. It belongs to the letfs deployment boundary, not a user-facing service. Do not add Redis, Celery, embeddings, a VLM pipeline, or a second user-visible processing run.

### Durable identity and source safety

The successful upload/finalize transaction creates one durable artifact operation with the source ID, immutable content identity, validated input/options, and processor version. Use a stable operation identity such as `(source_node_id, source_content_identity, processor_version)`, where an object source identity is its immutable object key and an inline source identity is its content digest. The Workflow input should contain only operation/source IDs and small bounded options; the operation row holds the captured content identity. Never put file bytes, presigned URLs, credentials, or Docling output in Temporal history. The prepare API must transactionally:

- resolve and authorize the live source in its filesystem;
- require the expected source content identity;
- record the source object key or inline digest in durable processor state;
- enforce `MAX_OUTSTANDING_STORAGE`, source/output byte limits, and filesystem/bucket state before issuing capabilities.

**Resolved fencing rule.** Do not use metadata node revision as the publish guard: rename/move can bump it without changing content. Do not add source-retention pins or a global filesystem epoch. Completion compares the current source content identity (object key for object-backed data, digest for inline data) with the operation identity; operation supersession ensures only the current content's operation can publish. A changed object key/digest is stale; a metadata-only rename/move is not.

`artifact_dir_id` is not a caller-selected output directory. Completion creates a detached same-filesystem directory, links the generated ordinary nodes below it, and sets the source's nullable `artifact_dir_id` only in the publication transaction. There is no separate output filesystem, physical `.artifacts`/`.nodes` tree, reverse owner column, source pin, refcount, lease, or global epoch.

### Resolved artifact boundary

Expose published artifacts through virtual, case-sensitive aliases: `/.artifacts/<source-id>/...` resolves the source-owned root, while `/.nodes/<node-id>/...` resolves any scoped node ID. Raw IDs and both aliases share one source-aware visibility predicate: ordinary nodes must reach the live filesystem root, and artifact nodes must also have a live source owner. Detached trash/staging roots never become visible merely because `parent_id IS NULL`, and `..` cannot escape an artifact alias root.

Published artifact nodes are read-only through every locator. Create/modify, upload targets/finalization, move, trash, restore, purge, and artifact publication destinations reject them consistently; copying an artifact as a source into a normal live directory is allowed. A plain per-source status endpoint reports pending/ready/failed state without exposing detached root internals.

Source trash hides its aliases and restore re-enables them. Source purge and overwrite invalidation enqueue the detached artifact root through the existing bounded deletion/object-GC paths. Overwrite clears the old pointer and makes the old artifact unresolvable in the same finalize transaction; metadata-only rename/move does not supersede an operation. The upload finalize transaction also records the artifact dispatch intent, and maintenance retries a committed intent if workflow start fails.

## Presigned Storage Contract

### What the pinned Rust dependency actually supports

`object_store 0.14.2` has a `signer::Signer` trait with `signed_url` and `signed_url_opts`; the latter can bind query parameters and request headers. Its AWS implementation (`AmazonS3`) implements that trait. The generic `ObjectStore` trait does not extend `Signer`, so the current `Arc<dyn ObjectStore>` cannot be downcast or called as a presigner. Keep a second concrete `Arc<AmazonS3>`/presigner component built from the same config, or explicitly wrap the concrete store. Do not invent `app.storage.signed_url(...)`.

The signed-header facility is useful for binding `Content-Length`, checksum, and `If-None-Match: *`, but every provider must be tested with the exact signed request. The existing store uses `with_virtual_hosted_style_request(false)`, so path-style endpoint behavior remains part of the provider contract.

### Safer output protocol

1. `prepare` validates the durable operation created by upload finalization and returns a source capability plus an operation-scoped staging namespace. It never returns a final output key.
2. For each output, letfs issues a `PUT` URL for a fresh key such as `processing-stage/{operation_id}/{random_uuid}`. Bind exact content length and a checksum when the provider supports the signed headers. Conditional `If-None-Match: *` is an optional defense only; correctness must not depend on it. The Activity uploads only after local export is complete.
3. The Activity calls `complete` with output names, output kinds, sizes, hashes, and staging handles. This request is an internal authenticated letfs API, not a generic upload endpoint.
4. Outside any database transaction, letfs performs provider-side `HEAD`/checksum validation and copies each accepted staging object to a fresh unique immutable final key. It then opens a short publication transaction to recheck content identity/supersession and artifact ownership, admit quota, and link the already-verified final keys to nodes. The transaction must not hold locks across S3 `HEAD`, hash, or copy. Final keys are never presigned to the worker.
5. On completion response loss, a repeat of `complete` returns the durable published result. A late replayed staging `PUT` cannot mutate a final object. Expired/aborted/unknown staging keys remain represented by cleanup records until a grace period passes.

AWS documents that a presigned URL can be reused until expiration and an ordinary same-key `PUT` replaces the object. AWS and Cloudflare R2 document atomic `If-None-Match: *` conditional writes, but the pinned SeaweedFS `4.19` behavior is not established by this repository. That uncertainty no longer blocks the design: staging keys and unique final keys prevent correctness from depending on conditional writes. Test conditional support as an optional provider capability, not as the publication invariant.

For source download, the key recorded at prepare is the snapshot key for the expected content identity. Issue a short-lived `GET` URL immediately before download; refresh it through letfs if it expires. For an inline source, fetch bytes through an authenticated letfs inline route, not from object storage. Never let the worker choose an arbitrary bucket/key or bypass letfs quota/classification.

### Expiry, late writes, and cleanup

URL expiry is checked when the request starts; a large transfer that starts before expiry can continue, while a reconnect after expiry fails. Generate output URLs immediately before `PUT`, bound transfer time, and treat timeout/connection loss as an ambiguous write. Record the staging key durably before handing out the URL. Letfs maintenance must not delete a key while an operation or URL grace window can still use it. Existing upload behavior (`120s` transfer deadline, `1h` upload expiry, cleanup backlog limits) is a good starting pattern, but processor limits should be explicit and tested.

## Docling Runtime and Exports

As of 2026-10-29, PyPI lists `docling 2.144.0` (released 2026-10-28). The repository has no Python lockfile or Temporal Python pin; do not use a floating dependency. Pin one exact `temporalio` and Docling dependency set in the worker lockfile after the cross-language acceptance test. PyPI lists Temporal Python `1.35.0` as current, but this research did not prove that exact SDK against the repository's Temporal `1.32.1` server; it is a candidate dependency version, not a verified project choice. The existing Rust SDK remains the verified `1.1.0` dependency set.

Use the supported Docling v2 APIs:

```python
result = DocumentConverter(...).convert(local_source)
for item, level in result.document.iterate_items():
    ...
markdown = result.document.export_to_markdown()
table_df = table.export_to_dataframe(doc=result.document)
```

Docling's official v2 documentation names `DocumentConverter.convert`, `DoclingDocument.iterate_items`, `export_to_markdown`, and `TableItem.export_to_dataframe`. `SectionHeaderItem`, `TableItem`, `PictureItem`, and group labels for `SLIDE` and `SHEET` are official `docling-core` types. Build the requested flat outputs from this typed reading-order stream, not by parsing the rendered Markdown back into sections.

| Input | Required published tree | Minimal exporter behavior |
|---|---|---|
| PDF/DOCX | Flat ordered meaningful section `.md` files; `content.md` if no sections | Start a new file at `TitleItem`/`SectionHeaderItem`; preserve order; render tables with `TableItem.export_to_markdown`; optionally write `images/` and relative Markdown links. Use deterministic names such as `001-<slug>.md`; no index/manifest/document.json. |
| PPTX | Ordered slide `.md` files | Group by Docling slide group/provenance, preserve slide order, inline tables, optionally export pictures under that slide's `images/`; no presentation manifest. |
| XLSX | Ordered sheet folders, CSV per detected table, optional images | Group by sheet; an empty sheet may publish an empty folder. Every isolated non-empty cell region must produce a CSV even if Docling does not classify it as a formal table; do not silently drop non-empty cells. For detected `TableItem`s, call `export_to_dataframe(...).to_csv(index=False)` with deterministic table order. Do not publish an index/manifest. |

Filter by extension before conversion: process only `.pdf`, `.docx`, `.xlsx`, `.pptx`; bypass text and images; reject/bypass legacy `.doc`, `.xls`, `.ppt` despite Docling listing them as supported through LibreOffice. Do not enable remote VLM services, embeddings, or AI enrichment. Docling's PDF pipeline uses local layout/OCR/table models; this is document extraction, not a product embedding or generative-AI stage.

### Offline and CPU operation

Docling documents that models are downloaded on first use unless `artifacts_path` is set. Prefetch the exact model artifacts at image-build/release time and pass `PdfPipelineOptions(artifacts_path=Path("/models"))`; runtime networking must not be needed for model loading. DOCX/PPTX/XLSX do not require the PDF model weights according to the official FAQ, but the worker image should still pin and verify the complete environment.

Bound each job before conversion: source bytes <= letfs `MAX_FILE_BYTES` (currently 100 MiB), fixed scratch-directory quota, maximum output count/bytes, explicit Docling `document_timeout`, bounded pages/tables/images, and explicit CPU thread limits. The async Activity supervisor owns the temp directory, heartbeats, cancellation, and child-process lifetime; the child performs CPU-bound Docling work and returns bounded progress/results over IPC. This is an execution check to validate in tests, not a user-facing product promise.

## Temporal Execution, Cancellation, and Interoperability

Rust `temporalio-sdk 1.1.0` provides `ActivityOptions` with task queue, start/schedule-to-close timeout, heartbeat timeout, cancellation type, and retry policy. `ActivityContext` provides `record_heartbeat`, `heartbeat_details`, `is_cancelled`, and `cancelled`. Use a dedicated activity task queue in the Rust Workflow; leave the existing `openlet-letfs` lifecycle queue for Rust-owned work.

Python's official API provides `@activity.defn`, `activity.heartbeat`, `activity.is_cancelled`, cancellation waits, and `Worker(..., activities=[...], workflows=[...])`. The worker at `services/letfs/processor` registers exactly one Activity and no Workflows, and configures only the dedicated queue and bounded activity poll/concurrency settings. The Python worker should have only the letfs service token and Temporal connection details; no S3 access key/secret. The child process is an implementation detail of that Activity, not a second Temporal worker or a separate ProcessPool framework.

Temporal's official failure documentation is load-bearing here: Activities are at-least-once; heartbeat timeout triggers retry; heartbeat details may be available to the next attempt; cancellation is delivered through heartbeats. Therefore:

- heartbeat at each definite stage (`prepared`, `downloaded`, `converted`, `staged`, `completed`) and from Docling progress callbacks when available;
- set the Rust Activity `heartbeat_timeout` shorter than the worker-failure detection target but longer than the worst interval with no Docling callback;
- set `start_to_close_timeout` above the maximum bounded conversion plus upload/complete time and `schedule_to_close_timeout` to cap total retries;
- do not put URLs, source bytes, output text, or secrets in heartbeat details or Workflow history;
- propagate cancellation and make cleanup idempotent. If a cancellation arrives after a stage `PUT`, complete/abort reconciliation must leave no published partial tree.

Use plain JSON payloads for the cross-language Activity contract. Rust 1.1.0's default serde converter emits Temporal JSON payload encoding (`json/plain`); Python's default converter must be verified to decode the same payload in a real test. Keep the input/return schema to strings, UUIDs, booleans, bounded integers, and lists of output descriptors. Do not share Rust-specific protobuf or binary wrappers for this first bridge.

### Retry after lost result

The Python attempt must begin by calling letfs operation status/prepare reconciliation with the deterministic operation key. If the operation is already published, return the stored result without touching local disk. If the prior attempt staged objects but lost the response, letfs can inspect durable staging metadata and, outside DB locks, provider `HEAD`/hashes; it may finalize matching outputs or discard them. If state is unknown, use a new staging namespace and rerun conversion from the source snapshot. Never rely on a temp directory surviving on another worker, and never treat an unconfirmed local file as durable progress.

The final `complete` transaction is the idempotency boundary. It must distinguish `succeeded`, `running`, `discarding`, `stale-source`, and `failed` states, and should use stable output names/operation identity so a repeat cannot create a second user-visible run. A successful publication wins over a lost Temporal response.

## Tests and Recovery

Required acceptance is a real, non-disposable cross-language path:

1. Start the pinned Compose Temporal `1.32.1`, PostgreSQL, and SeaweedFS `4.19` stack.
2. Run a Rust `ProcessFile` Workflow that schedules the exact Python Activity name and dedicated queue.
3. Use small fixtures for one PDF, DOCX, PPTX, and XLSX; assert exact bytes, ordered output names, inline Markdown tables, CSV contents, optional image links, no index/manifest/document JSON, and bypass for text/image/legacy Office.
4. Exercise source content replacement during conversion, metadata-only rename/move, quota exhaustion, cancellation during conversion, URL expiry, failed/late `PUT`, commit-then-response-loss, worker restart, superseded operation, and repeat completion.
5. Assert the Python worker polls activities only and does not require S3 credentials. Record a real Temporal history and replay the Rust Workflow with the repository's workflow test path.
6. Verify exact provider semantics for presigned GET/PUT, signed headers, checksum/length, unique-key copy, path-style endpoint, range/large transfer, and cleanup. Conditional writes may be recorded as an optional capability but are not required for acceptance. Do not substitute an in-memory object store for these claims.

Backup/restore must stop admission, pause maintenance, drain the Rust and Python workers, wait for active processor operations and presigned transfer grace to finish or become terminal, then stop Temporal and storage writers. The backup drill must include processor state, staging cleanup records, artifact nodes, and model image/version evidence. A live URL or in-flight stage upload is not a recovery point.

## Trade-offs and Adoption Risk

| Option | Correctness after response loss | Complexity | Provider portability | Recommendation |
|---|---|---:|---:|---|
| Presigned PUT directly to final key | Unsafe: URL replay can overwrite published data | Low | Medium | Reject |
| Presigned PUT with conditional create only | Good on AWS/R2; exact SeaweedFS 4.19 behavior is unverified | Medium | Medium | Optional defense only |
| Unique staging PUT + letfs server-side copy/publish | Strong idempotency and late-write isolation; one extra server-side copy | Medium | Highest among existing stack choices | **Choose** |
| Python holds long-lived S3 credentials | Operationally simple but violates boundary and increases blast radius | Low | High | Reject |
| Separate Docling service/Redis/Celery | Scales independently but adds unrequested moving parts and recovery paths | High | Medium | Reject |

Temporal and Docling are active maintained projects with official APIs and current releases, but both have fast-moving versions. Pin exact Python packages and model artifacts, record hashes, and keep a compatibility fixture. Docling extraction fidelity is model/platform-sensitive; especially headings, OCR, merged tables, and pictures need fixture assertions rather than a blanket accuracy claim.

## Open Questions / Gaps

- The focused migration/API implementation for `nodes.artifact_dir_id`, processor operations, and staged output records remains to be written; the ownership and publication contract is resolved below.
- Which exact Python `temporalio` version passes the real payload/worker test against Temporal server `1.32.1`? Current PyPI `1.35.0` is observed, not compatibility-proven here.
- Does pinned SeaweedFS `4.19` support signed `If-None-Match: *` for an optional defense? Verify if desired; staging isolation does not depend on it.

## Status

Status: DONE

Summary: Verified the repository's Temporal/object-store/storage boundaries and current official Temporal, Docling, AWS/R2, and SeaweedFS behavior. The resolved design is one Rust Workflow plus one Python Activity under `services/letfs/processor`, with an async supervisor and cancellable CPU child, content-identity/op-supersession fencing, letfs-owned prepare/stage/complete APIs, unique staging and final keys, offline Docling artifacts, and real cross-language/provider/recovery acceptance.

Concerns/Blockers: The processor schema/API does not exist yet; Python SDK/server compatibility, the XLSX isolated-cell fallback, and exact optional SeaweedFS conditional-write behavior require implementation-time acceptance tests. CPU/model limits are execution checks, not unresolved product questions.

## Sources

- Repository: `services/letfs/Cargo.toml`, `services/letfs/src/storage/mod.rs`, `services/letfs/src/fs/uploads.rs`, `services/letfs/src/http/mod.rs`, `services/letfs/migrations/*.sql`, `deploy/compose.yaml`, `deploy/compose.test.yaml`, `docs/workflows.md`, `docs/testing.md`, `docs/operations.md`.
- [Temporal Python developer guide](https://docs.temporal.io/develop/python), [Python Activity API](https://python.temporal.io/temporalio.activity.html), [Python Worker API](https://python.temporal.io/temporalio.worker.Worker.html), and [Temporal Activity failure/heartbeat guidance](https://docs.temporal.io/encyclopedia/detecting-activity-failures).
- [Temporal Rust `ActivityOptions`](https://docs.rs/temporalio-workflow/latest/temporalio_workflow/struct.ActivityOptions.html), [Rust `ActivityContext` 1.1.0](https://docs.rs/temporalio-sdk/latest/temporalio_sdk/activities/struct.ActivityContext.html), and [Rust SDK 1.1.0 docs](https://docs.rs/crate/temporalio-sdk/latest).
- [Docling supported formats](https://docling-project.github.io/docling/usage/supported_formats/), [Docling v2 APIs](https://docling-project.github.io/docling/v2/), [Docling document converter](https://docling-project.github.io/docling/reference/document_converter/), [Docling document types/exports](https://docling-project.github.io/docling/reference/docling_document/), and [offline model guidance](https://docling-project.github.io/docling/faq/).
- [Docling PyPI 2.144.0](https://pypi.org/project/docling/2.144.0/) and [Temporal Python PyPI](https://pypi.org/project/temporalio/).
- [object_store 0.14.2 docs](https://docs.rs/crate/object_store/latest), [`Signer` source](https://docs.rs/object_store/latest/src/object_store/signer.rs.html), and [AWS S3 implementation source](https://docs.rs/object_store/latest/src/object_store/aws/mod.rs.html).
- [AWS presigned URL behavior](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html), [AWS conditional writes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html), [AWS PutObject preconditions](https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutObject.html), and [Cloudflare R2 presigned URLs](https://developers.cloudflare.com/r2/api/s3/presigned-urls/).
- [SeaweedFS S3 conditional-header source](https://github.com/seaweedfs/seaweedfs/blob/master/weed/s3api/s3api_object_handlers.go), [SeaweedFS compatibility tests](https://github.com/seaweedfs/seaweedfs/blob/master/test/s3/compatibility/README.md), and [pinned local Compose image reference](../../deploy/compose.test.yaml).

### Superseded draft points

The earlier draft suggested source-retention pins, metadata revision-only fencing, and conditional-write/provider verification as part of the core safety boundary. Controller resolution supersedes those points: use source content identity (object key or inline digest), deterministic operation supersession, all provider `HEAD`/hash/copy work outside DB locks, and unique staging-to-unique-final publication. Conditional writes remain an optional provider capability only.
