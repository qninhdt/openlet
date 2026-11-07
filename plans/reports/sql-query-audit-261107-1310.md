# SQL statement audit

Scope: application-owned Go store SQL in Account, Workspace and LetFS, including maintenance. AST callsite inventory includes concatenated and variable SQL arguments; each row is an execution site, not a distinct query template. Migration DDL, driver/framework SQL, tests and benchmark fixtures are excluded. No additional database access owner or alternate Go/Python database execution API was found.

233 execution sites reviewed. Three entries are lock/savepoint control statements; repeated templates remain separate because their call paths differ. Dynamic arguments (`query`, `fsSQL`, `scopeSQL`) were traced to their builders. Performance evidence and retained/rejected changes are recorded in [the measurement report](performance-261107-1310-semantic-sql-audit.md). Full SQL expressions and decisions are retained locally in [the ledger](../../.local/sql-performance/sql-audit-ledger.json).

## apps/account/internal/account/relations.go

| Source | Owner | Disposition |
|---|---|---|
| [line 24](../../apps/account/internal/account/relations.go:24) | `SyncRelationships` | Keep bounded PK batch / PK keyset; account rebuild page measured. |
| [line 65](../../apps/account/internal/account/relations.go:65) | `RelationshipIDs` | Keep bounded PK batch / PK keyset; account rebuild page measured. |

## apps/account/internal/account/service.go

| Source | Owner | Disposition |
|---|---|---|
| [line 38](../../apps/account/internal/account/service.go:38) | `GetOnboarding` | Keep indexed identity lookup/mutation and its state/ownership guards. |

## apps/account/internal/account/store.go

| Source | Owner | Disposition |
|---|---|---|
| [line 49](../../apps/account/internal/account/store.go:49) | `EnsureAccount` | Keep atomic publication/upsert and existing FK/unique checks; PK or bounded input identities. |
| [line 68](../../apps/account/internal/account/store.go:68) | `CreateManaged` | Keep atomic publication/upsert and existing FK/unique checks; PK or bounded input identities. |
| [line 82](../../apps/account/internal/account/store.go:82) | `Profile` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 93](../../apps/account/internal/account/store.go:93) | `UpdateProfile` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 104](../../apps/account/internal/account/store.go:104) | `Summaries` | Keep bounded identity batch using existing PK/unique indexes. |
| [line 121](../../apps/account/internal/account/store.go:121) | `Subject` | Keep indexed identity lookup/mutation and its state/ownership guards. |

## apps/workspace/internal/workspace/authorization.go

| Source | Owner | Disposition |
|---|---|---|
| [line 41](../../apps/workspace/internal/workspace/authorization.go:41) | `lockAdmission` | Keep owning lock and ordering; no query/data traversal to optimize. |

## apps/workspace/internal/workspace/deletion.go

| Source | Owner | Disposition |
|---|---|---|
| [line 25](../../apps/workspace/internal/workspace/deletion.go:25) | `MarkWorkspaceDeleting` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 40](../../apps/workspace/internal/workspace/deletion.go:40) | `RemoveWorkspace` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 50](../../apps/workspace/internal/workspace/deletion.go:50) | `RemoveWorkspace` | Keep existing scoped/identity access; retain transaction/state checks. |
| [line 53](../../apps/workspace/internal/workspace/deletion.go:53) | `RemoveWorkspace` | Keep indexed identity lookup/mutation and its state/ownership guards. |

## apps/workspace/internal/workspace/invitations.go

| Source | Owner | Disposition |
|---|---|---|
| [line 57](../../apps/workspace/internal/workspace/invitations.go:57) | `Invite` | Keep token, pending-email and workspace-page indexes; page/token/delete controls measured. |
| [line 60](../../apps/workspace/internal/workspace/invitations.go:60) | `Invite` | Keep token, pending-email and workspace-page indexes; page/token/delete controls measured. |
| [line 77](../../apps/workspace/internal/workspace/invitations.go:77) | `Invite` | Keep token, pending-email and workspace-page indexes; page/token/delete controls measured. |
| [line 87](../../apps/workspace/internal/workspace/invitations.go:87) | `Invitations` | Keep token, pending-email and workspace-page indexes; page/token/delete controls measured. |
| [line 115](../../apps/workspace/internal/workspace/invitations.go:115) | `RevokeInvite` | Keep token, pending-email and workspace-page indexes; page/token/delete controls measured. |
| [line 131](../../apps/workspace/internal/workspace/invitations.go:131) | `AdmitInvitation` | Keep token, pending-email and workspace-page indexes; page/token/delete controls measured. |

## apps/workspace/internal/workspace/maintenance.go

| Source | Owner | Disposition |
|---|---|---|
| [line 6](../../apps/workspace/internal/workspace/maintenance.go:6) | `PruneReceipts` | Keep expiry-index + PK deletion, bounded 100; measured. |

## apps/workspace/internal/workspace/membership.go

