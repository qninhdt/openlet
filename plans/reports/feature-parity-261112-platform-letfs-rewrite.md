# Đối chiếu chức năng sau rewrite Platform, LetFS và ingest

Cập nhật 2026-11-12. Thuộc [plan hiện tại](../261111-1727-platform-letfs-rewrite/plan.md), không thay thế plan. Phạm vi: Account + Workspace → Platform, LetFS, ingest và shared packages; loại trừ Leta. Archive dùng để đọc hành vi, không lấy handwritten implementation/tests làm bản mới.

Trạng thái: đã đối chiếu contract và các implementation owning tương ứng. Người dùng chốt **chỉ bổ sung hybrid search** ngày 2026-11-12; bốn hành vi còn lại được chấp nhận cắt khỏi đợt rewrite. Hybrid đã implementation và full API E2E pass 4/4; acceptance đã đóng. [Review trước push dev và LoC](readiness-loc-261112-platform-letfs-rewrite.md) ghi kiểm chứng cuối và giới hạn.

## Kết quả các khoảng thiếu đã phát hiện

| Hành vi archived | Quyết định | Bản mới |
|---|---|---|
| Semantic search kết hợp BM25 + dense bằng RRF | Giữ | Native Qdrant text index với BM25 scoring; dense và lexical prefetch cùng workspace filter, RRF rồi current-version/live SQL hydration và rerank hiện có. Không thêm embeddings/service/dependency hoặc đổi protobuf |
| Search MIME/semantic type/created-updated filters và filename sorting | Không bổ sung theo lựa chọn người dùng | Giữ API search hiện tại |
| Restore trash sang storage khác cùng workspace | Không bổ sung theo lựa chọn người dùng | Chỉ restore trong storage nguồn |
| mkdir không tự tạo parent còn thiếu | Không bổ sung theo lựa chọn người dùng | CreateDirectories luôn tạo parents |
| Trash chỉ khi ordinary directory rỗng | Không bổ sung theo lựa chọn người dùng | Không có empty-directory option |

Nguồn: [protobuf LetFS archived](../../archive/2026-11-11/packages/contracts/proto/openlet_api/letfs/v1/letfs.proto), [search](../../archive/2026-11-11/apps/letfs/internal/filesystem/search.go), [semantic search](../../archive/2026-11-11/apps/letfs/internal/filesystem/semantic_search.go), [Qdrant client archived](../../archive/2026-11-11/apps/letfs-ingest/src/letfs_ingest/clients/qdrant.py). Các mục cắt ở đây là quyết định sau đối chiếu, không tự gọi chức năng bị mất là overengineering.

## Account/Workspace → Platform

| Nhóm | Owner/hành vi mới | Kết luận và bằng chứng |
|---|---|---|
| Clerk identity, bootstrap/default workspace, profile đọc/sửa, batch user summaries | Platform identity + ProvisionWorkspace | Giữ; [identity](../../apps/platform/internal/platform/identity.go), [provisioning](../../apps/platform/internal/platform/provisioning.go), gateway/collaboration E2E |
| Verified emails phục vụ invitation acceptance | Platform đọc native Clerk tại AcceptInvitation | Giữ mục đích; bỏ vòng Workspace → Account theo thiết kế gộp service |
| Workspace metadata/list/update/create/delete | Platform handlers, internal system create và native Temporal lifecycle | Giữ theo API đã duyệt; delete không cần Leta; list graph IDs rồi batch SQL |
| Member list/add/remove/leave, owner protection/transfer | SpiceDB authority, Platform API | Giữ; membership không mirror SQL; remove human không dừng agent, theo quyết định mới |
| Invitation create/list/revoke/accept, verified email, token expiry | Platform SQL invitation + graph member write | Giữ; collaboration E2E có consumed token không regrant sau remove |
| Scope discovery/access, personal mapping | LetFS ListStorages và List/Set/RevokeStorageAccess | Thay theo thiết kế được duyệt: không Platform proxy, filesystem/scope hoặc mapping table |
| Initial workspace ID/state/onboarding completion và admin role | Không có trong schema mới | Đã chốt bỏ; owner/member duy nhất, bootstrap workflow thay onboarding state cũ |
| RegisterAgent/EnsureLetaHomeAccess/CleanupLetaAccess và stop fanout | Không tồn tại trong core mới | Đã chốt bỏ boundary leak; Leta tự sở hữu agent relations, agent identity/grants độc lập |

