# Upload and artifact architecture proposal

> Superseded proposal: the user rejected retaining public object-byte proxying. Use [the direct-storage architecture proposal](design-261030-0825-direct-storage-architecture.md) for the replacement design; the source observations below remain historical evidence.

Researched: 2026-10-30, Asia/Ho_Chi_Minh. Status: proposed for user review; no implementation or active-plan edits. This report extends the earlier direct-object-upload research by inspecting the existing letfs implementation.

## Decision

Keep one letfs-owned upload lifecycle and the existing public streaming API. Add scoped direct S3 transfers for the Python processor, as previously requested, using the installed storage library. Reuse upload records and cleanup. Ordinary multi-file uploads publish independently. Artifacts use their existing processing operation to publish a bounded output set in one PostgreSQL transaction. Do not build a generic batch workflow service or physically copy every upload before publication.

## Evidence from established solutions

| Source | Verified behavior | Implication |
|---|---|---|
| [Rails Active Storage Blob 8.1.4](https://api.rubyonrails.org/v8.1.4/classes/ActiveStorage/Blob.html#method-c-create_before_direct_upload-21) and [S3Service](https://api.rubyonrails.org/v8.1.4/classes/ActiveStorage/Service/S3Service.html#method-i-url_for_direct_upload) | Save upload metadata/key first, upload directly to that key, then associate with the owning record. The S3 URL binds length and MD5. | Transfer and application publication are separate; publication need not move the object. Rails' shared blob model is not proposed for Openlet. |
| [Uppy S3](https://uppy.io/docs/aws-s3/) | Standard client implementations coordinate per-file transfers, signing and bounded concurrency; single PUT and multipart are distinct modes. | Do not invent a multi-file transfer protocol. Uppy is evidence, not a dependency to add to this backend-only project. |
| [AWS multipart overview](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html) | Initiate, upload parts, complete; retry failed parts. Multipart describes one object's parts. | Multiple files and multipart are different problems. Continue using an SDK instead of implementing part transfer algorithms. |
| [AWS consistency model](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html#ConsistencyModel) | Atomicity does not span object keys. | All-or-nothing artifact visibility belongs to letfs metadata, not a simulated S3 directory transaction. |
| [R2 conditional writes](https://developers.cloudflare.com/r2/reference/consistency/#conditional-writes) | Atomic `PutObject` with `If-None-Match: *`; at most one concurrent create succeeds. | Fresh final keys plus signed create-only PUT remove the need for staging-to-final copies on this provider. |
| [R2 upload methods](https://developers.cloudflare.com/r2/objects/upload-objects/) and [S3 API compatibility](https://developers.cloudflare.com/r2/api/s3/api/) | Single PUT up to 5 GiB; multipart for larger/resumable transfers; PUT supports Content-MD5. R2 aborts incomplete multipart after seven days by default. | Current 100 MiB application default does not require a new client multipart/resume API. Enforce supported direct-transfer limits explicitly. |
| [AWS abort multipart](https://docs.aws.amazon.com/AmazonS3/latest/userguide/abort-mpu.html) | Incomplete parts remain separate from completed objects and require abort or lifecycle cleanup. | Deleting the object key does not replace aborting incomplete multipart uploads. |

These sources establish the transfer primitives and separation of upload from attachment. The artifact tree, quota rules and processing operation remain Openlet-specific domain decisions.

## Current code

- `services/letfs/src/fs/uploads.rs:68`: creates an upload record and unique candidate key before storage I/O.
- `uploads.rs:81`: allows one streaming transfer through a database state transition, records SHA-256/actual length, and bounds transfer time.
- `uploads.rs:129`: bounds buffering, stores small valid UTF-8 without NUL inline, otherwise uses `object_store` PUT/multipart.
- `uploads.rs:188`: revalidates the saved destination/revision and publishes file data, quota and result in one transaction. Repeated finalize returns the original node. The candidate key becomes the published key without copy.
- `uploads.rs:261` and `fs/maintenance.rs`: terminal abort/expiry and durable cleanup records already exist.
- `services/workspace/internal/http/files.go`: authorizes public file calls and streams bytes to letfs. There is no public direct-S3 upload today.
- `services/letfs/tests/integration.rs:514` and `tests/e2e/storage_test.go:35`: existing tests cover inline/binary/large uploads, repeat finalize, duplicate transfer rejection, actor isolation and stale overwrite protection. They were read, not rerun.
- Installed `object_store` 0.14.2 already provides `Signer::signed_url_opts`, `SignedUrlOptions::with_signed_header`, `WriteMultipart::abort`, and server-controlled multipart APIs. No custom SigV4 implementation or new storage SDK is needed.

## Proposed responsibilities and flows

### Common upload ownership

letfs alone allocates keys and owns upload states, length/integrity evidence, publication and cleanup. Keep `uploads`, `file_data` and `object_deletions`; do not introduce a content/blob registry, reference counts or deduplication. The name candidate means not yet published; it does not require another physical key.

Keep a single publication primitive callable inside a transaction. Single-file finalize uses it once. Processing completion uses set-based validation/inserts for its whole bounded set, rather than invoking the single-file HTTP finalize repeatedly. No transaction holds locks while reading or writing S3.

### User files

Preserve the current public create/bytes/finalize/abort endpoints and text-edit API. Workspace authorizes each operation; letfs performs scoped resource and lifecycle checks. The existing stream classifies bytes, so callers cannot force binary data into inline text by lying about content type.

Uploading several independent user files means several instances of this same lifecycle with bounded concurrency and per-file results/retries. One failed file does not roll back successful siblings. This is a proposed default for ordinary multi-file upload, not a change to the all-or-nothing artifact requirement. There is no current public multi-file transaction contract to preserve.

Do not migrate all public transfers to direct S3 solely to integrate processing. That is a separate public-contract and operational change, with no measured need in this task. Preserve the existing endpoints and tests.

### Processor output

The Python worker continues to have no DB connection or long-lived S3 credentials. Its activity downloads the captured source using a scoped GET, runs Docling locally, and retains all scratch outputs until upload/completion finishes.

After export it sends a bounded list of relative output paths, sizes, types and integrity values to letfs. letfs creates the output upload records in a batch tied to the current processing operation/attempt; it does not create a second generic upload-batch entity. Repeat preparation for the same invocation/path reuses its record and rejects changed parameters.

- Small Markdown/CSV text is transferred to letfs and validated/stored inline. Large text and binary output use object storage. Both paths produce ready upload records, not visible nodes.
- Object output receives a scoped, short-lived presigned PUT for a unique key, with mandatory signed `If-None-Match: *`, expected length and supported integrity headers. The installed signer supplies this functionality. Do not allow unconditional retry/fallback at the same key.
- Use provider-validated transfer checksums, such as signed Content-MD5 on R2, for transport integrity. This is not a cryptographic authenticity claim. Do not assume multipart ETag equals SHA-256 or download all output again merely to recompute a hash already validated by the provider. If a particular checksum contract requires independent byte verification, that requirement must be explicit and tested.
- A lost PUT acknowledgment is reconciled against the allocated upload record and object evidence. A 412 is not automatically success. Reissuing a URL must preserve the same binding and be allowed only while that upload/operation is active.
- Preserve ordering/fencing of processing attempts. An older attempt cannot complete, abort or clean up the winning attempt's uploads. Source content identity and processing operation are checked again at publication.

One completion request contains ready upload IDs and explicit directory paths where needed, not a persisted manifest file. letfs validates paths, duplicate/colliding names, ownership, readiness, current input identity and operation state. In one short transaction it checks aggregate quota/node count, creates the complete readonly child tree directly under the source file, finalizes uploads and records success. Retrying completion returns saved success without attaching or charging twice. Failed quota leaves the source intact and output unpublished.

There is no additional filesystem or artifact folder. `/drive/report.pdf/001-introduction.md` resolves normal children. Input replacement invalidates prior output as already agreed. Processing descendants never trigger another processing workflow.

### Cleanup and durability

Reuse the maintenance workflow and deletion records. Inline abandoned data is removed from upload records; unreferenced objects are queued for deletion. Protect live upload/processing references from cleanup. Signed PUT capabilities remain usable until expiry: deleting their object can permit recreation, so cleanup evidence must survive the capability/in-flight window and ambiguous writes. Existing ambiguous-write cleanup is a starting point, not proof the direct-upload case is already implemented.

Use SDK abort on recoverable multipart failure and provider-native incomplete-multipart lifecycle for process death. Verify the selected SeaweedFS configuration too. Do not implement a parallel storage garbage-collection platform.

Keep exactly one Rust processing workflow and one Python activity. Upload prepare/transfer/complete are HTTP/application calls inside that activity, not additional Temporal workflows or activities.

## Existing fixes versus new feature work

| Classification | Evidence | Required action |
|---|---|---|
| Existing cleanup defect, established by code inspection; not reproduced at runtime | `receive` returns on stream/limit/part errors before `finish`; outer timeout drops it. No explicit multipart abort occurs on those exits. `uploads::abort` queues key deletion, while `WriteMultipart` documents no S3 cleanup on drop. | Preserve writer ownership long enough to explicitly abort on handled failures/timeouts, retain the original failure, and confirm incomplete-multipart lifecycle for crash cleanup. Add a real-provider regression that observes incomplete upload removal. |
| Existing capacity is incompatible with atomic artifact groups | `capacity` counts every unfinalized upload; the default limit is 16. Holding an entire output set until publication would reject larger sets even if transfers are sequential. | Admit a bounded processing operation as one job, and bound its child upload count/aggregate bytes separately. Do not count every child as an independent outstanding job; do not remove limits or add quota reservations. Reuse existing operation and upload rows. |
| New direct-transfer support | No current presigned upload routes; current size/hash proof comes from letfs reading the stream. | Add scoped signing and direct-upload readiness verification to the same upload module, with exact provider/signature checks. Retain existing streaming compatibility. |
| New processing publication | Single finalize currently resolves an ordinary destination and requires a directory parent; it publishes immediately. | Separate byte readiness from destination publication and add operation-bound batch prepare/complete. Preserve public directory-only mutation behavior; only processing completion may attach readonly children under files. |
| Existing lifecycle integration must be extended | Cleanup/publication knows uploads/copy items but not processing state; ordinary overwrite does not yet invalidate artifact children. | Integrate processing references, supersession, hybrid subtree lifecycle and atomic intent creation through the already planned artifact changes. This is feature work, not proof today's plain upload is broken. |

Batch metadata SQL must remain set-based; do not loop single-file finalizers or perform one node query per output. Storage still requires an actual transfer/verification per object; bounded object requests are inherent I/O, not an excuse for database N+1 queries.

## Verification and handoff

Read-only source and official-document research completed. No production code, active plan, dependency, schema or live provider configuration was modified. A docs.rs fetch failed; installed 0.14.2 source supplied the API evidence instead. No skill script failed.

Required implementation acceptance covers existing upload regressions, multipart stream failure/timeout cleanup, more than 16 artifact outputs, signed-header removal/change, sequential/concurrent PUT replay, lost responses, source overwrite during processing, stale attempts, all-or-nothing quota failure, retry without duplicate charge, and cleanup protection. Use the existing Testcontainers tests plus actual R2 provider checks for provider-specific claims.

Disk had approximately 512 MiB free. No containers/builds/models/tests were started; no runtime result is claimed. Neither R2 signing/length enforcement nor SeaweedFS 4.19 concurrency/lifecycle was empirically checked in this task.

Next step: user reviews this architecture, then update the active processing plan to remove physical stage/final copies and incorporate the specific upload corrections. Implementation remains a separate instruction.

## Unresolved product decisions

None required for this proposal. Direct-upload provider enforcement and numerical output/resource limits remain implementation acceptance checks. Changing the public upload transport or adding resumable client uploads is outside this proposal.