| Source | Owner | Disposition |
|---|---|---|
| [line 20](../../apps/workspace/internal/workspace/membership.go:20) | `applyMembership` | Keep workspace/member PK and invitation-token access; scoped member count measured; preserve serialized membership rules. |
| [line 32](../../apps/workspace/internal/workspace/membership.go:32) | `applyMembership` | Keep workspace/member PK and invitation-token access; scoped member count measured; preserve serialized membership rules. |
| [line 48](../../apps/workspace/internal/workspace/membership.go:48) | `applyMembership` | Keep workspace/member PK and invitation-token access; scoped member count measured; preserve serialized membership rules. |
| [line 64](../../apps/workspace/internal/workspace/membership.go:64) | `applyMembership` | Keep workspace/member PK and invitation-token access; scoped member count measured; preserve serialized membership rules. |
| [line 70](../../apps/workspace/internal/workspace/membership.go:70) | `applyMembership` | Keep workspace/member PK and invitation-token access; scoped member count measured; preserve serialized membership rules. |
| [line 75](../../apps/workspace/internal/workspace/membership.go:75) | `applyMembership` | Keep workspace/member PK and invitation-token access; scoped member count measured; preserve serialized membership rules. |
| [line 84](../../apps/workspace/internal/workspace/membership.go:84) | `applyMembership` | Keep workspace/member PK and invitation-token access; scoped member count measured; preserve serialized membership rules. |
| [line 89](../../apps/workspace/internal/workspace/membership.go:89) | `applyMembership` | Keep workspace/member PK and invitation-token access; scoped member count measured; preserve serialized membership rules. |

## apps/workspace/internal/workspace/mutation_receipt.go

| Source | Owner | Disposition |
|---|---|---|
| [line 20](../../apps/workspace/internal/workspace/mutation_receipt.go:20) | `mutationApplied` | Keep receipt PK lookup/upsert; preserve replay/conflict/expiry checks. |
| [line 40](../../apps/workspace/internal/workspace/mutation_receipt.go:40) | `saveMutationReceipt` | Keep atomic publication/upsert and existing FK/unique checks; PK or bounded input identities. |
| [line 45](../../apps/workspace/internal/workspace/mutation_receipt.go:45) | `CompleteMutation` | Keep receipt PK lookup/upsert; preserve replay/conflict/expiry checks. |

## apps/workspace/internal/workspace/relations.go

| Source | Owner | Disposition |
|---|---|---|
| [line 64](../../apps/workspace/internal/workspace/relations.go:64) | `PublishStorageRelationships` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 80](../../apps/workspace/internal/workspace/relations.go:80) | `RemoveRelationships` | Keep existing scoped/identity access; retain transaction/state checks. |
| [line 89](../../apps/workspace/internal/workspace/relations.go:89) | `RemoveRelationships` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 106](../../apps/workspace/internal/workspace/relations.go:106) | `RelationshipIDs` | Keep indexed keyset traversal; no offset or pagination engine. |
| [line 114](../../apps/workspace/internal/workspace/relations.go:114) | `RebuildWorkspaceRelationships` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 127](../../apps/workspace/internal/workspace/relations.go:127) | `RebuildWorkspaceRelationships` | Keep indexed keyset traversal; no offset or pagination engine. |
| [line 171](../../apps/workspace/internal/workspace/relations.go:171) | `ChangeScopeAccess` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 191](../../apps/workspace/internal/workspace/relations.go:191) | `UpdateScopeAccess` | Keep indexed identity lookup/mutation and its state/ownership guards. |

## apps/workspace/internal/workspace/service.go

| Source | Owner | Disposition |
|---|---|---|
| [line 244](../../apps/workspace/internal/workspace/service.go:244) | `AcceptInvitation` | Keep indexed identity lookup/mutation and its state/ownership guards. |

## apps/workspace/internal/workspace/store.go

| Source | Owner | Disposition |
|---|---|---|
| [line 106](../../apps/workspace/internal/workspace/store.go:106) | `getInTransaction` | Keep existing scoped/identity access; retain transaction/state checks. |
| [line 109](../../apps/workspace/internal/workspace/store.go:109) | `Get` | Keep existing scoped/identity access; retain transaction/state checks. |
| [line 114](../../apps/workspace/internal/workspace/store.go:114) | `FindCreation` | Keep receipt PK lookup/upsert; preserve replay/conflict/expiry checks. |
| [line 137](../../apps/workspace/internal/workspace/store.go:137) | `SaveWorkspace` | Keep owning lock and ordering; no query/data traversal to optimize. |
| [line 142](../../apps/workspace/internal/workspace/store.go:142) | `SaveWorkspace` | Keep receipt PK lookup/upsert; preserve replay/conflict/expiry checks. |
| [line 152](../../apps/workspace/internal/workspace/store.go:152) | `SaveWorkspace` | Keep atomic publication/upsert and existing FK/unique checks; PK or bounded input identities. |
| [line 155](../../apps/workspace/internal/workspace/store.go:155) | `SaveWorkspace` | Keep atomic publication/upsert and existing FK/unique checks; PK or bounded input identities. |
| [line 168](../../apps/workspace/internal/workspace/store.go:168) | `List` | Keep indexed keyset traversal; no offset or pagination engine. |
| [line 175](../../apps/workspace/internal/workspace/store.go:175) | `Members` | Keep indexed keyset traversal; no offset or pagination engine. |
| [line 183](../../apps/workspace/internal/workspace/store.go:183) | `Member` | Keep existing scoped/identity access; retain transaction/state checks. |
| [line 208](../../apps/workspace/internal/workspace/store.go:208) | `Update` | Keep indexed identity lookup/mutation and its state/ownership guards. |

## apps/letfs/internal/filesystem/archive.go

| Source | Owner | Disposition |
|---|---|---|
| [line 101](../../apps/letfs/internal/filesystem/archive.go:101) | `preflightArchive` | Keep indexed tree preflight/current ancestor checks; both measured, streaming revalidation remains necessary. |
| [line 184](../../apps/letfs/internal/filesystem/archive.go:184) | `archivePayload` | Keep indexed tree preflight/current ancestor checks; both measured, streaming revalidation remains necessary. |

## apps/letfs/internal/filesystem/artifacts.go