Nguồn: archived Account/Workspace protobufs và `internal/transport/http/`, các owning handlers mới ở [Platform](../../apps/platform/internal/platform/). Public/internal routes mới do [contracts](../../packages/contracts/proto/openlet_api/platform/v1/) sở hữu.

## LetFS

| Nhóm | Owner/hành vi mới | Kết luận và bằng chứng |
|---|---|---|
| Tenant budget, storage roots/access/capabilities | workspace_storage + storages + SpiceDB | Giữ theo mô hình storage mới; không general filesystem service; SQL quota/integration và collaboration E2E |
| ID/path/cwd/root resolution, Stat/BatchStat/ListNodes/ReadTree | Batch/recursive SQL resolver | Giữ, bao gồm mount containment và header không tải toàn payload; native SQL invariant check |
| Directory/text create, rename/move/copy | CreateNode/CreateDirectories/MoveNode/CopyNode | Giữ; mkdir luôn tạo parents theo quyết định trên; immutable object refs khi copy, không S3 byte-copy saga |
| Text full/range/line/head/tail/metrics, replace/append/patch/truncate/overwrite/literal replace | ReadText/MutateText | Giữ; TextMetrics gộp thành include_metrics; UTF-8 string PostgreSQL theo quyết định; unit + SQL + E2E |
| Image bytes/resize, text/blob download, ZIP stream | ReadImage/GetDownload/DownloadArchive | Giữ; native image library và signed S3/HttpBody; E2E kiểm ZIP và nguyên bytes blob |
| Upload đơn/multipart, signed parts/checksum, complete/retry/abort | uploads + AWS SDK | Giữ; provider smoke RustFS đã kiểm multipart CRC32C, bad signature/checksum và conditional overwrite; XLSX E2E kiểm complete replay |
| Filename/literal text/line search | SearchFiles/TextSearch | Giữ phần cơ bản; người dùng chấp nhận bỏ filters/sort sau đối chiếu |
| Semantic evidence/chunks/rerank | SemanticSearch + native Qdrant/provider SDK | Đã bổ sung native BM25 + dense/RRF; giữ rerank và current-version/live ancestry SQL check; E2E đã pass với keyword evidence có dense score thấp |
| Trash occurrence/list/detail display/restore/purge | trash_entries; list trả entry + node, restore/purge nhận occurrence ID | Giữ domain occurrence; GetTrash riêng được gộp vào list theo inventory API đã duyệt; người dùng chấp nhận bỏ cross-storage/empty option |
| Processing status và publication API | FileHeader.processing; GetProcessingInput/PrepareArtifactUploads/CommitParse/CommitEnrichment/CompleteIndex/FailProcessing | Giữ, gộp RPC lẻ thành manifest/batch, readonly bằng ancestry và source content version |
| Manual ReprocessNode, config/ACL-triggered reprocessing | Không có trong MVP mới | Giới hạn đã ghi trong [design](../261111-1727-platform-letfs-rewrite/design.md): chỉ blob content change dispatch; failed Temporal work vận hành bằng native retry, không counter generation mới |
| Revision + desired/publication generations, reservation/lease và broad locking | files.version; local SQL transactions/conditional DML | Thay theo thiết kế được duyệt; không khôi phục framework cũ để tương thích tests |

Sửa thiếu sót invariant trong đợt đối chiếu: cross-storage MoveNode giờ từ chối subtree chứa blob nếu storage đích không cho blob, dùng cùng recursive CTE rồi rollback; native SQL test chứng minh move bị từ chối không đổi storage. CreateUpload và PrepareArtifactUploads cùng từ chối declared text MIME đi S3, dùng chung boundary validation; text artifacts vẫn qua manifest/PostgreSQL.

Nguồn: archived LetFS protobuf/service/search/text/processing/upload code; [implementation mới](../../apps/letfs/internal/storage/), [public contract](../../packages/contracts/proto/openlet_api/letfs/v1/letfs.proto), [internal contract](../../packages/contracts/proto/openlet_api/letfs/v1/internal.proto).

## Ingest

