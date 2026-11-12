# Benchmark LetFS — 2026-11-12

Commit đo: `222902e6aac2796daddbb7de1e67a51aa4b95361`, branch `dev`. Chỉ benchmark và ghi nhận; không sửa application, contracts, migrations, dependencies hoặc source test tooling.

Đã đo đủ **33 public RPC + 10 internal RPC**, đối chiếu inventory bằng protobuf descriptors. Vòng chính: **121 nhóm, 11.680 request được tính giờ, 0 RPC error/0 warm-up error**. Vòng bổ sung hoàn tất: **11 nhóm, 320 request, 0 RPC error/0 assertion error**; thêm **80 request cấp/thu hồi grant thật, không lỗi**. Multipart bytes có lỗi riêng bên dưới; không tính phép đo lỗi đó thành upload thành công.

## Các phát hiện

Ưu tiên sửa lỗi multipart để upload lớn hoạt động; với performance, ưu tiên resolver, ReadTree và truy vấn artifact. Chưa cần thêm cơ chế phân tán hoặc thay kiến trúc.

1. **Resolver chung gây công việc thừa trên đường đọc/ghi phổ biến.** `jsonb_to_recordset` ước lượng 100 input dù request chỉ có một locator. EXPLAIN cho thấy hash/seq scan khoảng 25.500 node để đi qua hai ancestor. Đối chứng SQL chỉ đổi input một locator thành `jsonb_to_record(($3::jsonb)->0)`, giữ phần ancestor/live-root/readonly/header: median execution custom **6,379 → 0,463 ms**, generic **4,522 → 0,467 ms**. Đây là thời gian SQL, chưa phải mức tăng tốc toàn RPC hoặc implementation đã kiểm chứng mọi semantics. Hướng sửa nhỏ: cho SQL biết cardinality thật của một locator, giữ batch là batch; không thêm cache/locking/abstraction framework. Nguồn: [paths.go](../../apps/letfs/internal/storage/paths.go), `inputs`, `bases`, `ancestors`, `resolve`.
2. **ReadTree giới hạn response nhưng vẫn xử lý toàn subtree.** Tại thư mục 10.000 file, trả 1.000 node: p95 **54,96 ms** ở concurrency 1, **454,91 ms** ở concurrency 32, throughput khoảng **82 RPC/s** ở concurrency 32. Follow-up với khoảng 25.500 node toàn DB: xin 10 node vẫn p95 **69,01 ms**, xin 1.000 node p95 **81,49 ms**. EXPLAIN thấy recursive tree sinh **10.001 hàng** trước sort/LIMIT; LIMIT không phải giới hạn lượng truy vấn phải duyệt. Cần thu hẹp IDs/sort/LIMIT trước các join rộng, rồi đo lại; không đổi ordering hay thêm cơ chế cây phức tạp trong đợt benchmark. Nguồn: [tree.go](../../apps/letfs/internal/storage/tree.go), `ReadTree`.
3. **GetProcessingInput chọn plan quá lớn cho cây artifact nhỏ.** Vòng chính, 1/100/500 artifact có p95 **29,08 / 31,53 / 34,69 ms**. Follow-up khác phân bố dữ liệu, 100 artifact p95 **91,37 ms**. EXPLAIN actual **101** hàng nhưng estimate **133.721**, hash các bảng files/nodes toàn DB, ghi **1.682 block tạm ≈ 13,1 MiB**, JIT khoảng **36 ms** trong execution khoảng **90,6 ms**. Thử index `nodes(parent_id)` trên DB benchmark: API median **82,84 → 84,17 ms**, EXPLAIN median **90,574 → 90,893 ms**: **không cải thiện**. Không đề xuất thêm index này như một bản sửa đã được chứng minh. Hướng điều tra: lấy đúng IDs artifact trước khi join payload rộng; giữ batch, không truy vấn từng artifact. Nguồn: [processing.go](../../apps/letfs/internal/storage/processing.go), `GetProcessingInput`.
4. **Multipart chưa chạy được trọn luồng trên RustFS hiện tại.** Tạo multipart 20 MiB và SignParts thành công; part size 8 MiB. PUT URL được trả về, không thêm header checksum, tái hiện HTTP **500 InternalError**. Thử gửi `x-amz-checksum-crc32c` thì RustFS ghi `presigned_unsigned_amz_header`, vì SignParts chỉ ký `host`. Chưa kết luận mọi nguyên nhân của HTTP 500 là checksum; đây là lỗi tích hợp cần xử lý riêng. Không thể cung cấp latency CompleteUpload multipart thành công. CompleteUpload single-part đã đo thành công. Không đổi provider, không bypass API để làm benchmark xanh. Nguồn: [uploads.go](../../apps/letfs/internal/storage/uploads.go), `CreateUpload`, `SignParts`, `verifyObject`.
5. **UpdateStorage chỉ rename vẫn chạy và chờ Temporal workflow.** p50 **42,10 ms**, p95 **48,47 ms**, SQL execution chỉ **0,15 ms/request**. Handler luôn ExecuteWorkflow + Get; activity vẫn đọc visibility/ghi SpiceDB. Đây là overhead có bằng chứng cho name-only update; có thể giữ workflow cho visibility và cân nhắc đường rename trực tiếp khi sửa. Không bỏ Temporal cho lifecycle/visibility. Nguồn: [access.go](../../apps/letfs/internal/storage/access.go), `UpdateStorage`; [jobs.go](../../apps/letfs/internal/storage/jobs.go), `updateVisibility`.
6. **Các chi phí còn lại có thể giải thích được.** Resize ảnh 1600×1200 xuống width 320 p95 **61,33 ms**, CPU decode/resize/encode mỗi lần. AbortUpload multipart p95 **63,59 ms** dù SQL ~**0,05 ms**, phần ngoài DB là S3 abort. ZIP 100 text p95 **12,70 ms**; ZIP 10 blob thật tổng 640 KiB p95 **37,93 ms**, có khoảng **24,94 ms SQL/request**. Không thêm cache ảnh, pool download hay cơ chế mới chỉ từ các sample này.