| Source | Owner | Disposition |
|---|---|---|
| [line 46](../../apps/letfs/internal/filesystem/artifacts.go:46) | `recordIntent` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 57](../../apps/letfs/internal/filesystem/artifacts.go:57) | `DiscardForests` | Keep existing scoped/identity access; retain transaction/state checks. |
| [line 96](../../apps/letfs/internal/filesystem/artifacts.go:96) | `discardForest` | Keep existing scoped/identity access; retain transaction/state checks. |
| [line 115](../../apps/letfs/internal/filesystem/artifacts.go:115) | `enqueueIndexDeletion` | Keep atomic publication/upsert and existing FK/unique checks; PK or bounded input identities. |
| [line 120](../../apps/letfs/internal/filesystem/artifacts.go:120) | `discardUploads` | Keep source/generation and receipt-expression indexes from preceding measured optimization. |
| [line 129](../../apps/letfs/internal/filesystem/artifacts.go:129) | `discardUploads` | Keep source/generation and receipt-expression indexes from preceding measured optimization. |
| [line 135](../../apps/letfs/internal/filesystem/artifacts.go:135) | `completeProcessingReceipt` | Keep source/generation and receipt-expression indexes from preceding measured optimization. |
| [line 142](../../apps/letfs/internal/filesystem/artifacts.go:142) | `invalidate` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 156](../../apps/letfs/internal/filesystem/artifacts.go:156) | `invalidate` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 162](../../apps/letfs/internal/filesystem/artifacts.go:162) | `invalidate` | Keep existing scoped/identity access; retain transaction/state checks. |
| [line 167](../../apps/letfs/internal/filesystem/artifacts.go:167) | `fenceTrashed` | Keep actual subtree traversal and per-source fenced writes; output proportional to affected originals. |
| [line 192](../../apps/letfs/internal/filesystem/artifacts.go:192) | `fenceTrashed` | Keep actual subtree traversal and per-source fenced writes; output proportional to affected originals. |

## apps/letfs/internal/filesystem/backfill.go

| Source | Owner | Disposition |
|---|---|---|
| [line 21](../../apps/letfs/internal/filesystem/backfill.go:21) | `BackfillCandidates` | Optimize: keep live-tree traversal and carry name/revision to remove duplicate node lookup; benchmark both modes, custom/generic plans and generated-artifact shapes. |
| [line 61](../../apps/letfs/internal/filesystem/backfill.go:61) | `AdmitBackfill` | Keep PK revalidation/guarded update after workflow I/O; backfill observations are not authorization to skip current checks. |
| [line 72](../../apps/letfs/internal/filesystem/backfill.go:72) | `AdmitBackfill` | Keep PK revalidation/guarded update after workflow I/O; backfill observations are not authorization to skip current checks. |

## apps/letfs/internal/filesystem/copy.go

| Source | Owner | Disposition |
|---|---|---|
| [line 74](../../apps/letfs/internal/filesystem/copy.go:74) | `selectCopy` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 83](../../apps/letfs/internal/filesystem/copy.go:83) | `selectCopy` | Keep existing scoped/identity access; retain transaction/state checks. |
| [line 126](../../apps/letfs/internal/filesystem/copy.go:126) | `prepareCopy` | Keep receipt PK lookup/upsert; preserve replay/conflict/expiry checks. |
| [line 173](../../apps/letfs/internal/filesystem/copy.go:173) | `prepareCopy` | Keep existing scoped/identity access; retain transaction/state checks. |
| [line 196](../../apps/letfs/internal/filesystem/copy.go:196) | `prepareCopy` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 230](../../apps/letfs/internal/filesystem/copy.go:230) | `CopyNode` | Keep atomic publication/upsert and existing FK/unique checks; PK or bounded input identities. |

## apps/letfs/internal/filesystem/copy_data.go

| Source | Owner | Disposition |
|---|---|---|
| [line 32](../../apps/letfs/internal/filesystem/copy_data.go:32) | `copySource` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 87](../../apps/letfs/internal/filesystem/copy_data.go:87) | `copyCommitted` | Keep existing scoped/identity access; retain transaction/state checks. |
| [line 96](../../apps/letfs/internal/filesystem/copy_data.go:96) | `releaseCopyCandidate` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 107](../../apps/letfs/internal/filesystem/copy_data.go:107) | `validateCopyCandidate` | Keep existing scoped/identity access; retain transaction/state checks. |
| [line 113](../../apps/letfs/internal/filesystem/copy_data.go:113) | `validateCopyCandidate` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 158](../../apps/letfs/internal/filesystem/copy_data.go:158) | `commitCopyItem` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 172](../../apps/letfs/internal/filesystem/copy_data.go:172) | `commitCopyItem` | Keep atomic publication/upsert and existing FK/unique checks; PK or bounded input identities. |
| [line 192](../../apps/letfs/internal/filesystem/copy_data.go:192) | `commitCopyItem` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 209](../../apps/letfs/internal/filesystem/copy_data.go:209) | `commitCopyItem` | Keep transaction control; not a data-access performance candidate. |
| [line 219](../../apps/letfs/internal/filesystem/copy_data.go:219) | `commitCopyItem` | Keep atomic publication/upsert and existing FK/unique checks; PK or bounded input identities. |
| [line 223](../../apps/letfs/internal/filesystem/copy_data.go:223) | `commitCopyItem` | Keep atomic publication/upsert and existing FK/unique checks; PK or bounded input identities. |
| [line 231](../../apps/letfs/internal/filesystem/copy_data.go:231) | `commitCopyItem` | Keep transaction control; not a data-access performance candidate. |
| [line 284](../../apps/letfs/internal/filesystem/copy_data.go:284) | `nextCopyItem` | Keep indexed keyset traversal; no offset or pagination engine. |
| [line 321](../../apps/letfs/internal/filesystem/copy_data.go:321) | `finishCopyFile` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 329](../../apps/letfs/internal/filesystem/copy_data.go:329) | `finishCopyFile` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 341](../../apps/letfs/internal/filesystem/copy_data.go:341) | `inScope` | Keep indexed identity lookup/mutation and its state/ownership guards. |