| Nhóm | Bản mới | Kết luận và bằng chứng |
|---|---|---|
| Hai worker CPU/IO, durable pipeline và resumable publication | ParseBlob, EnrichAndIndex; native Temporal retries/stages | Giữ; XLSX E2E chạy cả hai worker thật và real LetFS/S3/Qdrant |
| PDF/OCR với model offline, Word/PPT/XLSX, image | Docling/native format libraries, build-time model preparation | Giữ; focused generated Office tests; PDF scan offline đã smoke riêng, không paid-provider suite mỗi PR |
| Document layout, one/two-level sections, positional table CSV links, relative image links | exporter/layout mới | Giữ; focused layout/Word/PPT tests; Word wrapped runs và PPT compatibility shapes được xử lý tại parser boundary |
| Excel ordinary tables, outside cells/formulas/images | exporter mới dùng native workbook data | Giữ; generated spreadsheet test và pipeline E2E |
| Taxonomy/title/description/context, sampled evidence, image enrichment | Pydantic structured output, bounded evidence/vision inputs | Giữ; focused provider tests; public model API được WireMock tại boundary E2E |
| Folder README metadata/own body/children summaries | render + own_body | Giữ; tránh dùng generated child listing như body evidence |
| Full body chunks, overlap, ancestor context, stable versioned IDs | native splitter và Qdrant upsert wait | Giữ; focused index tests; ID gồm source/version/artifact/vector space; không app identity UUIDv5 |
| AI path rename + link rewriting | Khôi phục theo yêu cầu 2026-11-12 | Title hiện có → tên file/directory; rewrite links/README children; một batch CommitEnrichment nguyên tử, giữ node IDs/source name |
| CSV full profiling | CSV headers/sample | Giữ thay đổi đã chốt; không khôi phục full profiling |
| Custom process supervisor, broker/clients/telemetry wrappers | Bounded conversion subprocess + native SDKs/OTel | Thay theo plan; không mất input limits, model checks, heartbeats hoặc exception causes |

Nguồn: archived `parser/`, `processing/`, `clients/`, `temporal/`; [bản mới](../../apps/letfs-ingest/src/letfs_ingest/) và [focused tests](../../apps/letfs-ingest/tests/). BM25 thuộc LetFS search/native Qdrant bootstrap; payload text do IO ghi đã đủ, không cần đổi parser/indexer hoặc re-embed.

## Packages, infra và verification

- Generated Go/Python contracts thay DTO/handwritten RPC mirrors. Native actor metadata/ZedToken, config loader, telemetry và local receipt helpers vẫn có ở [sdk-go](../../packages/sdk-go/) và [sdk-python](../../packages/sdk-python/). HTTP/problem mapper, auth token wrapper, action registry và SDK repository layers được bỏ theo thiết kế; không giữ API cũ chỉ để archived consumers compile. Leta deferred, không thêm compatibility SDK cho nó.
- Root Makefile, six scripts, Compose, Playwright API/browser và two workflows thay harness cũ. Browser suite chờ frontend thật theo quyết định, không placeholder tests. Không đưa archived suites trở lại CI.
- Kiểm chứng cuối 2026-11-12: Go tests/vet, 15 ingest tests, Ruff, TypeScript, Buf lint, ShellCheck và actionlint pass. Native migrated PostgreSQL `TestStorageSQLInvariants` pass, gồm rejected cross-storage blob move rollback. Fresh Compose chạy **4/4 API journeys, 32.7s phần Playwright**, không publish host ports; project/volumes đã teardown. Đây không phải latency/load benchmark.
- Backup/restore drill tách biệt hoàn tất: inventory sáu PostgreSQL databases, sáu dumps/checksums, Platform/LetFS data so trước/sau khớp, nonempty-target refusal và restored SpiceDB permission sau native transaction-ID repair. Evidence local ignored tại `.local/drill/`; final E2E evidence tại `.local/e2e/results/`.
- Chưa chạy GitHub Actions hoặc deploy VPS; chưa production-provider/model quality/load test, browser/frontend hay full S3/Qdrant disaster recovery. PostgreSQL drill không đồng nghĩa full-system restore. Lần final fresh startup đã pass; một lần startup thủ công trước đó từng timeout kết nối Temporal, chưa chứng minh được nguyên nhân và không thêm retry framework để che lỗi.

## Điều kiện đóng báo cáo

Quyết định đã rõ: chỉ giữ hybrid search; bốn hành vi còn lại được chấp nhận cắt. Kiểm chứng hybrid trên Qdrant thật bằng test trong journey XLSX hiện có: embeddings cố tình xếp CSV evidence thấp hơn root README, query từ khóa vẫn phải trả evidence đó đầu tiên nhờ BM25/RRF. Không mở integration suite hoặc query framework mới. Full API E2E cuối pass 4/4; đóng acceptance. Các giới hạn production và archive local-only nằm trong review trước push dev, không đổi thành yêu cầu tính năng mới.