## N+1, truy vấn và locking

Stat, BatchStat 1/10/100, ListNodes, ReadTree, ReadText, SearchFiles và TextSearch đều một application SQL/request. BatchStat 100 không biến thành 100 lần gọi DB. PrepareArtifactUploads 1/100 output đều hai SQL/request. CommitParse 1/100/500 artifact đều **5 application statements/request**, gồm BEGIN/COMMIT. Copy 101 node dùng **7 application statements**, không gọi resolve cho từng node.

`pg_stat_statements` bật `track=all` báo cả các câu SQL kiểm tra FK deferred với `toplevel=true`, vì chúng chạy khi commit. Vì vậy số raw 108 statements của Copy 101 node = **7 app + 101 FK checks**; raw 505 của CommitParse 500 = **5 app + 500 FK checks**. Không được gọi các kiểm tra nội bộ PostgreSQL này là application N+1. Bảng dưới đã tách chúng; BEGIN/COMMIT vẫn tính là app statements. Chi phí FK nằm trong latency thực tế, không bỏ constraint để giảm số đo.

Không thấy workspace/filesystem mutex, lease hoặc fencing được thêm vào đường đọc. Có row lock trên file đang đổi và row lock ngắn trên `workspace_storage` khi UPDATE usage/quota. Vì vậy ghi các file khác nhau trong cùng workspace vẫn có tranh chấp counter; ghi cùng một file tuần tự hóa mạnh hơn. Đây là contention đã đo, không phải lý do tự thêm workspace-wide lock hoặc sharded counter.

| Tình huống | Đồng thời | p95 ms | RPC/s | Sample chờ Lock (transactionid + tuple) |
|---|---:|---:|---:|---:|
| Create text, cùng workspace | 1 | 10.20 | 108.5 | 0 |
| Create text, cùng workspace | 8 | 21.86 | 473.6 | 13 |
| Create text, cùng workspace | 32 | 66.61 | 570.3 | 62 |
| Append, các file khác nhau | 1 | 9.67 | 140.8 | 0 |
| Append, các file khác nhau | 8 | 18.26 | 605.0 | 9 |
| Append, các file khác nhau | 32 | 60.86 | 649.8 | 51 |
| Append, cùng file | 1 | 9.95 | 143.0 | 0 |
| Append, cùng file | 8 | 45.59 | 340.0 | 102 |
| Append, cùng file | 32 | 159.50 | 335.3 | 192 |