## apps/letfs/internal/filesystem/deletion.go

| Source | Owner | Disposition |
|---|---|---|
| [line 42](../../apps/letfs/internal/filesystem/deletion.go:42) | `PrepareTrashPurge` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 48](../../apps/letfs/internal/filesystem/deletion.go:48) | `PrepareTrashPurge` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 66](../../apps/letfs/internal/filesystem/deletion.go:66) | `fenceScopeDeletion` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 72](../../apps/letfs/internal/filesystem/deletion.go:72) | `fenceScopeDeletion` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 75](../../apps/letfs/internal/filesystem/deletion.go:75) | `fenceScopeDeletion` | Keep scoped nodes/files bulk enqueue; affected-row work is necessary for deletion. |
| [line 79](../../apps/letfs/internal/filesystem/deletion.go:79) | `fenceScopeDeletion` | Optimize access with full uploads_by_scope; pending-only indexes omit terminal uploads. |
| [line 85](../../apps/letfs/internal/filesystem/deletion.go:85) | `fenceScopeDeletion` | Optimize access with full uploads_by_scope; pending-only indexes omit terminal uploads. |
| [line 89](../../apps/letfs/internal/filesystem/deletion.go:89) | `fenceScopeDeletion` | Optimize access with full uploads_by_scope; pending-only indexes omit terminal uploads. |
| [line 102](../../apps/letfs/internal/filesystem/deletion.go:102) | `removeNodes` | Keep bounded leaf identity batch, atomic cleanup/accounting and FK checks; per-source uploads/receipts already indexed. |
| [line 123](../../apps/letfs/internal/filesystem/deletion.go:123) | `removeNodes` | Keep bounded leaf identity batch, atomic cleanup/accounting and FK checks; per-source uploads/receipts already indexed. |
| [line 128](../../apps/letfs/internal/filesystem/deletion.go:128) | `removeNodes` | Keep bounded leaf identity batch, atomic cleanup/accounting and FK checks; per-source uploads/receipts already indexed. |
| [line 131](../../apps/letfs/internal/filesystem/deletion.go:131) | `removeNodes` | Optimize: partial scope/original_parent index avoids scanning unrelated trash in every deletion batch. |
| [line 134](../../apps/letfs/internal/filesystem/deletion.go:134) | `removeNodes` | Keep bounded leaf identity batch, atomic cleanup/accounting and FK checks; per-source uploads/receipts already indexed. |
| [line 155](../../apps/letfs/internal/filesystem/deletion.go:155) | `deletionLeaves` | Keep indexed branch/leaf traversal and bounded 64 removal; descent/sibling/scope leaf queries measured. |
| [line 166](../../apps/letfs/internal/filesystem/deletion.go:166) | `deletionLeaves` | Keep indexed branch/leaf traversal and bounded 64 removal; descent/sibling/scope leaf queries measured. |
| [line 209](../../apps/letfs/internal/filesystem/deletion.go:209) | `DeletionBatch` | Keep indexed branch/leaf traversal and bounded 64 removal; descent/sibling/scope leaf queries measured. |
| [line 218](../../apps/letfs/internal/filesystem/deletion.go:218) | `DeletionBatch` | Keep indexed branch/leaf traversal and bounded 64 removal; descent/sibling/scope leaf queries measured. |
| [line 229](../../apps/letfs/internal/filesystem/deletion.go:229) | `DeletionBatch` | Keep indexed branch/leaf traversal and bounded 64 removal; descent/sibling/scope leaf queries measured. |
| [line 241](../../apps/letfs/internal/filesystem/deletion.go:241) | `DeletionBatch` | Keep indexed branch/leaf traversal and bounded 64 removal; descent/sibling/scope leaf queries measured. |
| [line 243](../../apps/letfs/internal/filesystem/deletion.go:243) | `DeletionBatch` | Keep indexed branch/leaf traversal and bounded 64 removal; descent/sibling/scope leaf queries measured. |
| [line 249](../../apps/letfs/internal/filesystem/deletion.go:249) | `DeletionBatch` | Keep indexed branch/leaf traversal and bounded 64 removal; descent/sibling/scope leaf queries measured. |
| [line 270](../../apps/letfs/internal/filesystem/deletion.go:270) | `ListScopesForDeletion` | Keep filesystem/scopes_by_filesystem access and lifecycle lock/empty-tree checks. |
| [line 274](../../apps/letfs/internal/filesystem/deletion.go:274) | `ListScopesForDeletion` | Keep filesystem/scopes_by_filesystem access and lifecycle lock/empty-tree checks. |
| [line 296](../../apps/letfs/internal/filesystem/deletion.go:296) | `RemoveFilesystem` | Keep filesystem/scopes_by_filesystem access and lifecycle lock/empty-tree checks. |
| [line 311](../../apps/letfs/internal/filesystem/deletion.go:311) | `DeleteScopeData` | Keep indexed identity lookup/mutation and its state/ownership guards. |

## apps/letfs/internal/filesystem/download.go

