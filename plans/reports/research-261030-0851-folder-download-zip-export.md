# Folder downloads and ZIP exports

Researched: 2026-10-30 08:56 Asia/Ho_Chi_Minh.
Status: final design recommendation for discussion; no implementation or execution-plan changes. This report supersedes the ZIP/export recommendations in the earlier direct-storage report where they differ. Subsequent user decisions already supersede that report's upload classification: callers choose inline/object; the backend enforces inline size without reclassification.

## Outcome and scope

Download a selection or folder as a ZIP containing original file payloads, preserving ordinary folder structure. Explicit artifact export uses the same archive engine. Retain Rust letfs, PostgreSQL, private S3/R2, existing Temporal workers, and direct S3 delivery to the client. No historical folder snapshot, archive cache, additional service, per-entry workflow, or reference-count system.

Acceptance requires correct inline/object bytes and paths, original-only folder traversal, explicit artifact traversal, bounded resources, no partial archive published, and direct client download from storage.

## Verified practice

- [OneDrive/SharePoint](https://support.microsoft.com/en-gb/onedrive/download-files-and-folders-from-onedrive-or-sharepoint) downloads a multi-selection as ZIP. The page documents user behavior, not its internal worker/storage architecture.
- [Dropbox](https://help.dropbox.com/sync/download-entire-folders), updated February 16, 2026, documents ZIP folder downloads with file-count and uncompressed-size limits. Its limits are not proposed as Openlet limits.
- [Box create ZIP](https://developer.box.com/reference/post-zip-downloads) checks selection access and returns download/status URLs, expiry, and name conflicts. It does not establish a prebuilt-S3 architecture.
- [Box ZIP content](https://developer.box.com/reference/get-zip-downloads-id-content) describes streamed archive contents; a started download cannot be stopped and resumed. [Box status](https://developer.box.com/reference/get-zip-downloads-id-status) is available after download starts and reports progress/skipped items. It is not a documented prebuild-readiness polling API.
- [AWS downloads](https://docs.aws.amazon.com/AmazonS3/latest/userguide/download-objects.html) documents individual object GET/Range and a multiple-object example that downloads objects and separately creates a ZIP. A presigned GET alone does not assemble multiple objects into an archive.
- [AWS multipart](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html) provides part upload, completion and abort. It transports archive bytes produced by an application; it does not generate ZIP structure.

## Alternatives and decision

Streaming an archive to the HTTP client is a valid design: download can start sooner and there is no temporary archive object. Its first operational weakness is that generation is coupled to the client connection; an interrupted transfer may require generating the archive again. Box documents a non-resumable ZIP download contract, without exposing whether it generates or caches contents internally.

Openlet should instead build one temporary archive in the existing worker and deliver the completed object by presigned GET. It adds preparation latency and temporary S3 I/O/storage, but archive generation survives client disconnects, failed builds expose no partial ZIP, and downloading the same completed object supports ordinary S3 Range/retry. This is an Openlet engineering choice for the accepted direct-storage design, not a claim that all cloud drives work this way. No better approach was found under those constraints; do not implement both delivery modes for MVP.

## Final recommended behavior

- Single-file download returns the file's own current bytes, whether inline or object-backed. It does not start an archive workflow.
- Selecting an ordinary folder or multiple entries starts a ZIP export. Traverse folder nodes recursively. At a file node, include its payload and stop traversal even when that file has generated children.
- Thus normal folder download includes uploaded and manually-created files, and writable copies of artifacts placed in ordinary folders. It does not implicitly include attached generated artifacts.
- Explicit source-artifact export starts traversal at the source's published children and produces `report.pdf-artifacts.zip`, with paths relative to those children. A directly selected artifact file downloads normally; a directly selected artifact folder exports its subtree.
- Preserve selected directory roots and empty directories. Deduplicate overlapping selections and deterministically disambiguate duplicate top-level names without renaming stored nodes. ZIP paths must be safe relative paths.

ZIP format can contain conflicting entry names; the practical problem is that ordinary destination filesystems cannot extract both a regular `report.pdf` and a `report.pdf/...` directory tree at the same location. The original-only traversal is an Openlet product rule, not a limitation preventing ZIP encoding.

## Runtime

1. Workspace authorizes the selection and forwards scoped metadata to letfs. letfs creates an export operation and returns an operation ID/status route.
2. Reuse the existing durable-operation dispatch pattern to start one `ExportArchive` workflow with one archive activity in the Rust letfs worker. No extra service or Python Docling worker is needed.
3. The activity validates current scope/liveness, enumerates bounded metadata in set-based queries, and captures paths and object keys or inline node revisions for the attempt. Avoid a long database transaction across storage I/O and avoid N+1 inline reads.
4. Read inline bytes in bounded batches and stream object bytes from S3. Use a maintained ZIP/ZIP64 library and stream its output into a native S3 multipart upload with bounded buffering. No complete archive in RAM or full local input download is required.
5. Record the candidate key before writing: `exports/<operation-id>/<attempt-id>.zip`. Only after ZIP finalization and S3 completion succeeds may the current attempt publish its result through the operation record. An obsolete attempt cannot replace the winning result.
6. The caller polls operation status and requests a download descriptor after success. Reauthorize when issuing/renewing the short-lived presigned GET; the client downloads directly from S3. Renewal/Range always references the same export object.

A retry rebuilds the archive into a fresh attempt key; no per-entry durable checkpoints. Inputs can be re-enumerated on retry. Within an attempt, do not substitute newer bytes or silently omit unavailable entries: fail the export. This is not a point-in-time historical folder snapshot. Source deletion/overwrite may make an in-progress build fail.

## Bounds and cleanup

Enforce configurable entry-count, source-byte, resulting-byte, runtime and concurrency limits. Reject known excess before generation and enforce output bounds while writing. Exact numeric ceilings require implementation configuration; vendor product limits are evidence that limits are normal, not workload sizing evidence.

Temporary exports are not filesystem nodes and do not consume logical workspace quota, so a full workspace can still download itself. Retain completed exports for 24 hours by default, with short-lived GET URLs bounded by the operation's logical expiry. Provider lifecycle handles eventual physical expiry of the export prefix; reuse existing cleanup for failed attempt keys and native incomplete-multipart abort/lifecycle. Lifecycle removal is asynchronous, not an exact deletion-time guarantee.

No workflow per file, archive cache, stored manifest file, AI processing dependency, new database for archives, or separate cleanup service.

## Verification and remaining work

Research only: official documentation was read; no code, plan, configuration, schema, runtime tests or provider resources were changed. One Box guide URL was unavailable; its official endpoint references supplied the needed evidence.

Implementation must verify ZIP library streaming/multipart integration, ZIP64 and empty directories, safe names/collisions, overlap handling, original-only traversal, artifact export, inline/object byte correctness, source changes, failed/reordered attempts, resource limits, expiry and direct Range delivery on pinned SeaweedFS and R2.

Unresolved product questions: none required for this recommendation. Numeric limits and library/provider behavior remain implementation checks.