Sample đếm backend đang chờ mỗi ~20 ms, không phải tổng lock, phần trăm request hay thời gian lock. Cùng file ở concurrency 32 có nhiều lock wait hơn, throughput khoảng 335/s; các file khác nhau khoảng 650/s trong lượt đo này. Chưa có bằng chứng cần thay cơ chế quota hiện tại; ưu tiên sửa query plan trước.

## Inventory public API

Latency ms, throughput closed-loop RPC/s; c=1, trừ các bảng bổ sung có ghi rõ. Dòng đọc lấy dataset thư mục 10.000 file. Các mutation sau đó làm DB tăng dần tới 25.251 node/25.098 file/24 storage; đây không phải mọi API đều chạy trên chính xác 10.000 hàng. Mỗi group warm-up ba request riêng; n dưới đây không gồm warm-up. Với n=10/20/40, p99 gần hoặc bằng max, không đủ suy ra tail ổn định.

Stat theo ID; ListNodes page 100; ReadTree max_nodes 1.000; BatchStat một locator; ReadText khoảng 4 KiB; SearchFiles/TextSearch query hit; MutateText append; CopyNode thư mục 100 file; ReadImage bản gốc PNG; ListTrash rỗng; Create/CompleteUpload single-part 64 KiB; SignParts ba part; GetDownload text. Các biến thể có dữ liệu lớn hơn được ghi bên dưới.

| RPC | n | p50 ms | p95 ms | p99 ms | RPC/s | SQL app/request |
|---|---:|---:|---:|---:|---:|---:|
| AbortUpload | 20 | 60.01 | 63.59 | 67.67 | 16.5 | 1 |
| BatchStat | 80 | 8.32 | 9.98 | 15.45 | 116.3 | 1 |
| CompleteUpload | 20 | 7.80 | 8.29 | 8.49 | 127.4 | 8 |
| CopyNode | 20 | 27.76 | 37.98 | 40.58 | 34.2 | 7 |
| CreateDirectories | 20 | 11.00 | 14.98 | 15.58 | 85.9 | 6 |
| CreateNode | 80 | 9.05 | 10.20 | 11.68 | 108.5 | 7 |
| CreateUpload | 40 | 7.09 | 10.77 | 12.00 | 123.1 | 7 |
| DownloadArchive | 20 | 11.36 | 12.70 | 16.66 | 85.0 | 1 |
| GetDownload | 40 | 7.47 | 8.38 | 9.01 | 131.3 | 1 |
| GetStorage | 40 | 1.55 | 2.59 | 3.76 | 566.7 | 1 |
| GetUpload | 40 | 1.06 | 1.77 | 4.46 | 816.7 | 1 |
| GetWorkspaceStorage | 40 | 1.73 | 3.22 | 4.08 | 526.0 | 1 |
| ListNodes | 80 | 7.08 | 11.77 | 12.74 | 126.7 | 1 |
| ListStorageAccess | 40 | 1.82 | 2.55 | 4.62 | 520.9 | 1 |
| ListStorages | 40 | 1.12 | 1.95 | 5.21 | 751.5 | 1 |
| ListTrash | 40 | 0.84 | 3.03 | 4.99 | 825.5 | 1 |
| MoveNode | 20 | 9.05 | 12.56 | 13.49 | 103.8 | 6 |
| MutateText | 80 | 6.80 | 9.67 | 11.96 | 140.8 | 7 |
| PurgeTrash | 20 | 7.87 | 8.60 | 8.73 | 125.1 | 5 |
| ReadImage | 40 | 8.32 | 8.98 | 10.18 | 119.4 | 1 |
| ReadText | 80 | 7.74 | 11.16 | 15.57 | 120.2 | 1 |
| ReadTree | 80 | 47.00 | 54.96 | 71.64 | 21.3 | 1 |
| RestoreTrash | 20 | 9.11 | 10.00 | 10.58 | 107.9 | 5 |
| RevokeStorageAccess | 40 | 3.79 | 4.53 | 4.72 | 259.1 | 1 |
| SearchFiles | 80 | 8.33 | 12.82 | 15.70 | 116.7 | 1 |
| SemanticSearch | 40 | 11.93 | 16.55 | 17.82 | 79.7 | 1 |
| SetStorageAccess | 40 | 4.62 | 5.28 | 8.76 | 212.4 | 1 |
| SignParts | 40 | 1.14 | 2.41 | 3.32 | 765.1 | 1 |
| Stat | 80 | 7.33 | 8.98 | 11.98 | 132.3 | 1 |
| TextSearch | 80 | 9.27 | 14.35 | 15.78 | 100.4 | 1 |
| TrashNode | 20 | 8.96 | 10.00 | 10.69 | 108.5 | 6 |
| UpdateStorage | 10 | 42.10 | 48.47 | 48.47 | 23.1 | 7 |
| UpdateStorageQuota | 40 | 2.30 | 4.51 | 6.64 | 368.5 | 1 |