| Source | Owner | Disposition |
|---|---|---|
| [line 46](../../apps/letfs/internal/filesystem/download.go:46) | `GetDownload` | Keep indexed identity lookup/mutation and its state/ownership guards. |

## apps/letfs/internal/filesystem/enrichment.go

| Source | Owner | Disposition |
|---|---|---|
| [line 87](../../apps/letfs/internal/filesystem/enrichment.go:87) | `inventory` | Keep real bounded processing subtree inventory; complete projection/payload query measured. |
| [line 297](../../apps/letfs/internal/filesystem/enrichment.go:297) | `CompleteEnrichment` | Keep bounded manifest PK/ANY reads and per-node guarded publication; no measured scan bottleneck justifies batch redesign. |
| [line 321](../../apps/letfs/internal/filesystem/enrichment.go:321) | `CompleteEnrichment` | Keep bounded manifest PK/ANY reads and per-node guarded publication; no measured scan bottleneck justifies batch redesign. |
| [line 331](../../apps/letfs/internal/filesystem/enrichment.go:331) | `CompleteEnrichment` | Keep bounded manifest PK/ANY reads and per-node guarded publication; no measured scan bottleneck justifies batch redesign. |
| [line 337](../../apps/letfs/internal/filesystem/enrichment.go:337) | `CompleteEnrichment` | Keep bounded manifest PK/ANY reads and per-node guarded publication; no measured scan bottleneck justifies batch redesign. |
| [line 350](../../apps/letfs/internal/filesystem/enrichment.go:350) | `CompleteEnrichment` | Keep bounded manifest PK/ANY reads and per-node guarded publication; no measured scan bottleneck justifies batch redesign. |
| [line 354](../../apps/letfs/internal/filesystem/enrichment.go:354) | `CompleteEnrichment` | Keep bounded manifest PK/ANY reads and per-node guarded publication; no measured scan bottleneck justifies batch redesign. |
| [line 358](../../apps/letfs/internal/filesystem/enrichment.go:358) | `CompleteEnrichment` | Keep bounded manifest PK/ANY reads and per-node guarded publication; no measured scan bottleneck justifies batch redesign. |
| [line 375](../../apps/letfs/internal/filesystem/enrichment.go:375) | `CompleteEnrichment` | Keep bounded manifest PK/ANY reads and per-node guarded publication; no measured scan bottleneck justifies batch redesign. |
| [line 383](../../apps/letfs/internal/filesystem/enrichment.go:383) | `CompleteEnrichment` | Keep bounded manifest PK/ANY reads and per-node guarded publication; no measured scan bottleneck justifies batch redesign. |

## apps/letfs/internal/filesystem/index_cleanup.go

| Source | Owner | Disposition |
|---|---|---|
| [line 17](../../apps/letfs/internal/filesystem/index_cleanup.go:17) | `IndexDeletionCandidates` | Keep due selection/PK anti-join: dense-ready 90k tombstones measured; no added mechanism/index justified. |
| [line 35](../../apps/letfs/internal/filesystem/index_cleanup.go:35) | `DeleteObsoleteIndex` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 47](../../apps/letfs/internal/filesystem/index_cleanup.go:47) | `DeleteObsoleteIndex` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 68](../../apps/letfs/internal/filesystem/index_cleanup.go:68) | `DeleteObsoleteIndex` | Keep existing scoped/identity access; retain transaction/state checks. |

## apps/letfs/internal/filesystem/indexing.go

| Source | Owner | Disposition |
|---|---|---|
| [line 73](../../apps/letfs/internal/filesystem/indexing.go:73) | `PrepareIndex` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 106](../../apps/letfs/internal/filesystem/indexing.go:106) | `CompleteIndex` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 136](../../apps/letfs/internal/filesystem/indexing.go:136) | `FailIndex` | Keep indexed identity lookup/mutation and its state/ownership guards. |

## apps/letfs/internal/filesystem/maintenance.go

| Source | Owner | Disposition |
|---|---|---|
| [line 19](../../apps/letfs/internal/filesystem/maintenance.go:19) | `expireUpload` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 36](../../apps/letfs/internal/filesystem/maintenance.go:36) | `ExpireUploads` | Keep pending/multipart predicates and existing indexes; measured fast. No extra expiry index. |
| [line 54](../../apps/letfs/internal/filesystem/maintenance.go:54) | `ExpireUploads` | Keep pending/multipart predicates and existing indexes; measured fast. No extra expiry index. |
| [line 80](../../apps/letfs/internal/filesystem/maintenance.go:80) | `DeleteObjects` | Keep current due/backlog and object/candidate PK/unique probes; due/claim measured fast, including many deleted tombstones. |
| [line 120](../../apps/letfs/internal/filesystem/maintenance.go:120) | `DeleteObjects` | Keep current due/backlog and object/candidate PK/unique probes; due/claim measured fast, including many deleted tombstones. |
| [line 144](../../apps/letfs/internal/filesystem/maintenance.go:144) | `claimObjectDeletion` | Keep current due/backlog and object/candidate PK/unique probes; due/claim measured fast, including many deleted tombstones. |
| [line 147](../../apps/letfs/internal/filesystem/maintenance.go:147) | `claimObjectDeletion` | Keep current due/backlog and object/candidate PK/unique probes; due/claim measured fast, including many deleted tombstones. |
| [line 155](../../apps/letfs/internal/filesystem/maintenance.go:155) | `claimObjectDeletion` | Keep current due/backlog and object/candidate PK/unique probes; due/claim measured fast, including many deleted tombstones. |

## apps/letfs/internal/filesystem/node_writes.go

