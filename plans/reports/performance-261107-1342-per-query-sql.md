# Per-query SQL measurements

Measured **233/233** source execution sites. Failed probes: 1 (excluded from successful timings).

Each EXPLAIN sample is one warm-up followed by three rolled-back runs; the table shows the range of their medians across observed SQL variants and workloads. These are PostgreSQL execution times, excluding planning, network, pool waits and API work. Control statements use actual client elapsed time and are labelled separately. Rows means root output or mutation input rows from the plan; it is not a universal affected-row count. An aggregate/EXISTS can return one row without matching underlying data.

Integration tests supply real application SQL and bound parameters on isolated fixtures. Supplemental cases use verbatim inventoried SQL on explicitly seeded fixtures. Most integration fixtures are small; these timings alone do not prove large-data or concurrent performance. All observed workloads, SQL, parameter metadata and plans are in `/home/qninh/projects/openlet/.local/sql-performance/per-query/summary.json` and `queries-*.jsonl`. Bound parameter values are not persisted as separate fields, though PostgreSQL plans can embed fixture constants.

## Findings and validation

- Inventory reconciliation: Account **9/9**, Workspace **43/43**, LetFS **181/181**. There are **238 observed SQL variants** at **233 sites**, comprising 231 data-query sites and two savepoint control sites. No site is missing; no data site has only zero work rows under the plan metric above. This does not enumerate every possible parameter combination or prove every EXISTS predicate returned true.
- Final evidence includes **661 EXPLAIN observations** (one warm-up plus three recorded runs each) and **14 control observations**. Raw records preserve every workload rather than selecting the fastest result. A single SQLSTATE `23505` probe is from the expected restore/name-conflict case in `TestIntegrationReplacementAndTrashPreserveAccountingAndCleanup`; it is retained separately and excluded from successful timings. All three instrumented application suites passed.
- Supplemental fixtures: Account has 100,000 accounts. Workspace has 10,001 workspaces, 100,100 members, 10,001 invitations and 10,000 receipts. LetFS has 100,002 nodes, 100,001 file records, 100,001 uploads and 100,103 receipts; most files are siblings under one root, with a two-node file/artifact subtree. Most other measurements come from small integration fixtures. Existing [large-workload before/after measurements](performance-261107-1310-semantic-sql-audit.md) remain separate evidence.
- Largest new cost: `artifacts.go:fenceTrashed` takes **44.716 ms** for that two-node subtree in the 100,000-file sibling fixture. Its recursive plan scans all nodes twice and hashes all file records because cardinality is overestimated. This is a measured remaining hotspot, not evidence that all SQL is optimal.
- Three LATERAL/optimizer-fence experiments were rejected. In a separate equivalent comparison on a pinned, CPU/memory-bounded PostgreSQL 18.6 fixture, the original was **49.745 ms**, versus **102.515 / 178.932 / 177.126 ms** for the candidates, with identical complete result digests for the small subtree. A subsequent whole-tree candidate stress probe exceeded the runner's 120-second deadline; its container was removed. No candidate SQL, planner setting or new index was retained. Details: `.local/sql-performance/fence-shapes.{py,json,log}`.
- Other maximum per-site medians over observed fixtures: batched `removeNodes` **1.660 ms** for 64 nodes; Workspace receipt pruning **1.256 ms** for 100 receipts. These workloads differ and are not an API latency comparison. No production SQL was changed in this measurement task.
- Verification: rollback self-checks cover insert/update/delete, an existing parent transaction, a constraint error, and upsert/update/do-nothing row accounting. Supplemental cases assert positive work rows. Final helper changes were checked again with the supplemental fixture suite and an actual traced Account integration test. Harness Python tests and formatting/lint checks passed. Owned experiment containers were stopped; user containers were not touched.