SetStorageAccess ở vòng chính lặp TOUCH cùng một viewer; RevokeStorageAccess lặp cùng một actor nên sau warm-up chủ yếu là revoke idempotent. Đã đo thêm trên **43 actor khác nhau** (3 warm-up + 40 timed): mỗi lần SetStorageAccess tạo grant mới, p50/p95/p99 **6,22 / 7,88 / 8,09 ms**; mỗi lần RevokeStorageAccess xóa grant đang tồn tại, **3,71 / 4,59 / 4,91 ms**. Mỗi RPC vẫn một SQL app; quyền thành viên fixture được truyền bằng fresh token để không tính thao tác bị từ chối do revision cũ. Có kiểm đủ 43 grant trước khi đo xóa.

SemanticSearch dùng Qdrant thật với 10 evidence points, nhưng embedding/rerank provider dùng fixture HTTP. Con số này chỉ đo orchestration, Qdrant, SQL và fixture transport; không phải latency AI provider hoặc bằng chứng search scale lớn.

## Inventory internal API

Create/DeleteStorage lần lượt là storage mới/rỗng; DeleteWorkspaceStorage một storage rỗng. GetProcessingInput/CommitParse/CommitEnrichment dòng chính là một artifact; PrepareArtifactUploads một output. CommitParse/Enrichment thực hiện stage transition trên các source khác nhau, không benchmark chỉ replay. Source/version/artifact metadata được seed trực tiếp với constraints DB thật; các source fixture PDF không cần parser/S3 fetch cho những RPC này. Không dùng thời gian này làm hiệu năng parser.

| RPC | n | p50 ms | p95 ms | p99 ms | RPC/s | SQL app/request |
|---|---:|---:|---:|---:|---:|---:|
| CommitEnrichment | 20 | 22.13 | 24.35 | 24.88 | 46.9 | 5 |
| CommitParse | 20 | 2.43 | 4.10 | 4.55 | 365.1 | 5 |
| CompleteIndex | 20 | 1.59 | 1.97 | 4.26 | 569.8 | 4 |
| CreateStorage | 20 | 4.83 | 5.49 | 5.95 | 207.5 | 4 |
| DeleteStorage | 20 | 4.32 | 4.91 | 5.19 | 229.6 | 5 |
| DeleteWorkspaceStorage | 20 | 4.00 | 4.44 | 4.81 | 249.0 | 2 |
| FailProcessing | 20 | 1.62 | 1.90 | 4.38 | 559.3 | 4 |
| GetProcessingInput | 40 | 19.79 | 29.08 | 33.60 | 47.7 | 1 |
| PrepareArtifactUploads | 20 | 1.81 | 2.81 | 4.60 | 490.5 | 2 |
| ProvisionWorkspaceStorage | 20 | 1.43 | 1.91 | 4.26 | 616.3 | 1 |

## Các biến thể bổ sung