| Source | Owner | Disposition |
|---|---|---|
| [line 89](../../apps/letfs/internal/filesystem/node_writes.go:89) | `usage` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 102](../../apps/letfs/internal/filesystem/node_writes.go:102) | `addNodes` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 114](../../apps/letfs/internal/filesystem/node_writes.go:114) | `bump` | Keep bounded identity batch using existing PK/unique indexes. |
| [line 120](../../apps/letfs/internal/filesystem/node_writes.go:120) | `fetch` | Keep existing scoped/identity access; retain transaction/state checks. |
| [line 126](../../apps/letfs/internal/filesystem/node_writes.go:126) | `depth` | Keep structural guards for actual moves; indexed ancestry/subtree work. Same-parent rename already skips them. |
| [line 176](../../apps/letfs/internal/filesystem/node_writes.go:176) | `CreateNode` | Keep receipt PK lookup/upsert; preserve replay/conflict/expiry checks. |
| [line 226](../../apps/letfs/internal/filesystem/node_writes.go:226) | `CreateNode` | Keep atomic publication/upsert and existing FK/unique checks; PK or bounded input identities. |
| [line 234](../../apps/letfs/internal/filesystem/node_writes.go:234) | `CreateNode` | Keep atomic publication/upsert and existing FK/unique checks; PK or bounded input identities. |
| [line 255](../../apps/letfs/internal/filesystem/node_writes.go:255) | `CreateNode` | Keep atomic publication/upsert and existing FK/unique checks; PK or bounded input identities. |
| [line 349](../../apps/letfs/internal/filesystem/node_writes.go:349) | `UpdateNode` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 379](../../apps/letfs/internal/filesystem/node_writes.go:379) | `cycle` | Keep structural guards for actual moves; indexed ancestry/subtree work. Same-parent rename already skips them. |
| [line 401](../../apps/letfs/internal/filesystem/node_writes.go:401) | `validateMove` | Keep structural guards for actual moves; indexed ancestry/subtree work. Same-parent rename already skips them. |
| [line 463](../../apps/letfs/internal/filesystem/node_writes.go:463) | `ReplaceContent` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 467](../../apps/letfs/internal/filesystem/node_writes.go:467) | `ReplaceContent` | Keep indexed identity lookup/mutation and its state/ownership guards. |

## apps/letfs/internal/filesystem/nodes.go

| Source | Owner | Disposition |
|---|---|---|
| [line 119](../../apps/letfs/internal/filesystem/nodes.go:119) | `openSessionState` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 129](../../apps/letfs/internal/filesystem/nodes.go:129) | `openSessionState` | Keep existing scoped/identity access; retain transaction/state checks. |
| [line 133](../../apps/letfs/internal/filesystem/nodes.go:133) | `openSessionState` | Keep existing scoped/identity access; retain transaction/state checks. |
| [line 148](../../apps/letfs/internal/filesystem/nodes.go:148) | `ValidateScope` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 163](../../apps/letfs/internal/filesystem/nodes.go:163) | `GetFilesystem` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 287](../../apps/letfs/internal/filesystem/nodes.go:287) | `ListNodes` | Keep indexed keyset traversal; no offset or pagination engine. |

## apps/letfs/internal/filesystem/paths.go

| Source | Owner | Disposition |
|---|---|---|
| [line 117](../../apps/letfs/internal/filesystem/paths.go:117) | `resolve` | Keep previously measured index-visible recursive resolver in custom/generic plans. |

## apps/letfs/internal/filesystem/processing.go

| Source | Owner | Disposition |
|---|---|---|
| [line 31](../../apps/letfs/internal/filesystem/processing.go:31) | `processingSession` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 42](../../apps/letfs/internal/filesystem/processing.go:42) | `currentProcessing` | Keep existing scoped/identity access; retain transaction/state checks. |
| [line 110](../../apps/letfs/internal/filesystem/processing.go:110) | `failProcessing` | Keep indexed identity lookup/mutation and its state/ownership guards. |

## apps/letfs/internal/filesystem/processing_control.go

| Source | Owner | Disposition |
|---|---|---|
| [line 42](../../apps/letfs/internal/filesystem/processing_control.go:42) | `GetProcessing` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 79](../../apps/letfs/internal/filesystem/processing_control.go:79) | `Reprocess` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 103](../../apps/letfs/internal/filesystem/processing_control.go:103) | `Reprocess` | Keep receipt PK lookup/upsert; preserve replay/conflict/expiry checks. |
| [line 124](../../apps/letfs/internal/filesystem/processing_control.go:124) | `Reprocess` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 132](../../apps/letfs/internal/filesystem/processing_control.go:132) | `Reprocess` | Keep atomic publication/upsert and existing FK/unique checks; PK or bounded input identities. |
| [line 154](../../apps/letfs/internal/filesystem/processing_control.go:154) | `PendingProcessing` | Keep partial processing_dispatch + PK revalidation; dispatcher measured. |
| [line 158](../../apps/letfs/internal/filesystem/processing_control.go:158) | `ProcessingCandidates` | Keep partial processing_dispatch + PK revalidation; dispatcher measured. |
| [line 173](../../apps/letfs/internal/filesystem/processing_control.go:173) | `ReconcileProcessing` | Keep partial processing_dispatch + PK revalidation; dispatcher measured. |

## apps/letfs/internal/filesystem/processing_publication.go

