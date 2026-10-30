# File-operation retries: production evidence

Research date: 2026-10-29, Asia/Saigon. Scope: whether short trash/restore/delete operations require stored-response replay, distinct from safe side effects and durable workflow progress. Sources are official API documentation, HTTP standards and pinned Nextcloud source. No live vendor requests or Openlet tests were executed. This report does not change the current plan by itself.

## Conclusion

The reviewed public contracts support resource state, conditional requests, stable identities and asynchronous operation status; they do not require universal exact-response replay for trash/restore/delete. Openlet can omit request-result records for its direct short trash/restore/file-purge operations if it explicitly supports ambiguous-response recovery and guards stale retries. Durable operation/checkpoint state remains justified for multi-step work. This recommendation is an Openlet inference, not a claim about private Google/Microsoft database internals.

## Evidence

| Source | Observed contract | What it establishes |
|---|---|---|
| [RFC 9110 section 9.2.2](https://www.rfc-editor.org/rfc/rfc9110.html#section-9.2.2) | Idempotency concerns intended effects; a repeated request can return a different response. PUT/DELETE are idempotent methods. | Response replay and side-effect idempotency are separate guarantees. POST is not automatically retry-safe merely because the business action sounds idempotent. |
| [RFC 9110 section 13.1.1](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.1) | False If-Match prevents mutation; 412 is appropriate, with permitted success if the server determines the change already happened. | Strong conditional revision checks can guard retry without an identical success response. |
| [Google Drive trash/restore guide](https://developers.google.com/workspace/drive/api/guides/delete) | files.update sets trashed true or false; current trash state is retrievable. | A resource-state API rather than a documented universal request-receipt contract. Does not specify every repeated-request outcome. |
| [Google Drive upload guide: pre-generated IDs](https://developers.google.com/workspace/drive/api/guides/manage-uploads#use_a_pre-generated_id_to_upload_files) | Pre-generated IDs make supported upload retries safe; a retry after successful creation returns 409 rather than creating a duplicate. | Direct positive example: safe retry without replay of the original response. Restrictions apply to Workspace document types. |
| [Microsoft Graph delete v1.0](https://learn.microsoft.com/en-us/graph/api/driveitem-delete?view=graph-rest-1.0) | DELETE moves item to recycle bin; optional If-Match mismatch returns 412 without deleting; success is 204. | Real cloud-drive conditional delete. The page neither requires an Idempotency-Key nor promises exact response replay or a particular status for every repeated deletion. |
| [Microsoft Graph restore v1.0](https://learn.microsoft.com/en-us/graph/api/driveitem-restore?view=graph-rest-1.0) | POST restore accepts optional parent/name and returns restored item. The documented API is currently OneDrive Personal only. | State-specific restore action without a documented response-replay key. Not proof of repeated-call behavior. |
| [Nextcloud trash WebDAV](https://docs.nextcloud.com/server/stable/developer_manual/client_apis/WebDAV/trashbin.html) | PROPFIND lists trash, MOVE restores, DELETE purges. | Resource/WebDAV primitives, without a documented per-request receipt requirement. |
| [Nextcloud AbstractTrash, pinned commit](https://github.com/nextcloud/server/blob/b63fed182ee4c1b712373b92a9e37c51a78d258a/apps/files_trashbin/lib/Sabre/AbstractTrash.php#L81-L93) | delete checks policy then invokes removeItem; restore invokes restoreItem. | The inspected adapter has no request-key/response-receipt lookup. This is not an audit proving no deduplication exists anywhere downstream. |
| [Microsoft Graph async copy](https://learn.microsoft.com/en-us/graph/api/driveitem-copy?view=graph-rest-1.0) | 202 plus Location monitoring URL, with later success/failure. | Durable operation status is established practice for long work; not proof that submitting the same POST is automatically deduplicated. |
| [Temporal Activity Definition](https://docs.temporal.io/activity-definition#idempotency) | An activity may commit effects then fail to acknowledge and be retried; completed activity results are reused during normal workflow replay. | Application side effects must be retry-safe. Workflow replay does not mean every HTTP response needs persistent replay storage. |

## Openlet recommendation

- Keep transactions, atomic quota changes and monotonically increasing revisions for direct operations. No generic receipt table just for trash/restore/file-purge responses.
- Require the original precondition on mutation retries; never silently fetch a new revision and repeat destructive intent after a conflict. A delayed old trash request must not trash a file that somebody already restored.
- Target stable IDs/trash-entry identities, not a path that could now refer to another file. Public path mutation requests should require a stable expected target ID as well as its revision, or resolve to ID before issuing the mutation; per-node revision values alone can coincide after path replacement.
- A repeated request can return 404, 409 or 412 according to the defined state/precondition contract. None proves which actor caused the current state. An authorized client must refresh live/trash state and present unresolved outcomes honestly; never treat every 404 as successful deletion.
- Keep existing upload ID/state/result for finalize retries; return the recorded file identity/current operation outcome as needed. Exact original HTTP payload/header replay is unnecessary.
- Keep operation IDs, scope-bound deduplication and durable batch checkpoints for provisioning, copy and destructive workflows. Prevent duplicate effects and allow status inspection; do not implement a universal stored-response framework.
- Regression cases: commit then response loss, trash -> restore -> delayed old trash request, restore -> re-trash -> delayed old restore request, ID/path replacement, repeated purge with zero extra quota debit, and workflow activity retry after commit.

## Limits and next step

Google/Microsoft internal implementation is unavailable; absence of a documented key cannot prove absence of internal request deduplication. Published docs do not specify all repeated restore/delete status codes. Select Openlet's own response codes and client reconciliation contract explicitly when reconciling the plan. Live provider and Openlet behavior remain unverified.