| Tình huống | n | p50 ms | p95 ms | p99 ms | RPC/s | SQL app/request |
|---|---:|---:|---:|---:|---:|---:|
| Stat path sâu 10 thư mục | 80 | 10.49 | 14.26 | 15.79 | 92.0 | 1 |
| BatchStat 10 | 80 | 7.49 | 8.37 | 14.07 | 129.3 | 1 |
| BatchStat 100 | 80 | 10.66 | 13.00 | 19.47 | 90.0 | 1 |
| Text 256 KiB, tail 10 + metrics | 80 | 9.07 | 10.42 | 14.16 | 109.0 | 1 |
| SearchFiles không có hit | 80 | 13.78 | 17.66 | 21.80 | 70.6 | 1 |
| TextSearch lines, text 256 KiB | 80 | 8.08 | 10.56 | 13.58 | 118.9 | 1 |
| MutateText replace | 20 | 6.40 | 9.31 | 9.83 | 144.8 | 7 |
| MutateText patch | 20 | 6.45 | 7.59 | 9.19 | 147.9 | 6 |
| MutateText truncate | 20 | 5.79 | 7.77 | 9.01 | 164.2 | 7 |
| MutateText overwrite | 20 | 6.20 | 6.73 | 6.91 | 161.6 | 6 |
| MutateText literal_replace | 20 | 7.45 | 10.12 | 10.63 | 128.1 | 6 |
| GetDownload blob, chỉ ký URL | 40 | 8.32 | 9.36 | 11.59 | 118.0 | 1 |
| ReadImage resize 1600→320 | 20 | 55.57 | 61.33 | 63.31 | 17.7 | 1 |
| DownloadArchive 100 text | 20 | 11.36 | 12.70 | 16.66 | 85.0 | 1 |
| GetProcessingInput 100 artifacts, baseline | 40 | 24.43 | 31.53 | 45.46 | 38.8 | 1 |
| GetProcessingInput 500 artifacts | 40 | 31.62 | 34.69 | 39.47 | 31.3 | 1 |
| CommitParse 100 artifacts | 20 | 9.90 | 11.75 | 14.09 | 95.9 | 5 |
| CommitParse 500 artifacts | 10 | 38.20 | 87.78 | 87.78 | 23.1 | 5 |
| PrepareArtifactUploads 100 outputs | 20 | 7.58 | 10.63 | 11.38 | 125.0 | 2 |
| CommitEnrichment 100 artifacts | 20 | 29.30 | 32.54 | 33.68 | 33.4 | 5 |
| ReadTree.10 | 40 | 56.51 | 69.01 | 92.52 | 17.1 | 1 |
| ReadTree.1000 | 40 | 69.47 | 81.49 | 92.27 | 14.0 | 1 |
| ListStorages.21 (c=8) | 40 | 3.69 | 13.92 | 13.99 | 1376.4 | 1 |
| ListStorageAccess.101 | 40 | 2.86 | 3.82 | 6.00 | 331.8 | 1 |
| ListTrash.100 | 40 | 3.45 | 4.94 | 5.74 | 281.2 | 1 |
| CreateUpload.multipart.fresh | 10 | 21.03 | 22.33 | 22.33 | 46.8 | 7 |
| DownloadArchive.10blobs640KiB | 20 | 32.32 | 37.93 | 45.33 | 29.7 | 1 |
| GetProcessingInput100.beforeIndex | 40 | 82.84 | 91.37 | 92.93 | 12.0 | 1 |
| GetProcessingInput100.afterIndex | 40 | 84.17 | 88.27 | 93.66 | 11.8 | 1 |
| DeleteStorage.1000files | 5 | 76.02 | 77.69 | 77.69 | 13.1 | 6 |
| DeleteWorkspaceStorage.10storages | 5 | 21.35 | 21.88 | 21.88 | 46.9 | 2 |

Hai follow-up list (21 storages và 100 viewer grants + owner) dùng token fresh đã ghi sau fixture, qua optional `x-openlet-zed-token`, để xác nhận response đủ dữ liệu; không đánh đồng với profile `minimize_latency` mặc định của vòng chính. Các thử fixture trước đó có response thiếu/stale hoặc assertion fail khi dùng default revision ngay sau nhiều graph writes; chúng được giữ riêng và loại khỏi nhóm final, không coi empty/partial response là benchmark đầy đủ. Không ép fully_consistent trên mọi API.