| Source | Owner | Disposition |
|---|---|---|
| [line 120](../../apps/letfs/internal/filesystem/processing_publication.go:120) | `CompleteParse` | Keep source/upload PK/ANY selection and existing JSON set-based publication; row/index write cost measured by batch controls. |
| [line 178](../../apps/letfs/internal/filesystem/processing_publication.go:178) | `CompleteParse` | Keep source/upload PK/ANY selection and existing JSON set-based publication; row/index write cost measured by batch controls. |
| [line 213](../../apps/letfs/internal/filesystem/processing_publication.go:213) | `CompleteParse` | Keep source/upload PK/ANY selection and existing JSON set-based publication; row/index write cost measured by batch controls. |
| [line 218](../../apps/letfs/internal/filesystem/processing_publication.go:218) | `CompleteParse` | Keep source/upload PK/ANY selection and existing JSON set-based publication; row/index write cost measured by batch controls. |
| [line 223](../../apps/letfs/internal/filesystem/processing_publication.go:223) | `CompleteParse` | Keep source/upload PK/ANY selection and existing JSON set-based publication; row/index write cost measured by batch controls. |
| [line 227](../../apps/letfs/internal/filesystem/processing_publication.go:227) | `CompleteParse` | Keep source/upload PK/ANY selection and existing JSON set-based publication; row/index write cost measured by batch controls. |

## apps/letfs/internal/filesystem/processing_uploads.go

| Source | Owner | Disposition |
|---|---|---|
| [line 159](../../apps/letfs/internal/filesystem/processing_uploads.go:159) | `insertProcessingOutput` | Keep atomic publication/upsert and existing FK/unique checks; PK or bounded input identities. |
| [line 248](../../apps/letfs/internal/filesystem/processing_uploads.go:248) | `WriteOutputBytes` | Keep indexed identity lookup/mutation and its state/ownership guards. |

## apps/letfs/internal/filesystem/provisioning.go

| Source | Owner | Disposition |
|---|---|---|
| [line 102](../../apps/letfs/internal/filesystem/provisioning.go:102) | `receipt` | Keep atomic publication/upsert and existing FK/unique checks; PK or bounded input identities. |
| [line 117](../../apps/letfs/internal/filesystem/provisioning.go:117) | `filesystemForUpdate` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 141](../../apps/letfs/internal/filesystem/provisioning.go:141) | `CreateFilesystem` | Keep atomic publication/upsert and existing FK/unique checks; PK or bounded input identities. |
| [line 199](../../apps/letfs/internal/filesystem/provisioning.go:199) | `CreateScopes` | Keep atomic publication/upsert and existing FK/unique checks; PK or bounded input identities. |
| [line 204](../../apps/letfs/internal/filesystem/provisioning.go:204) | `CreateScopes` | Keep atomic publication/upsert and existing FK/unique checks; PK or bounded input identities. |
| [line 213](../../apps/letfs/internal/filesystem/provisioning.go:213) | `CreateScopes` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 228](../../apps/letfs/internal/filesystem/provisioning.go:228) | `PruneReceipts` | Keep expiry-index + PK deletion, bounded 100; measured. |
| [line 238](../../apps/letfs/internal/filesystem/provisioning.go:238) | `pruneDeletedStorage` | Keep state-filtered PK-order page (64); 1000-resource sparse-state controls measured. |
| [line 250](../../apps/letfs/internal/filesystem/provisioning.go:250) | `pruneDeletedStorage` | Optimize with uploads_by_scope, including terminal states and FK/existence probes. |
| [line 253](../../apps/letfs/internal/filesystem/provisioning.go:253) | `pruneDeletedStorage` | Optimize with uploads_by_scope, including terminal states and FK/existence probes. |
| [line 257](../../apps/letfs/internal/filesystem/provisioning.go:257) | `pruneDeletedStorage` | Keep state-filtered PK-order page (64); 1000-resource sparse-state controls measured. |
| [line 269](../../apps/letfs/internal/filesystem/provisioning.go:269) | `pruneDeletedStorage` | Optimize with full object_deletions_by_filesystem; backlog partial index excludes settled rows. |
| [line 272](../../apps/letfs/internal/filesystem/provisioning.go:272) | `pruneDeletedStorage` | Optimize with full object_deletions_by_filesystem; backlog partial index excludes settled rows. |

## apps/letfs/internal/filesystem/scope_move.go

| Source | Owner | Disposition |
|---|---|---|
| [line 23](../../apps/letfs/internal/filesystem/scope_move.go:23) | `transferTree` | Keep real subtree output and atomic scope/parent/payload/generation checks; 11k-node select measured, no path materialization. |
| [line 54](../../apps/letfs/internal/filesystem/scope_move.go:54) | `transferTree` | Keep real subtree output and atomic scope/parent/payload/generation checks; 11k-node select measured, no path materialization. |
| [line 104](../../apps/letfs/internal/filesystem/scope_move.go:104) | `transferTree` | Keep real subtree output and atomic scope/parent/payload/generation checks; 11k-node select measured, no path materialization. |
| [line 106](../../apps/letfs/internal/filesystem/scope_move.go:106) | `transferTree` | Keep real subtree output and atomic scope/parent/payload/generation checks; 11k-node select measured, no path materialization. |
| [line 113](../../apps/letfs/internal/filesystem/scope_move.go:113) | `transferTree` | Keep real subtree output and atomic scope/parent/payload/generation checks; 11k-node select measured, no path materialization. |

## apps/letfs/internal/filesystem/search.go

| Source | Owner | Disposition |
|---|---|---|
| [line 162](../../apps/letfs/internal/filesystem/search.go:162) | `searchRoot` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 212](../../apps/letfs/internal/filesystem/search.go:212) | `SearchFiles` | Keep filename keyset behavior and previously measured metadata-carrying traversal; selected-subtree substring scan remains. |

