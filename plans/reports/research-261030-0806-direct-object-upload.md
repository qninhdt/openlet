# Direct object uploads and publication

Researched: 2026-10-30 08:09 +07:00. Scope: single-object presigned PUT for processor outputs; no plan or implementation changes.

## Finding

Temporary-key upload followed by server-side copy is a real pattern, but it is not a universal requirement. Openlet can avoid that copy on R2 by using fresh keys and mandatory signed conditional-create requests, while retaining unpublished upload records and atomic database publication.

## Verified implementations and platform behavior

- [Rails Active Storage 8.1.4 S3Service](https://api.rubyonrails.org/v8.1.4/classes/ActiveStorage/Service/S3Service.html#method-i-url_for_direct_upload) presigns PUT against the supplied blob key with expected length, content type and MD5. Its direct-upload method has no temporary-to-final copy. [Blob](https://api.rubyonrails.org/v8.1.4/classes/ActiveStorage/Blob.html) documents creating metadata before direct upload and treating file content as immutable. This source does not establish that Rails uses `If-None-Match`.
- [GitLab's CarrierWave/Workhorse upload guide](https://docs.gitlab.com/development/uploads/working_with_uploads/#direct-upload-via-workhorse) explicitly describes temporary upload, remote copy to final location, and temporary cleanup.
- [GitLab artifact operations documentation](https://docs.gitlab.com/administration/cicd/job_artifacts_troubleshooting/#final-artifacts-not-deleted-from-object-store) documents artifacts uploaded directly to their final location and the need to clean up orphaned objects. Both approaches exist within GitLab; the CarrierWave flow is not a universal artifact requirement.
- [AWS presigned URL documentation](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html) confirms URL reuse until expiry and ordinary PUT replacement of an existing key.
- [AWS conditional writes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html) provides `If-None-Match: *` to prevent overwriting an existing object.
- [R2 consistency documentation](https://developers.cloudflare.com/r2/reference/consistency/#conditional-writes) explicitly guarantees atomic conditional PUT at commit: concurrent creates of an absent key have at most one success; other requests receive 412. Its negative-read section warns that HEAD 404 does not cancel an earlier in-flight PUT.
- [R2 presigned URL documentation](https://developers.cloudflare.com/r2/api/s3/presigned-urls/) describes SigV4 signed headers and reusable PUT URLs. The application must sign the mandatory condition, not merely ask the worker to send it.

## Recommended Openlet flow — synthesis, not a copied implementation

1. letfs allocates a fresh object key and an unpublished upload record for each object-backed output. Inline text continues through letfs; it needs no S3 upload.
2. letfs returns a short-lived PUT URL requiring signed `If-None-Match: *`, with the expected length and supported integrity constraints bound to the request. Python uploads directly to that key.
3. letfs verifies upload evidence. If a PUT response is lost and a repeat receives 412, reconcile the stored object against the expected output; 412 alone is not proof of successful correct upload.
4. Once all outputs are ready, one database transaction checks that the source content and processing operation are still current, attaches children, and accounts for quota exactly once. The same object keys remain in use; there is no copy or rename.
5. Failed or superseded operations retain cleanup evidence. Conditional create only protects an existing object: deletion allows a still-valid URL to create the key again. Cleanup must cover URL validity and outstanding requests rather than deleting once and forgetting the key. Never reuse keys for different content.

Logical publication remains necessary for the agreed all-or-nothing artifact tree; physical temporary and final copies do not follow from that requirement. Existing source/attempt guards still prevent old workers from attaching obsolete results. Neither a Temporal timeout nor conditional PUT replaces those database checks.

The benefit is removing one copy and temporary-object lifecycle per output. The requirement is reliable conditional-create enforcement and correct signing on every supported provider. Do not silently fall back to unconditional PUT if a provider fails this contract.

## Local provider and verification limits

`deploy/compose.test.yaml` pins SeaweedFS 4.19. Its [tagged PUT implementation](https://github.com/seaweedfs/seaweedfs/blob/4.19/weed/s3api/s3api_object_handlers_put.go#L782) rechecks conditional headers through `withObjectWriteLock` around filer entry creation. This is source evidence of enforcement, not a runtime proof of every upload path or deployment topology.

No containers, SDK integration, live R2 requests, multipart races, or benchmarks were run during this research. Before implementation is accepted, exercise the actual signed PUT path on pinned SeaweedFS and R2: normal create, sequential/concurrent replay, omitted/changed signed condition, wrong length/integrity, and lost-response reconciliation. Multipart completion requires separate verification if introduced.

Next step: present this recommendation for the user's decision; only then replace the mandatory stage-to-final copy in the active plan. Keep metadata publication, stale-result rejection and cleanup obligations.