CreateUpload multipart fresh chỉ tạo descriptor/session, không tính bytes upload. PUT 20 MiB chia part 8 MiB tái hiện lỗi trước khi có completion thành công. DeleteStorage 1.000 file và DeleteWorkspaceStorage 10 storages chỉ n=5, dùng để phát hiện hành vi thô; p95/p99 của chúng là max mẫu. DeleteWorkspaceStorage đi qua graph deletion tuần tự mỗi storage theo code, SQL app vẫn hai statements, không phải N+1 theo node.

ListNodes đã scan trọn pagination: **1.000 node/10 trang/60,43 ms**, **10.000 node/100 trang/760,08 ms**, kiểm đúng count và kết thúc cursor. Đây là thời gian một scan, không phải p95.

## Read concurrency

| Tình huống tại 10k file | c | p50 ms | p95 ms | p99 ms | RPC/s |
|---|---:|---:|---:|---:|---:|
| Stat.id | 1 | 7.33 | 8.98 | 11.98 | 132.3 |
| Stat.id | 8 | 13.73 | 16.60 | 18.98 | 597.7 |
| Stat.id | 32 | 44.45 | 60.42 | 66.46 | 683.1 |
| ListNodes.100 | 1 | 7.08 | 11.77 | 12.74 | 126.7 |
| ListNodes.100 | 8 | 16.06 | 20.14 | 24.00 | 492.4 |
| ListNodes.100 | 32 | 53.85 | 70.46 | 78.74 | 583.2 |
| BatchStat.100 | 1 | 10.66 | 13.00 | 19.47 | 90.0 |
| BatchStat.100 | 8 | 20.45 | 24.55 | 28.07 | 387.9 |
| BatchStat.100 | 32 | 73.17 | 100.64 | 105.25 | 415.1 |
| ReadTree.1000 | 1 | 47.00 | 54.96 | 71.64 | 21.3 |
| ReadTree.1000 | 8 | 99.51 | 122.10 | 133.53 | 79.5 |
| ReadTree.1000 | 32 | 382.08 | 454.91 | 501.09 | 81.9 |

## HTTP/Envoy đối chứng

Vòng Python ban đầu thấy HTTP c=32 p95 249–403 ms. Không quy số này cho Envoy: chạy lại bằng Go native gRPC và standard `net/http`, drain response/reuse connections, cùng một node, cùng dataset khoảng 25k, 1.000 request mỗi group, kết quả dưới. HTTP/1.1 có JWT/Envoy/JSON; native gRPC dùng trusted actor metadata. Đây là so sánh đường truy cập thực tế, không phải hai transport có cùng chi phí xác thực.

| Transport / Stat | c | n | p50 ms | p95 ms | p99 ms | req/s | Errors |
|---|---:|---:|---:|---:|---:|---:|---:|
| grpc | 1 | 1000 | 8.83 | 11.57 | 14.31 | 112.8 | 0 |
| grpc | 8 | 1000 | 13.57 | 19.42 | 28.57 | 588.2 | 0 |
| grpc | 32 | 1000 | 45.37 | 60.21 | 74.07 | 678.4 | 0 |
| http | 1 | 1000 | 6.83 | 8.24 | 10.92 | 142.5 | 0 |
| http | 8 | 1000 | 12.98 | 15.79 | 17.52 | 638.8 | 0 |
| http | 32 | 1000 | 53.75 | 79.72 | 92.76 | 568.4 | 0 |

Một lần Go độc lập khác cũng không tái hiện tail Python lớn: HTTP c=32 p95 68,29 ms. Các lượt có biến động máy chung, thứ tự chạy và prepared plans; không kết luận HTTP nhanh hơn gRPC hay Envoy đã được chứng minh scale production. Các bảng RPC chính dùng native gRPC.

## Môi trường, phép đo và bằng chứng