| Source | Function | SQL variants | Median ms range | Rows range | Measurement |
|---|---|---:|---:|---:|---|
| [apps/account/internal/account/relations.go:24](../../apps/account/internal/account/relations.go#L24) | SyncRelationships | 1 | 0.007–0.009 | 1–1 | explain_analyze |
| [apps/account/internal/account/relations.go:65](../../apps/account/internal/account/relations.go#L65) | RelationshipIDs | 1 | 0.034–0.034 | 100–100 | explain_analyze |
| [apps/account/internal/account/service.go:38](../../apps/account/internal/account/service.go#L38) | GetOnboarding | 1 | 0.011–0.011 | 1–1 | supplemental_explain_analyze |
| [apps/account/internal/account/store.go:49](../../apps/account/internal/account/store.go#L49) | EnsureAccount | 1 | 0.041–0.089 | 1–1 | explain_analyze |
| [apps/account/internal/account/store.go:68](../../apps/account/internal/account/store.go#L68) | CreateManaged | 1 | 0.082–0.082 | 1–1 | explain_analyze |
| [apps/account/internal/account/store.go:82](../../apps/account/internal/account/store.go#L82) | Profile | 1 | 0.006–0.007 | 1–1 | explain_analyze |
| [apps/account/internal/account/store.go:93](../../apps/account/internal/account/store.go#L93) | UpdateProfile | 1 | 0.036–0.041 | 1–1 | explain_analyze |
| [apps/account/internal/account/store.go:104](../../apps/account/internal/account/store.go#L104) | Summaries | 1 | 0.007–0.014 | 1–2 | explain_analyze |
| [apps/account/internal/account/store.go:121](../../apps/account/internal/account/store.go#L121) | Subject | 1 | 0.005–0.005 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/authorization.go:41](../../apps/workspace/internal/workspace/authorization.go#L41) | lockAdmission | 1 | 0.009–0.010 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/deletion.go:25](../../apps/workspace/internal/workspace/deletion.go#L25) | MarkWorkspaceDeleting | 1 | 0.037–0.037 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/deletion.go:40](../../apps/workspace/internal/workspace/deletion.go#L40) | RemoveWorkspace | 1 | 0.009–0.009 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/deletion.go:50](../../apps/workspace/internal/workspace/deletion.go#L50) | RemoveWorkspace | 1 | 0.010–0.064 | 0–101 | explain_analyze, supplemental_explain_analyze |
| [apps/workspace/internal/workspace/deletion.go:53](../../apps/workspace/internal/workspace/deletion.go#L53) | RemoveWorkspace | 1 | 0.040–0.040 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/invitations.go:57](../../apps/workspace/internal/workspace/invitations.go#L57) | Invite | 1 | 0.007–0.041 | 0–1 | explain_analyze, supplemental_explain_analyze |
| [apps/workspace/internal/workspace/invitations.go:60](../../apps/workspace/internal/workspace/invitations.go#L60) | Invite | 1 | 0.005–0.008 | 0–1 | explain_analyze, supplemental_explain_analyze |
| [apps/workspace/internal/workspace/invitations.go:77](../../apps/workspace/internal/workspace/invitations.go#L77) | Invite | 1 | 0.062–0.062 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/invitations.go:87](../../apps/workspace/internal/workspace/invitations.go#L87) | Invitations | 1 | 0.022–0.022 | 51–51 | supplemental_explain_analyze |
| [apps/workspace/internal/workspace/invitations.go:115](../../apps/workspace/internal/workspace/invitations.go#L115) | RevokeInvite | 1 | 0.063–0.063 | 1–1 | supplemental_explain_analyze |
| [apps/workspace/internal/workspace/invitations.go:131](../../apps/workspace/internal/workspace/invitations.go#L131) | AdmitInvitation | 1 | 0.006–0.006 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/maintenance.go:6](../../apps/workspace/internal/workspace/maintenance.go#L6) | PruneReceipts | 1 | 1.256–1.256 | 100–100 | supplemental_explain_analyze |
| [apps/workspace/internal/workspace/membership.go:20](../../apps/workspace/internal/workspace/membership.go#L20) | applyMembership | 1 | 0.011–0.012 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/membership.go:32](../../apps/workspace/internal/workspace/membership.go#L32) | applyMembership | 1 | 0.005–0.007 | 0–1 | explain_analyze |
| [apps/workspace/internal/workspace/membership.go:48](../../apps/workspace/internal/workspace/membership.go#L48) | applyMembership | 1 | 0.010–0.010 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/membership.go:64](../../apps/workspace/internal/workspace/membership.go#L64) | applyMembership | 1 | 0.011–0.013 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/membership.go:70](../../apps/workspace/internal/workspace/membership.go#L70) | applyMembership | 1 | 0.036–0.041 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/membership.go:75](../../apps/workspace/internal/workspace/membership.go#L75) | applyMembership | 1 | 0.039–0.039 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/membership.go:84](../../apps/workspace/internal/workspace/membership.go#L84) | applyMembership | 1 | 0.031–0.031 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/membership.go:89](../../apps/workspace/internal/workspace/membership.go#L89) | applyMembership | 1 | 0.030–0.030 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/mutation_receipt.go:20](../../apps/workspace/internal/workspace/mutation_receipt.go#L20) | mutationApplied | 1 | 0.005–0.010 | 0–1 | explain_analyze |
| [apps/workspace/internal/workspace/mutation_receipt.go:40](../../apps/workspace/internal/workspace/mutation_receipt.go#L40) | saveMutationReceipt | 1 | 0.038–0.048 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/mutation_receipt.go:45](../../apps/workspace/internal/workspace/mutation_receipt.go#L45) | CompleteMutation | 1 | 0.019–0.025 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/relations.go:64](../../apps/workspace/internal/workspace/relations.go#L64) | PublishStorageRelationships | 1 | 0.006–0.007 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/relations.go:80](../../apps/workspace/internal/workspace/relations.go#L80) | RemoveRelationships | 1 | 0.007–0.007 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/relations.go:89](../../apps/workspace/internal/workspace/relations.go#L89) | RemoveRelationships | 1 | 0.006–0.006 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/relations.go:106](../../apps/workspace/internal/workspace/relations.go#L106) | RelationshipIDs | 1 | 0.007–0.007 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/relations.go:114](../../apps/workspace/internal/workspace/relations.go#L114) | RebuildWorkspaceRelationships | 1 | 0.005–0.005 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/relations.go:127](../../apps/workspace/internal/workspace/relations.go#L127) | RebuildWorkspaceRelationships | 1 | 0.030–0.030 | 100–100 | explain_analyze |
| [apps/workspace/internal/workspace/relations.go:171](../../apps/workspace/internal/workspace/relations.go#L171) | ChangeScopeAccess | 1 | 0.009–0.009 | 1–1 | supplemental_explain_analyze |
| [apps/workspace/internal/workspace/relations.go:191](../../apps/workspace/internal/workspace/relations.go#L191) | UpdateScopeAccess | 1 | 0.008–0.008 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/service.go:244](../../apps/workspace/internal/workspace/service.go#L244) | AcceptInvitation | 1 | 0.006–0.006 | 1–1 | supplemental_explain_analyze |
| [apps/workspace/internal/workspace/store.go:106](../../apps/workspace/internal/workspace/store.go#L106) | getInTransaction | 1 | 0.011–0.013 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/store.go:109](../../apps/workspace/internal/workspace/store.go#L109) | Get | 1 | 0.012–0.023 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/store.go:114](../../apps/workspace/internal/workspace/store.go#L114) | FindCreation | 1 | 0.007–0.008 | 0–1 | explain_analyze |
| [apps/workspace/internal/workspace/store.go:137](../../apps/workspace/internal/workspace/store.go#L137) | SaveWorkspace | 1 | 0.002–0.003 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/store.go:142](../../apps/workspace/internal/workspace/store.go#L142) | SaveWorkspace | 1 | 0.005–0.008 | 0–1 | explain_analyze |
| [apps/workspace/internal/workspace/store.go:152](../../apps/workspace/internal/workspace/store.go#L152) | SaveWorkspace | 1 | 0.036–0.042 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/store.go:155](../../apps/workspace/internal/workspace/store.go#L155) | SaveWorkspace | 1 | 0.053–0.064 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/store.go:168](../../apps/workspace/internal/workspace/store.go#L168) | List | 1 | 0.020–0.020 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/store.go:175](../../apps/workspace/internal/workspace/store.go#L175) | Members | 1 | 0.023–0.023 | 51–51 | supplemental_explain_analyze |
| [apps/workspace/internal/workspace/store.go:183](../../apps/workspace/internal/workspace/store.go#L183) | Member | 1 | 0.006–0.006 | 1–1 | explain_analyze |
| [apps/workspace/internal/workspace/store.go:208](../../apps/workspace/internal/workspace/store.go#L208) | Update | 1 | 0.035–0.035 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/archive.go:101](../../apps/letfs/internal/filesystem/archive.go#L101) | preflightArchive | 1 | 0.039–0.039 | 4–4 | explain_analyze |
| [apps/letfs/internal/filesystem/archive.go:184](../../apps/letfs/internal/filesystem/archive.go#L184) | archivePayload | 1 | 0.032–0.032 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/artifacts.go:46](../../apps/letfs/internal/filesystem/artifacts.go#L46) | recordIntent | 1 | 0.049–0.062 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/artifacts.go:57](../../apps/letfs/internal/filesystem/artifacts.go#L57) | DiscardForests | 1 | 0.021–0.035 | 0–1 | explain_analyze |
| [apps/letfs/internal/filesystem/artifacts.go:96](../../apps/letfs/internal/filesystem/artifacts.go#L96) | discardForest | 1 | 0.010–0.010 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/artifacts.go:115](../../apps/letfs/internal/filesystem/artifacts.go#L115) | enqueueIndexDeletion | 1 | 0.006–0.029 | 0–1 | explain_analyze |
| [apps/letfs/internal/filesystem/artifacts.go:120](../../apps/letfs/internal/filesystem/artifacts.go#L120) | discardUploads | 1 | 0.009–0.059 | 0–1 | explain_analyze, supplemental_explain_analyze |
| [apps/letfs/internal/filesystem/artifacts.go:129](../../apps/letfs/internal/filesystem/artifacts.go#L129) | discardUploads | 1 | 0.007–0.073 | 0–1 | explain_analyze, supplemental_explain_analyze |
| [apps/letfs/internal/filesystem/artifacts.go:135](../../apps/letfs/internal/filesystem/artifacts.go#L135) | completeProcessingReceipt | 1 | 0.006–0.029 | 0–1 | explain_analyze, supplemental_explain_analyze |
| [apps/letfs/internal/filesystem/artifacts.go:142](../../apps/letfs/internal/filesystem/artifacts.go#L142) | invalidate | 1 | 0.008–0.013 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/artifacts.go:156](../../apps/letfs/internal/filesystem/artifacts.go#L156) | invalidate | 1 | 0.042–0.048 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/artifacts.go:162](../../apps/letfs/internal/filesystem/artifacts.go#L162) | invalidate | 1 | 0.007–0.040 | 0–1 | explain_analyze |
| [apps/letfs/internal/filesystem/artifacts.go:167](../../apps/letfs/internal/filesystem/artifacts.go#L167) | fenceTrashed | 1 | 0.016–44.716 | 0–2 | explain_analyze, supplemental_explain_analyze |
| [apps/letfs/internal/filesystem/artifacts.go:192](../../apps/letfs/internal/filesystem/artifacts.go#L192) | fenceTrashed | 1 | 0.042–0.042 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/backfill.go:21](../../apps/letfs/internal/filesystem/backfill.go#L21) | BackfillCandidates | 1 | 0.064–0.340 | 2–4 | explain_analyze |
| [apps/letfs/internal/filesystem/backfill.go:61](../../apps/letfs/internal/filesystem/backfill.go#L61) | AdmitBackfill | 1 | 0.012–0.012 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/backfill.go:72](../../apps/letfs/internal/filesystem/backfill.go#L72) | AdmitBackfill | 1 | 0.049–0.049 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/copy.go:74](../../apps/letfs/internal/filesystem/copy.go#L74) | selectCopy | 1 | 0.005–0.007 | 0–1 | explain_analyze |
| [apps/letfs/internal/filesystem/copy.go:83](../../apps/letfs/internal/filesystem/copy.go#L83) | selectCopy | 1 | 0.006–0.007 | 0–1 | explain_analyze |
| [apps/letfs/internal/filesystem/copy.go:126](../../apps/letfs/internal/filesystem/copy.go#L126) | prepareCopy | 1 | 0.006–0.008 | 0–1 | explain_analyze, supplemental_explain_analyze |
| [apps/letfs/internal/filesystem/copy.go:173](../../apps/letfs/internal/filesystem/copy.go#L173) | prepareCopy | 1 | 0.008–0.009 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/copy.go:196](../../apps/letfs/internal/filesystem/copy.go#L196) | prepareCopy | 1 | 0.006–0.006 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/copy.go:230](../../apps/letfs/internal/filesystem/copy.go#L230) | CopyNode | 1 | 0.020–0.021 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/copy_data.go:32](../../apps/letfs/internal/filesystem/copy_data.go#L32) | copySource | 1 | 0.006–0.006 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/copy_data.go:87](../../apps/letfs/internal/filesystem/copy_data.go#L87) | copyCommitted | 1 | 0.008–0.009 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/copy_data.go:96](../../apps/letfs/internal/filesystem/copy_data.go#L96) | releaseCopyCandidate | 1 | 0.014–0.019 | 0–1 | explain_analyze, supplemental_explain_analyze |
| [apps/letfs/internal/filesystem/copy_data.go:107](../../apps/letfs/internal/filesystem/copy_data.go#L107) | validateCopyCandidate | 1 | 0.012–0.012 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/copy_data.go:113](../../apps/letfs/internal/filesystem/copy_data.go#L113) | validateCopyCandidate | 1 | 0.008–0.008 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/copy_data.go:158](../../apps/letfs/internal/filesystem/copy_data.go#L158) | commitCopyItem | 1 | 0.005–0.005 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/copy_data.go:172](../../apps/letfs/internal/filesystem/copy_data.go#L172) | commitCopyItem | 1 | 0.059–0.059 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/copy_data.go:192](../../apps/letfs/internal/filesystem/copy_data.go#L192) | commitCopyItem | 1 | 0.036–0.036 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/copy_data.go:209](../../apps/letfs/internal/filesystem/copy_data.go#L209) | commitCopyItem | 1 | 0.032–0.055 | 0–0 | control_client_elapsed |
| [apps/letfs/internal/filesystem/copy_data.go:219](../../apps/letfs/internal/filesystem/copy_data.go#L219) | commitCopyItem | 1 | 0.047–0.075 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/copy_data.go:223](../../apps/letfs/internal/filesystem/copy_data.go#L223) | commitCopyItem | 1 | 0.046–0.047 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/copy_data.go:231](../../apps/letfs/internal/filesystem/copy_data.go#L231) | commitCopyItem | 1 | 0.049–0.049 | 0–0 | control_client_elapsed |
| [apps/letfs/internal/filesystem/copy_data.go:284](../../apps/letfs/internal/filesystem/copy_data.go#L284) | nextCopyItem | 1 | 0.004–0.007 | 0–1 | explain_analyze |
| [apps/letfs/internal/filesystem/copy_data.go:321](../../apps/letfs/internal/filesystem/copy_data.go#L321) | finishCopyFile | 1 | 0.006–0.006 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/copy_data.go:329](../../apps/letfs/internal/filesystem/copy_data.go#L329) | finishCopyFile | 1 | 0.009–0.062 | 0–1 | explain_analyze |
| [apps/letfs/internal/filesystem/copy_data.go:341](../../apps/letfs/internal/filesystem/copy_data.go#L341) | inScope | 1 | 0.007–0.007 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/deletion.go:42](../../apps/letfs/internal/filesystem/deletion.go#L42) | PrepareTrashPurge | 1 | 0.006–0.007 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/deletion.go:48](../../apps/letfs/internal/filesystem/deletion.go#L48) | PrepareTrashPurge | 1 | 0.022–0.022 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/deletion.go:66](../../apps/letfs/internal/filesystem/deletion.go#L66) | fenceScopeDeletion | 1 | 0.005–0.006 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/deletion.go:72](../../apps/letfs/internal/filesystem/deletion.go#L72) | fenceScopeDeletion | 1 | 0.025–0.033 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/deletion.go:75](../../apps/letfs/internal/filesystem/deletion.go#L75) | fenceScopeDeletion | 1 | 0.017–0.336 | 0–72 | explain_analyze |
| [apps/letfs/internal/filesystem/deletion.go:79](../../apps/letfs/internal/filesystem/deletion.go#L79) | fenceScopeDeletion | 1 | 0.009–0.079 | 0–1 | explain_analyze |
| [apps/letfs/internal/filesystem/deletion.go:85](../../apps/letfs/internal/filesystem/deletion.go#L85) | fenceScopeDeletion | 1 | 0.007–0.083 | 0–4 | explain_analyze |
| [apps/letfs/internal/filesystem/deletion.go:89](../../apps/letfs/internal/filesystem/deletion.go#L89) | fenceScopeDeletion | 1 | 0.010–0.036 | 0–2 | explain_analyze |
| [apps/letfs/internal/filesystem/deletion.go:102](../../apps/letfs/internal/filesystem/deletion.go#L102) | removeNodes | 1 | 0.009–0.046 | 0–64 | explain_analyze |
| [apps/letfs/internal/filesystem/deletion.go:123](../../apps/letfs/internal/filesystem/deletion.go#L123) | removeNodes | 1 | 0.015–0.086 | 0–1 | explain_analyze, supplemental_explain_analyze |
| [apps/letfs/internal/filesystem/deletion.go:128](../../apps/letfs/internal/filesystem/deletion.go#L128) | removeNodes | 1 | 0.006–0.013 | 0–1 | explain_analyze |
| [apps/letfs/internal/filesystem/deletion.go:131](../../apps/letfs/internal/filesystem/deletion.go#L131) | removeNodes | 1 | 0.006–0.027 | 0–1 | explain_analyze, supplemental_explain_analyze |
| [apps/letfs/internal/filesystem/deletion.go:134](../../apps/letfs/internal/filesystem/deletion.go#L134) | removeNodes | 1 | 0.151–1.660 | 1–64 | explain_analyze |
| [apps/letfs/internal/filesystem/deletion.go:155](../../apps/letfs/internal/filesystem/deletion.go#L155) | deletionLeaves | 1 | 0.020–0.023 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/deletion.go:166](../../apps/letfs/internal/filesystem/deletion.go#L166) | deletionLeaves | 1 | 0.017–0.020 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/deletion.go:209](../../apps/letfs/internal/filesystem/deletion.go#L209) | DeletionBatch | 1 | 0.006–0.007 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/deletion.go:218](../../apps/letfs/internal/filesystem/deletion.go#L218) | DeletionBatch | 1 | 0.017–0.056 | 1–64 | explain_analyze |
| [apps/letfs/internal/filesystem/deletion.go:229](../../apps/letfs/internal/filesystem/deletion.go#L229) | DeletionBatch | 1 | 0.025–0.072 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/deletion.go:241](../../apps/letfs/internal/filesystem/deletion.go#L241) | DeletionBatch | 1 | 0.007–0.010 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/deletion.go:243](../../apps/letfs/internal/filesystem/deletion.go#L243) | DeletionBatch | 1 | 0.007–0.010 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/deletion.go:249](../../apps/letfs/internal/filesystem/deletion.go#L249) | DeletionBatch | 1 | 0.038–0.047 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/deletion.go:270](../../apps/letfs/internal/filesystem/deletion.go#L270) | ListScopesForDeletion | 1 | 0.029–0.037 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/deletion.go:274](../../apps/letfs/internal/filesystem/deletion.go#L274) | ListScopesForDeletion | 1 | 0.009–0.009 | 1–3 | explain_analyze |
| [apps/letfs/internal/filesystem/deletion.go:296](../../apps/letfs/internal/filesystem/deletion.go#L296) | RemoveFilesystem | 1 | 0.033–0.045 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/deletion.go:311](../../apps/letfs/internal/filesystem/deletion.go#L311) | DeleteScopeData | 1 | 0.006–0.007 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/download.go:46](../../apps/letfs/internal/filesystem/download.go#L46) | GetDownload | 1 | 0.006–0.007 | 1–1 | explain_analyze, supplemental_explain_analyze |
| [apps/letfs/internal/filesystem/enrichment.go:87](../../apps/letfs/internal/filesystem/enrichment.go#L87) | inventory | 1 | 0.056–0.059 | 5–5 | explain_analyze |
| [apps/letfs/internal/filesystem/enrichment.go:297](../../apps/letfs/internal/filesystem/enrichment.go#L297) | CompleteEnrichment | 1 | 0.006–0.007 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/enrichment.go:321](../../apps/letfs/internal/filesystem/enrichment.go#L321) | CompleteEnrichment | 1 | 0.068–0.068 | 4–4 | explain_analyze |
| [apps/letfs/internal/filesystem/enrichment.go:331](../../apps/letfs/internal/filesystem/enrichment.go#L331) | CompleteEnrichment | 1 | 0.033–0.034 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/enrichment.go:337](../../apps/letfs/internal/filesystem/enrichment.go#L337) | CompleteEnrichment | 1 | 0.039–0.039 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/enrichment.go:350](../../apps/letfs/internal/filesystem/enrichment.go#L350) | CompleteEnrichment | 1 | 0.045–0.046 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/enrichment.go:354](../../apps/letfs/internal/filesystem/enrichment.go#L354) | CompleteEnrichment | 1 | 0.046–0.051 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/enrichment.go:358](../../apps/letfs/internal/filesystem/enrichment.go#L358) | CompleteEnrichment | 1 | 0.067–0.069 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/enrichment.go:375](../../apps/letfs/internal/filesystem/enrichment.go#L375) | CompleteEnrichment | 1 | 0.045–0.047 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/enrichment.go:383](../../apps/letfs/internal/filesystem/enrichment.go#L383) | CompleteEnrichment | 1 | 0.053–0.054 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/index_cleanup.go:17](../../apps/letfs/internal/filesystem/index_cleanup.go#L17) | IndexDeletionCandidates | 1 | 0.012–0.018 | 0–1 | explain_analyze |
| [apps/letfs/internal/filesystem/index_cleanup.go:35](../../apps/letfs/internal/filesystem/index_cleanup.go#L35) | DeleteObsoleteIndex | 1 | 0.005–0.005 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/index_cleanup.go:47](../../apps/letfs/internal/filesystem/index_cleanup.go#L47) | DeleteObsoleteIndex | 1 | 0.007–0.007 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/index_cleanup.go:68](../../apps/letfs/internal/filesystem/index_cleanup.go#L68) | DeleteObsoleteIndex | 1 | 0.020–0.020 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/indexing.go:73](../../apps/letfs/internal/filesystem/indexing.go#L73) | PrepareIndex | 1 | 0.046–0.046 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/indexing.go:106](../../apps/letfs/internal/filesystem/indexing.go#L106) | CompleteIndex | 1 | 0.045–0.046 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/indexing.go:136](../../apps/letfs/internal/filesystem/indexing.go#L136) | FailIndex | 1 | 0.009–0.047 | 0–1 | explain_analyze |
| [apps/letfs/internal/filesystem/maintenance.go:19](../../apps/letfs/internal/filesystem/maintenance.go#L19) | expireUpload | 1 | 0.070–0.070 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/maintenance.go:36](../../apps/letfs/internal/filesystem/maintenance.go#L36) | ExpireUploads | 1 | 0.008–0.013 | 0–3 | explain_analyze |
| [apps/letfs/internal/filesystem/maintenance.go:54](../../apps/letfs/internal/filesystem/maintenance.go#L54) | ExpireUploads | 1 | 0.005–0.008 | 0–1 | explain_analyze |
| [apps/letfs/internal/filesystem/maintenance.go:80](../../apps/letfs/internal/filesystem/maintenance.go#L80) | DeleteObjects | 1 | 0.006–0.011 | 0–4 | explain_analyze |
| [apps/letfs/internal/filesystem/maintenance.go:120](../../apps/letfs/internal/filesystem/maintenance.go#L120) | DeleteObjects | 1 | 0.031–0.031 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/maintenance.go:144](../../apps/letfs/internal/filesystem/maintenance.go#L144) | claimObjectDeletion | 1 | 0.010–0.010 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/maintenance.go:147](../../apps/letfs/internal/filesystem/maintenance.go#L147) | claimObjectDeletion | 1 | 0.044–0.044 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/maintenance.go:155](../../apps/letfs/internal/filesystem/maintenance.go#L155) | claimObjectDeletion | 1 | 0.034–0.034 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/node_writes.go:89](../../apps/letfs/internal/filesystem/node_writes.go#L89) | usage | 1 | 0.028–0.033 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/node_writes.go:102](../../apps/letfs/internal/filesystem/node_writes.go#L102) | addNodes | 1 | 0.029–0.035 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/node_writes.go:114](../../apps/letfs/internal/filesystem/node_writes.go#L114) | bump | 1 | 0.035–0.040 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/node_writes.go:120](../../apps/letfs/internal/filesystem/node_writes.go#L120) | fetch | 1 | 0.012–0.013 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/node_writes.go:126](../../apps/letfs/internal/filesystem/node_writes.go#L126) | depth | 1 | 0.023–0.032 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/node_writes.go:176](../../apps/letfs/internal/filesystem/node_writes.go#L176) | CreateNode | 1 | 0.006–0.011 | 0–1 | explain_analyze, supplemental_explain_analyze |
| [apps/letfs/internal/filesystem/node_writes.go:226](../../apps/letfs/internal/filesystem/node_writes.go#L226) | CreateNode | 1 | 0.074–0.095 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/node_writes.go:234](../../apps/letfs/internal/filesystem/node_writes.go#L234) | CreateNode | 1 | 0.062–0.070 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/node_writes.go:255](../../apps/letfs/internal/filesystem/node_writes.go#L255) | CreateNode | 1 | 0.020–0.025 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/node_writes.go:349](../../apps/letfs/internal/filesystem/node_writes.go#L349) | UpdateNode | 1 | 0.046–0.074 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/node_writes.go:379](../../apps/letfs/internal/filesystem/node_writes.go#L379) | cycle | 1 | 0.022–0.023 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/node_writes.go:401](../../apps/letfs/internal/filesystem/node_writes.go#L401) | validateMove | 1 | 0.023–0.026 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/node_writes.go:463](../../apps/letfs/internal/filesystem/node_writes.go#L463) | ReplaceContent | 1 | 0.052–0.057 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/node_writes.go:467](../../apps/letfs/internal/filesystem/node_writes.go#L467) | ReplaceContent | 1 | 0.033–0.033 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/nodes.go:119](../../apps/letfs/internal/filesystem/nodes.go#L119) | openSessionState | 1 | 0.006–0.006 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/nodes.go:129](../../apps/letfs/internal/filesystem/nodes.go#L129) | openSessionState | 2 | 0.006–0.036 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/nodes.go:133](../../apps/letfs/internal/filesystem/nodes.go#L133) | openSessionState | 2 | 0.006–0.018 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/nodes.go:148](../../apps/letfs/internal/filesystem/nodes.go#L148) | ValidateScope | 1 | 0.008–0.009 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/nodes.go:163](../../apps/letfs/internal/filesystem/nodes.go#L163) | GetFilesystem | 1 | 0.008–0.009 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/nodes.go:287](../../apps/letfs/internal/filesystem/nodes.go#L287) | ListNodes | 1 | 0.014–0.015 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/paths.go:117](../../apps/letfs/internal/filesystem/paths.go#L117) | resolve | 1 | 0.111–0.121 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/processing.go:31](../../apps/letfs/internal/filesystem/processing.go#L31) | processingSession | 1 | 0.005–0.007 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/processing.go:42](../../apps/letfs/internal/filesystem/processing.go#L42) | currentProcessing | 1 | 0.013–0.024 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/processing.go:110](../../apps/letfs/internal/filesystem/processing.go#L110) | failProcessing | 1 | 0.048–0.051 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/processing_control.go:42](../../apps/letfs/internal/filesystem/processing_control.go#L42) | GetProcessing | 1 | 0.006–0.006 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/processing_control.go:79](../../apps/letfs/internal/filesystem/processing_control.go#L79) | Reprocess | 1 | 0.015–0.015 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/processing_control.go:103](../../apps/letfs/internal/filesystem/processing_control.go#L103) | Reprocess | 1 | 0.007–0.009 | 0–1 | explain_analyze |
| [apps/letfs/internal/filesystem/processing_control.go:124](../../apps/letfs/internal/filesystem/processing_control.go#L124) | Reprocess | 1 | 0.006–0.006 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/processing_control.go:132](../../apps/letfs/internal/filesystem/processing_control.go#L132) | Reprocess | 1 | 0.021–0.021 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/processing_control.go:154](../../apps/letfs/internal/filesystem/processing_control.go#L154) | PendingProcessing | 1 | 0.014–0.017 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/processing_control.go:158](../../apps/letfs/internal/filesystem/processing_control.go#L158) | ProcessingCandidates | 1 | 0.025–0.034 | 0–1 | explain_analyze |
| [apps/letfs/internal/filesystem/processing_control.go:173](../../apps/letfs/internal/filesystem/processing_control.go#L173) | ReconcileProcessing | 1 | 0.010–0.020 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/processing_publication.go:120](../../apps/letfs/internal/filesystem/processing_publication.go#L120) | CompleteParse | 1 | 0.017–0.023 | 2–3 | explain_analyze |
| [apps/letfs/internal/filesystem/processing_publication.go:178](../../apps/letfs/internal/filesystem/processing_publication.go#L178) | CompleteParse | 1 | 0.007–0.007 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/processing_publication.go:213](../../apps/letfs/internal/filesystem/processing_publication.go#L213) | CompleteParse | 1 | 0.124–0.127 | 4–4 | explain_analyze |
| [apps/letfs/internal/filesystem/processing_publication.go:218](../../apps/letfs/internal/filesystem/processing_publication.go#L218) | CompleteParse | 1 | 0.086–0.097 | 2–3 | explain_analyze |
| [apps/letfs/internal/filesystem/processing_publication.go:223](../../apps/letfs/internal/filesystem/processing_publication.go#L223) | CompleteParse | 1 | 0.092–0.099 | 2–3 | explain_analyze |
| [apps/letfs/internal/filesystem/processing_publication.go:227](../../apps/letfs/internal/filesystem/processing_publication.go#L227) | CompleteParse | 1 | 0.042–0.052 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/processing_uploads.go:159](../../apps/letfs/internal/filesystem/processing_uploads.go#L159) | insertProcessingOutput | 1 | 0.092–0.097 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/processing_uploads.go:248](../../apps/letfs/internal/filesystem/processing_uploads.go#L248) | WriteOutputBytes | 1 | 0.062–0.074 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/provisioning.go:102](../../apps/letfs/internal/filesystem/provisioning.go#L102) | receipt | 1 | 0.019–0.026 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/provisioning.go:117](../../apps/letfs/internal/filesystem/provisioning.go#L117) | filesystemForUpdate | 1 | 0.012–0.013 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/provisioning.go:141](../../apps/letfs/internal/filesystem/provisioning.go#L141) | CreateFilesystem | 1 | 0.023–0.030 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/provisioning.go:199](../../apps/letfs/internal/filesystem/provisioning.go#L199) | CreateScopes | 1 | 0.049–0.065 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/provisioning.go:204](../../apps/letfs/internal/filesystem/provisioning.go#L204) | CreateScopes | 1 | 0.061–0.084 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/provisioning.go:213](../../apps/letfs/internal/filesystem/provisioning.go#L213) | CreateScopes | 1 | 0.005–0.007 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/provisioning.go:228](../../apps/letfs/internal/filesystem/provisioning.go#L228) | PruneReceipts | 1 | 0.017–0.395 | 0–100 | explain_analyze, supplemental_explain_analyze |
| [apps/letfs/internal/filesystem/provisioning.go:238](../../apps/letfs/internal/filesystem/provisioning.go#L238) | pruneDeletedStorage | 1 | 0.007–0.010 | 0–1 | explain_analyze |
| [apps/letfs/internal/filesystem/provisioning.go:250](../../apps/letfs/internal/filesystem/provisioning.go#L250) | pruneDeletedStorage | 1 | 0.011–0.011 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/provisioning.go:253](../../apps/letfs/internal/filesystem/provisioning.go#L253) | pruneDeletedStorage | 1 | 0.146–0.146 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/provisioning.go:257](../../apps/letfs/internal/filesystem/provisioning.go#L257) | pruneDeletedStorage | 1 | 0.007–0.008 | 0–1 | explain_analyze |
| [apps/letfs/internal/filesystem/provisioning.go:269](../../apps/letfs/internal/filesystem/provisioning.go#L269) | pruneDeletedStorage | 1 | 0.013–0.013 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/provisioning.go:272](../../apps/letfs/internal/filesystem/provisioning.go#L272) | pruneDeletedStorage | 1 | 0.015–0.090 | 0–1 | explain_analyze |
| [apps/letfs/internal/filesystem/scope_move.go:23](../../apps/letfs/internal/filesystem/scope_move.go#L23) | transferTree | 1 | 0.042–0.042 | 2–2 | explain_analyze |
| [apps/letfs/internal/filesystem/scope_move.go:54](../../apps/letfs/internal/filesystem/scope_move.go#L54) | transferTree | 1 | 0.008–0.008 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/scope_move.go:104](../../apps/letfs/internal/filesystem/scope_move.go#L104) | transferTree | 1 | 0.082–0.082 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/scope_move.go:106](../../apps/letfs/internal/filesystem/scope_move.go#L106) | transferTree | 1 | 0.063–0.063 | 1–1 | supplemental_explain_analyze |
| [apps/letfs/internal/filesystem/scope_move.go:113](../../apps/letfs/internal/filesystem/scope_move.go#L113) | transferTree | 1 | 0.261–0.261 | 2–2 | explain_analyze |
| [apps/letfs/internal/filesystem/search.go:162](../../apps/letfs/internal/filesystem/search.go#L162) | searchRoot | 1 | 0.023–0.028 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/search.go:212](../../apps/letfs/internal/filesystem/search.go#L212) | SearchFiles | 3 | 0.037–0.068 | 1–3 | explain_analyze |
| [apps/letfs/internal/filesystem/semantic_search.go:82](../../apps/letfs/internal/filesystem/semantic_search.go#L82) | hydrateSearch | 1 | 0.042–0.195 | 0–3 | explain_analyze |
| [apps/letfs/internal/filesystem/semantic_search.go:117](../../apps/letfs/internal/filesystem/semantic_search.go#L117) | SemanticSearch | 1 | 0.006–0.013 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/service.go:120](../../apps/letfs/internal/filesystem/service.go#L120) | DeleteFilesystem | 1 | 0.008–0.008 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/trash.go:29](../../apps/letfs/internal/filesystem/trash.go#L29) | queueObject | 1 | 0.009–0.048 | 0–1 | explain_analyze, supplemental_explain_analyze |
| [apps/letfs/internal/filesystem/trash.go:40](../../apps/letfs/internal/filesystem/trash.go#L40) | trashEntry | 2 | 0.006–0.012 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/trash.go:75](../../apps/letfs/internal/filesystem/trash.go#L75) | ListTrash | 1 | 0.008–0.009 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/trash.go:129](../../apps/letfs/internal/filesystem/trash.go#L129) | TrashNode | 1 | 0.090–0.103 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/trash.go:133](../../apps/letfs/internal/filesystem/trash.go#L133) | TrashNode | 1 | 0.040–0.044 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/trash.go:214](../../apps/letfs/internal/filesystem/trash.go#L214) | RestoreTrash | 1 | 0.011–0.012 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/trash.go:222](../../apps/letfs/internal/filesystem/trash.go#L222) | RestoreTrash | 1 | 0.053–0.058 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/upload_publication.go:87](../../apps/letfs/internal/filesystem/upload_publication.go#L87) | completeUpload | 1 | 0.075–0.101 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/upload_publication.go:96](../../apps/letfs/internal/filesystem/upload_publication.go#L96) | completeUpload | 1 | 0.070–0.074 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/upload_publication.go:180](../../apps/letfs/internal/filesystem/upload_publication.go#L180) | publishUpload | 1 | 0.063–0.066 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/upload_publication.go:210](../../apps/letfs/internal/filesystem/upload_publication.go#L210) | publishUpload | 1 | 0.034–0.047 | 1–1 | explain_analyze, supplemental_explain_analyze |
| [apps/letfs/internal/filesystem/upload_publication.go:216](../../apps/letfs/internal/filesystem/upload_publication.go#L216) | publishUpload | 1 | 0.095–0.097 | 1–1 | explain_analyze, supplemental_explain_analyze |
| [apps/letfs/internal/filesystem/upload_publication.go:227](../../apps/letfs/internal/filesystem/upload_publication.go#L227) | publishUpload | 1 | 0.047–0.069 | 1–1 | explain_analyze, supplemental_explain_analyze |
| [apps/letfs/internal/filesystem/upload_publication.go:247](../../apps/letfs/internal/filesystem/upload_publication.go#L247) | publishUpload | 1 | 0.072–0.073 | 1–1 | explain_analyze, supplemental_explain_analyze |
| [apps/letfs/internal/filesystem/upload_publication.go:255](../../apps/letfs/internal/filesystem/upload_publication.go#L255) | completeUploadReceipt | 1 | 0.006–0.022 | 0–1 | explain_analyze, supplemental_explain_analyze |
| [apps/letfs/internal/filesystem/upload_publication.go:260](../../apps/letfs/internal/filesystem/upload_publication.go#L260) | queueCandidate | 1 | 0.059–0.063 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/upload_publication.go:287](../../apps/letfs/internal/filesystem/upload_publication.go#L287) | abortUpload | 1 | 0.071–0.081 | 1–1 | explain_analyze, supplemental_explain_analyze |
| [apps/letfs/internal/filesystem/upload_publication.go:313](../../apps/letfs/internal/filesystem/upload_publication.go#L313) | abortMultipart | 1 | 0.066–0.066 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/uploads.go:101](../../apps/letfs/internal/filesystem/uploads.go#L101) | loadUpload | 1 | 0.012–0.015 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/uploads.go:174](../../apps/letfs/internal/filesystem/uploads.go#L174) | uploadTarget | 1 | 0.007–0.010 | 1–1 | explain_analyze, supplemental_explain_analyze |
| [apps/letfs/internal/filesystem/uploads.go:192](../../apps/letfs/internal/filesystem/uploads.go#L192) | uploadCapacity | 1 | 0.018–0.018 | 1–1 | explain_analyze |
| [apps/letfs/internal/filesystem/uploads.go:244](../../apps/letfs/internal/filesystem/uploads.go#L244) | CreateUpload | 1 | 0.006–0.010 | 0–1 | explain_analyze, supplemental_explain_analyze |
| [apps/letfs/internal/filesystem/uploads.go:295](../../apps/letfs/internal/filesystem/uploads.go#L295) | CreateUpload | 1 | 0.093–0.096 | 1–1 | explain_analyze, supplemental_explain_analyze |
| [apps/letfs/internal/filesystem/uploads.go:305](../../apps/letfs/internal/filesystem/uploads.go#L305) | CreateUpload | 1 | 0.022–0.022 | 1–1 | explain_analyze, supplemental_explain_analyze |
| [apps/letfs/internal/filesystem/uploads.go:366](../../apps/letfs/internal/filesystem/uploads.go#L366) | recordCapability | 1 | 0.071–0.082 | 1–1 | explain_analyze, supplemental_explain_analyze |
| [apps/letfs/internal/filesystem/uploads.go:432](../../apps/letfs/internal/filesystem/uploads.go#L432) | saveMultipart | 1 | 0.066–0.094 | 1–1 | explain_analyze, supplemental_explain_analyze |
| [apps/letfs/internal/temporal/maintenance.go:68](../../apps/letfs/internal/temporal/maintenance.go#L68) | reconcileResources | 1 | 0.007–0.007 | 0–1 | explain_analyze, supplemental_explain_analyze |
| [apps/letfs/internal/temporal/maintenance.go:81](../../apps/letfs/internal/temporal/maintenance.go#L81) | reconcileResources | 1 | 0.011–0.013 | 0–1 | explain_analyze, supplemental_explain_analyze |