## apps/letfs/internal/filesystem/semantic_search.go

| Source | Owner | Disposition |
|---|---|---|
| [line 82](../../apps/letfs/internal/filesystem/semantic_search.go:82) | `hydrateSearch` | Keep previously measured candidate-upward ancestry/current-generation hydration; now used by bounded semantic top-K. |
| [line 117](../../apps/letfs/internal/filesystem/semantic_search.go:117) | `SemanticSearch` | Keep indexed identity lookup/mutation and its state/ownership guards. |

## apps/letfs/internal/filesystem/service.go

| Source | Owner | Disposition |
|---|---|---|
| [line 120](../../apps/letfs/internal/filesystem/service.go:120) | `DeleteFilesystem` | Keep indexed identity lookup/mutation and its state/ownership guards. |

## apps/letfs/internal/filesystem/trash.go

| Source | Owner | Disposition |
|---|---|---|
| [line 29](../../apps/letfs/internal/filesystem/trash.go:29) | `queueObject` | Keep atomic publication/upsert and existing FK/unique checks; PK or bounded input identities. |
| [line 40](../../apps/letfs/internal/filesystem/trash.go:40) | `trashEntry` | Keep existing scoped/identity access; retain transaction/state checks. |
| [line 75](../../apps/letfs/internal/filesystem/trash.go:75) | `ListTrash` | Keep indexed keyset traversal; no offset or pagination engine. |
| [line 129](../../apps/letfs/internal/filesystem/trash.go:129) | `TrashNode` | Keep atomic publication/upsert and existing FK/unique checks; PK or bounded input identities. |
| [line 133](../../apps/letfs/internal/filesystem/trash.go:133) | `TrashNode` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 214](../../apps/letfs/internal/filesystem/trash.go:214) | `RestoreTrash` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 222](../../apps/letfs/internal/filesystem/trash.go:222) | `RestoreTrash` | Keep indexed identity lookup/mutation and its state/ownership guards. |

## apps/letfs/internal/filesystem/upload_publication.go

| Source | Owner | Disposition |
|---|---|---|
| [line 87](../../apps/letfs/internal/filesystem/upload_publication.go:87) | `completeUpload` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 96](../../apps/letfs/internal/filesystem/upload_publication.go:96) | `completeUpload` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 180](../../apps/letfs/internal/filesystem/upload_publication.go:180) | `publishUpload` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 210](../../apps/letfs/internal/filesystem/upload_publication.go:210) | `publishUpload` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 216](../../apps/letfs/internal/filesystem/upload_publication.go:216) | `publishUpload` | Keep atomic publication/upsert and existing FK/unique checks; PK or bounded input identities. |
| [line 227](../../apps/letfs/internal/filesystem/upload_publication.go:227) | `publishUpload` | Keep atomic publication/upsert and existing FK/unique checks; PK or bounded input identities. |
| [line 247](../../apps/letfs/internal/filesystem/upload_publication.go:247) | `publishUpload` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 255](../../apps/letfs/internal/filesystem/upload_publication.go:255) | `completeUploadReceipt` | Keep existing scoped/identity access; retain transaction/state checks. |
| [line 260](../../apps/letfs/internal/filesystem/upload_publication.go:260) | `queueCandidate` | Keep atomic publication/upsert and existing FK/unique checks; PK or bounded input identities. |
| [line 287](../../apps/letfs/internal/filesystem/upload_publication.go:287) | `abortUpload` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 313](../../apps/letfs/internal/filesystem/upload_publication.go:313) | `abortMultipart` | Keep indexed identity lookup/mutation and its state/ownership guards. |

## apps/letfs/internal/filesystem/uploads.go

| Source | Owner | Disposition |
|---|---|---|
| [line 101](../../apps/letfs/internal/filesystem/uploads.go:101) | `loadUpload` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 174](../../apps/letfs/internal/filesystem/uploads.go:174) | `uploadTarget` | Keep existing scoped/identity access; retain transaction/state checks. |
| [line 192](../../apps/letfs/internal/filesystem/uploads.go:192) | `uploadCapacity` | Optimize user outstanding partial scope index; avoid scanning processing uploads for user-upload admission. Backlog count retains existing partial index. |
| [line 244](../../apps/letfs/internal/filesystem/uploads.go:244) | `CreateUpload` | Keep receipt PK lookup/upsert; preserve replay/conflict/expiry checks. |
| [line 295](../../apps/letfs/internal/filesystem/uploads.go:295) | `CreateUpload` | Keep atomic publication/upsert and existing FK/unique checks; PK or bounded input identities. |
| [line 305](../../apps/letfs/internal/filesystem/uploads.go:305) | `CreateUpload` | Keep atomic publication/upsert and existing FK/unique checks; PK or bounded input identities. |
| [line 366](../../apps/letfs/internal/filesystem/uploads.go:366) | `recordCapability` | Keep indexed identity lookup/mutation and its state/ownership guards. |
| [line 432](../../apps/letfs/internal/filesystem/uploads.go:432) | `saveMultipart` | Keep indexed identity lookup/mutation and its state/ownership guards. |

## apps/letfs/internal/temporal/maintenance.go

| Source | Owner | Disposition |
|---|---|---|
| [line 68](../../apps/letfs/internal/temporal/maintenance.go:68) | `reconcileResources` | Keep state-filtered resource pages (64); sparse-state controls measured, no speculative lifecycle indexes. |
| [line 81](../../apps/letfs/internal/temporal/maintenance.go:81) | `reconcileResources` | Keep state-filtered resource pages (64); sparse-state controls measured, no speculative lifecycle indexes. |