- Intel i5-11400H, 12 logical CPU, RAM khoảng 15 GiB; Linux 7.0.0-42-generic. Client và toàn bộ Compose cùng máy; host có sẵn swap usage, không kiểm soát hoàn toàn tải ngoài benchmark.
- PostgreSQL/SpiceDB/Temporal/RustFS/Qdrant thật. Platform và LetFS cùng native workers hoạt động. Ingest CPU/IO không start; JWKS và model provider dùng WireMock fixture. Không chạy Leta.
- Độc lập với stack/DB cũ: Compose project `openlet-bench-letfs`, credentials test ngẫu nhiên, volume mới mỗi lượt. Backup post-migration trước fixtures và dump trước index experiment. Các container/network/volume của benchmark đã teardown; không sửa `.env` thật.
- Vòng chính: flat files tăng từ 1k lên 10k, text 512 byte/file; thêm cây sâu 10, 100-file subtree, 256 KiB text, 64 write targets và artifacts. Follow-up thêm 15k file ở thư mục khác, không chỉ đổi page limit trên tập rỗng. Bulk seed xong có ANALYZE; không dùng VACUUM để giả định trạng thái ổn định dài hạn.
- Closed-loop workers c=1/8/32, tách ba warm-up đầu; thời gian từ client trước RPC đến response/đọc hết stream. Write request IDs riêng, không vô tình benchmark idempotency replay. S3 PUT setup không tính vào CompleteUpload. Quota/file row locks và durability thật vẫn bật.
- `pg_stat_statements`, `track_io_timing`, wait sampling khoảng 20 ms; số SQL lọc theo role LetFS và tách FK deferred. SQL time không bằng toàn bộ RPC latency và không bao gồm mọi thời gian client/pool/SpiceDB/S3/Temporal. EXPLAIN ANALYZE có overhead; không trộn execution-only với planning hoặc RPC latency.
- PostgreSQL mặc định `work_mem=4 MiB`, `shared_buffers=128 MiB`, JIT on, max_connections=100. Chỉ connection diagnostics ép custom/generic plan; ứng dụng giữ auto. Maintenance interval benchmark 3.600s để tránh job cleanup xen vào nhóm ngắn.
- Một snapshot khi load ghi PostgreSQL khoảng 249% CPU và 286 MiB RAM, LetFS khoảng 35 MiB; đây là snapshot, không phải peak/RSS toàn phiên hay capacity limit. DB CPU và query shape là bằng chứng mạnh hơn giả thuyết application locking chung.

Raw evidence và mọi executable benchmark chỉ ở **`.local/bench-letfs/`**, đã kiểm Git ignore; không thêm script vào source/CI. Các file chính: `summary.json`, `results.jsonl`, `explain.json`, `pagination-*.json`, `resources*.jsonl`; follow-up `followup/summary.json`, `experiments.json`, `explain.json`, `multipart.json`; paired Go transport ở `followup-attempt2/transport.jsonl`; grants thật ở `permissions/summary.json`. Raw latencies và query text được giữ tại local. Các lần setup/harness thất bại và follow-up stale fixtures nằm riêng, không cộng vào lượt đã kiểm chứng. Report không chứa signed URLs/credentials.

Search miss có seq scan dù schema đã có trigram GIN; full fresh-seed plan có resolver scan + candidate scan. Đây là quan sát trên phân bố hiện tại, không chứng minh thiếu index. Chưa tách ảnh hưởng GIN pending list/autovacuum; không đề xuất tạo thêm search index chỉ dựa vào thời gian này.

## Giới hạn và việc chưa làm

Không sửa performance code hay multipart contract trong task benchmark. Không benchmark parser/OCR/model provider thật, WAN/S3 production, cold-disk, soak dài hạn hoặc capacity/SLA trên VPS. 43/43 là coverage RPC với các scenario ghi rõ, không phải mọi tổ hợp input, mọi lỗi và mọi distribution. Các sample mutation/lifecycle ngắn không đủ chứng minh p99 production. Chưa có latency CompleteUpload multipart thành công vì lỗi UploadPart trên provider hiện tại. Không có bằng chứng cần thêm cache phân quyền, lock/lease/fencing, sharded quota hoặc tách service để xử lý những điểm đo được.

Implementation follow-up theo phê duyệt sau benchmark đã hoàn tất: [thay đổi, audit idempotency và số đo trước/sau](implementation-261112-1249-letfs-performance-idempotency.md). Các số liệu trong report này giữ nguyên baseline trước sửa.
