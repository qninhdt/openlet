# VFS, shell và Python sandbox của Leta đã chốt

Chốt 2026-11-13, chưa triển khai. Mirage là VFS/runtime chung của mọi file_* và exec_* tools; LetFS là owner của dữ liệu bền vững. Giữ native Redis content/index cache với ReadPolicy.BOUNDED, không kiểm quyền/version từ xa trước cache hit; bỏ policy.py. Dùng default Mirage 0.0.8: content/index TTL 600 giây, rút con số 5 giây chưa có số đo. Một storage_id là home binding, vẫn giữ dynamic public/shared/granted-private mounts theo [kiến trúc](design.md#10-filesystem-và-cache) và [native APIs](boundaries.md#5-file-operations-mounts-và-cache). Schema/Temporal inventory không đổi; public transport theo [HTTP/streaming đã chốt](streaming.md).

## 1. Mục tiêu và quyết định

Agent thao tác tài liệu, tìm kiếm, xử lý text và tính toán trong một filesystem bền vững. Giữ Mirage làm virtual shell/VFS engine, Monty làm Python sandbox, LetFS làm owner của dữ liệu và quyền. Viết mới adapter từng dòng; archive chỉ cho biết behavior cần giữ và cơ chế cần bỏ.

exec_shell là shell ảo có cú pháp Bash do Mirage hỗ trợ, không phải /bin/bash trên host. exec_python là Python subset của Monty, không phải một CPython environment có thể pip install. Không tạo terminal service, container cho từng agent, FUSE mount hoặc durable process manager.

```text
file_* ──────────────────────────┐
exec_shell → Mirage shell ────────┼─→ Mirage VFS dispatcher
exec_python → Mirage / Monty ────┘
                                       ↕ native Redis content/index cache
                                       ↓ cache miss / mutation / search
                          concrete LetFS adapter
                                       ↓ native gRPC
                                     LetFS
```

Một adapter inject binding/actor cho mọi backend call. Mirage sở hữu parser, pipes, redirection, glob, cache và lệnh có sẵn. LetFS sở hữu auth, live tree/containment, readonly artifacts, content/version, quota, receipts và blob processing khi request tới service. Tool không gọi gRPC ngoài Mirage dispatcher; không convert file_read/write/edit thành Bash command.

## 2. Mount và identity

Mỗi root giữ workspace_id/storage_id làm home binding như schema đã duyệt. Các storage đọc được khác được discover từ LetFS và mount trong RAM; không thêm mount/grant table. Adapter nhận actor và các bindings đã authorize từ runtime, không nhận actor/root tùy ý từ model.

| Execution | Actor gửi LetFS | Mount /home |
|---|---|---|
| Root Leta A | agent:A | storage root lấy từ GetStorage |
| Leti trong box B | agent:A | box.home_node_id của cùng storage |

Đường dẫn hướng agent dùng ~ và ~/path. Virtual HOME/cwd mặc định là /home; Mirage native expand_tilde hỗ trợ ~ và ~/... qua HOME. Tool nhận path dùng cùng native expansion trước routing. Không mount một directory tên literal ~ hoặc tự viết shell expander. pwd vẫn trả absolute path; Python open không tự expand ~ nên dùng relative path từ home hoặc explicit expansion.

Hai Leti cùng box chia sẻ home; hai box khác nhau có containment roots khác nhau. Root nhìn toàn home storage của nó, kể cả các box homes bên trong. Đây là isolation theo box, không phải mỗi Leti một storage/quyền graph riêng.

Box directory dùng đường dẫn ~/.boxes/<box_id>/ trong góc nhìn root; các Leti trong box thấy directory đó là ~/. Mount bind bằng home_node_id thật, không resolve box name mỗi lần đọc. Đường dẫn dùng stable box ID để tên box không trở thành filesystem identity.

Virtual /home được đổi thành locator tương đối bên dưới mount root. Mọi NodeLocator mang root_node_id, kể cả node_id trực tiếp và cwd_node_id. Copy/move inject root cho cả source và destination. LetFS resolver kiểm live ancestry; chuẩn hóa đường dẫn phía Leta chỉ phục vụ routing, không thay server enforcement.

Giữ các external mounts theo một quy tắc đường dẫn ổn định:

```text
~                         # home của root hoặc box
/mnt/<public-storage-id>  # public/shared trong cùng workspace
/mnt/<private-storage-id> # private đã cấp viewer/editor cho root agent
```

Tên storage là metadata hiển thị, ID làm mount key để rename không đổi đường dẫn. Không cần /users/<owner> hoặc personal resolver vì một user có thể có nhiều storages. Public chỉ trong workspace, mặc định read; write cần owner/editor. Private được share trực tiếp hoặc qua HITL dùng cùng quy tắc mount.

Discovery gọi ListStorages(workspace_id) bằng root agent, không owned_only và không dùng quyền của human owner. Follow native pagination đến hết kể cả page không có visible items nhưng còn next_page_token. Response có root_node_id/capabilities, không N+1 GetStorage cho mỗi item. Loại home storage_id khỏi external mounts: đặc biệt không tạo /mnt/<home-storage-id> cho Leti vì alias đó sẽ mở lại toàn home storage, vượt box containment.

Giữ discovery result trong runtime RAM, refresh lazily ở safe tool boundary khi cũ hơn 30 giây hoặc sau HITL grant; đây là default tuning đã duyệt, không list lại trước mỗi file operation hoặc background poller. Không đổi mount giữa command đang chạy. So mount map với discovery rồi dùng Mirage add_mount/unmount/set_mount_mode có sẵn. Public/storage share mới xuất hiện khi refresh; request tới LetFS sau revoke/delete bị service kiểm quyền, còn cached bytes có thể dùng tới expiry hoặc unmount. Không thêm SQL mount/grant mirror.

Accepted HITL cấp root agent quyền vào storage đích qua SetStorageAccess; refresh tiếp theo đưa storage đó vào /mnt. Mọi Leti dùng root actor nên có cùng external grants; chỉ home riêng chịu box containment. Không mount home storage của root dưới alias khác. Không thay root.storage_id, không thêm workflow/activity cho mounting, không cần user chạy mount thủ công hoặc vòng polling nền. Việc đổi home binding vẫn là tính năng khác đang hoãn. Những virtual views Mirage cần cho engine không được ánh xạ sang host disk.

Home-first đã chốt tại [Box/Leti](boxes.md#4-home-first-provisioning): lifecycle gọi LetFS CreateDirectories trước rồi ghi active graph với home_node_id thật trong SQL transaction. Pending create ở Temporal, không SQL box placeholder; giữ NOT NULL. VFS không ngầm tạo box home hoặc chọn ID thay lifecycle. Runtime chỉ mở home session sau active.

## 3. Bảy tools cho agent

| Tool | Input chính | Behavior |
|---|---|---|
| file_list | path=~, depth=1, cursor | Metadata; system chọn page size; flat listing có native page token, recursive tree có truncated |
| file_read | path, start_line=1 | System chọn text window; image thành multimodal image; blob khác thành descriptor/artifact references |
| file_write | path, content, overwrite=false | Tạo UTF-8 text; file có sẵn chỉ ghi đè khi explicit |
| file_edit | path, old_text, new_text, replace_all=false | Native literal replace; mặc định phải khớp đúng một chỗ |
| exec_shell | command, cwd=~ | Chạy command/pipeline trong Mirage; timeout/output budgets do runtime |
| exec_python | code | Chạy Monty qua native runtime integration, cùng /home; runtime quản lý budgets |
| file_semantic_search | query, paths | Native LetFS SemanticSearch dưới mount được chọn; mặc định home, hit budget do system |

Tool definitions đặt trong runtime/tools.py. Tất cả file_* gọi Mirage VFS/dispatch trong cùng workspace/cache với exec_shell và exec_python; gRPC chỉ nằm trong concrete LetFS adapter mà dispatcher gọi. Dùng native session.vfs.read/write hoặc dispatch cho hooks đặc thù; không thêm FilesystemTools façade hoặc xây shell string cho file tools. exec_python dùng native Mirage/Monty integration, không host subprocess.

Mirage có session.tools.read/write/edit nhưng bộ tool cấp cao có read-history guards và edit bằng read-modify-write. Leta giữ contract đã duyệt: file_write explicit overwrite, file_edit atomic literal replacement tại LetFS. Khai báo hook write_text/edit_text bằng native vfs_call(effect=WRITE, target=FILE), rồi gọi qua dispatcher; dispatcher chạy native post-write invalidation. Gọi method adapter/gRPC trực tiếp từ tool sẽ bỏ mất bước này và không thuộc thiết kế.

[Tool contracts/token audit đã sửa](tools.md#history-và-filesystemcompute) bỏ expected_version, timeout_seconds, limit/max_lines khỏi model schema. File versions và execution/page budgets do system/native adapter; agent chỉ chọn ý định, path và vị trí đọc. Không version tracker/registry hoặc schema compatibility cho các args đã bỏ.

file_list depth=1 dùng ListNodes và trả native cursor. depth>1 dùng ReadTree, giữ max_depth/max_nodes của server và trả truncated khi chạm budget; không giả vờ ReadTree có cursor hoặc tự thu thập cả cây. Không nhận cursor của flat listing cho recursive tree.

file_read có ba representation rõ ràng:

- Text: native cached whole-file read rồi format line window/truncation cho model; inline text tuân giới hạn LetFS, không đẩy toàn nội dung cache vào context. Version ở native adapter, không đưa vào model content. Các partial-read fast paths vẫn giữ cho nhu cầu phù hợp; kết quả một đoạn không được fill như whole-file cache.
- Image: native ReadImage preview có giới hạn dimensions, trả image content cho model; không base64 nhét vào stdout hoặc transcript text.
- PDF/DOCX/blob khác: metadata, processing status và artifact tree có giới hạn. Agent đọc text artifacts qua path thực mà LetFS trả. Không tự parse/download toàn blob để đoán text.

Artifact tree dùng tên/node kinds thực của LetFS; không tạo một namespace artifacts tự chế. File/image/shell tools nhận cả ~/... và /mnt/<id>/...; adapter chọn binding tương ứng, giữ containment root của mount đó. Semantic search mặc định home; target external path thì gọi search trong storage/mount tương ứng, không mặc định quét tất cả grants rồi tự merge ranking. Blob transfer nguyên bản thuộc signed-transfer contract của LetFS, không mở binary upload/edit qua shell này.

## 4. Adapter LetFS tối thiểu

| Nhu cầu | Native API hoặc engine |
|---|---|
| stat | Stat |
| readdir / flat list | ListNodes, giữ native pagination/bounded walk |
| recursive model-facing list / blob artifacts | ReadTree, giữ truncated |
| read text / read_text_lines / first_lines / last_lines | ReadText full/lines/head/tail selection tương ứng |
| line_count | ReadText include_metrics với selection nhỏ, không truyền full content chỉ để đếm |
| files_containing / lines_containing | TextSearch files/lines mode khi query/flags có literal semantics tương ứng |
| create text | CreateNode với text content |
| replace / append / literal edit | MutateText mutation tương ứng |
| mkdir -p | CreateDirectories |
| copy / move | CopyNode / MoveNode, source/destination storage và containment root theo từng mount |
| rm / rmdir | TrashNode theo native node/tree semantics |
| image preview | ReadImage |
| semantic search | SemanticSearch |
| regex/glob/text transforms của shell | Engine Mirage trên native VFS reads |

Đã chốt giữ native fast-path hooks: read_text_lines/first_lines/last_lines/line_count, files_containing/lines_containing cho literal query, write/append/edit, mkdir/remove và copy/copy_from/dir_copy/rename. read_tree dùng native ReadTree; semantic search dùng native SemanticSearch. Viết mới hooks theo pinned Mirage signatures và proto mới, không copy adapter cũ. Cache-aware native read path được ưu tiên khi đã có content; một custom hook không tự nhiên được file cache trả lời chỉ vì đi qua dispatch. Native mutation trả Node thì dùng ngay response; không mặc định Stat lại sau mỗi write. Không implement toàn bộ hook catalog để đạt POSIX coverage hoặc checksum RPC không tồn tại.

Text của LetFS là UTF-8 không NUL; sample config core giới hạn 256 KiB/file. Adapter tuân theo limit thực của server, không giữ giới hạn 1 MiB từ archive làm authority mới. Bytes từ một shell write phải decode UTF-8 hợp lệ trước gửi native text API; binary/hole writes trả unsupported/invalid rõ ràng.

VFS read không advertise arbitrary native byte ranges. Fallback dùng ReadText đầy đủ cho text file có giới hạn, encode UTF-8, để Mirage slice bytes khi cần. Các hooks lines/head/tail gọi native selection, không đi vòng full read. Native ReadText byte range không cho cắt giữa ký tự UTF-8; không viết thuật toán vá range.

Không emulation pwrite/truncate zero-fill, symlink/hardlink, executable binaries hoặc tail-follow vô hạn. Nếu cần một hook truncate cho text replacement thì chỉ native truncate-shrink hợp lệ; không thêm sparse/binary storage. Các chương trình phải thấy lỗi khi behavior không được hỗ trợ.

Regex của rg/grep giữ bởi Mirage; native TextSearch fast paths chỉ nhận input/flags thật sự có semantics literal tương ứng. Những mode chưa tương thích dùng Mirage fallback, không đổi regex thành literal rồi trả kết quả sai. LetFS SearchFiles/TextSearch file mode dùng LIKE/ILIKE với GIN pg_trgm; lines mode chọn matching lines trong một file có giới hạn. Đây là literal substring search, không tokenized PostgreSQL FTS hoặc fuzzy similarity search. Không tự viết regex/search engine, cross-mount merge hoặc reciprocal-rank fusion. SemanticSearch gọi LetFS đúng một owning search pipeline; không query Qdrant/rerank từ Leta.

gRPC errors được map một lần sang native VFS errors thích hợp: missing, permission denied, conflict, invalid input, quota và transient transport failure. Không đổi permission/quota/conflict thành file rỗng hoặc success; không dựng error taxonomy/framework riêng.

## 5. Cache bounded native đã chốt

Dùng RedisCacheConfig cho content và RedisIndexConfig cho metadata/listings, cùng Redis của Leta. ReadSpec dùng ReadPolicy.BOUNDED. Mirage 0.0.8 khai báo DEFAULT_READ_TTL=600 và IndexConfig.ttl=600; dùng 600 giây làm default ban đầu, không phải kết quả benchmark hoặc khẳng định tối ưu cho mọi workload. Rút số 5 giây tự đề xuất. Content TTL được stamp khi fill; warm reads không kéo dài đời bản cũ.

| Operation | Cache hit | Cache miss / expiry |
|---|---|---|
| file_read / native whole-file read | Dùng bytes, format window; không remote Stat/auth/version check | Adapter ReadText, native path fill cache |
| file_list / ls | Dùng listing/metadata native khi đủ dữ liệu cần trả | ListNodes/ReadTree theo page/depth/budgets; giữ partial/truncated đúng nghĩa |
| head/tail/line operations | Dùng cached read khi native path hỗ trợ | Native selection/metrics hook; partial response không là whole-file cache |
| file_write / file_edit | Vẫn ghi đồng bộ về LetFS | Vẫn ghi đồng bộ về LetFS |
| semantic search / image hook | Không hứa dùng text cache để trả representation khác | Native owning API qua dispatcher/adapter; không result-cache mới |

Cache hit nghĩa là đủ dữ liệu/metadata mà operation cần. Nếu thiếu metadata để xác định node/representation thì lấy metadata cần thiết; không thêm call chỉ để xin phép đọc cached bytes. LetFS kiểm quyền/containment/quota/version trong request đọc mới hoặc mutation. Sau revoke, dữ liệu đã đọc có thể dùng tới expiry/unmount; không hứa immediate cache revocation hoặc thêm permission cache.

Content cache dùng prefix ổn định theo root agent và home binding; native index scope phân biệt từng mount/binding. Hai Leti cùng box có thể share prefix, root/box khác không trộn /home dù virtual path giống nhau. Prefix giữ ổn định qua tool batches/retries; không mount fingerprint/observed-ID registry hoặc SQL cache table. Namespace/history/control của Mirage vẫn ephemeral, không hydrate session cũ từ Redis.

Mọi mutation đi qua dispatcher. Built-in writes dùng native post-write bookkeeping; custom write_text/edit_text khai báo WRITE để dispatcher invalidate content và metadata/listings liên quan. Dùng native path giữ bytes vừa ghi khi thư viện có sẵn; custom atomic edit chỉ trả metadata thì invalidate, không tự đọc lại để refill. Không Stat sau mutation để xác nhận response đã trả.

Invalidation áp dụng trong cùng cache namespace. Root/box khác hoặc caller ngoài Mirage có thể sửa cùng file qua view khác; chấp nhận dữ liệu cũ tới TTL. TTL phục vụ data freshness, không check quyền mỗi lần đọc. Không invalidation bus, revision table, fingerprint policy trước cache hit hoặc custom cache engine. LetFS files.version cho concurrency vẫn giữ, nhưng không dùng nó làm lý do revalidate mọi cached read.

Redis server có memory limit/eviction; RedisCacheConfig.limit chỉ advisory trong phiên bản đã đọc, không hard per-agent memory cap. Dùng native stores và server limits, không thêm cache accounting job. Mất cache thì đọc lại từ LetFS; cache không là recovery authority.

## 6. Shell và Python execution

Lệnh text/filesystem có sẵn của Mirage đủ cho bước đầu: ls/cat/head/tail/rg/grep, pipes/redirection, mkdir/cp/mv/rm và các text processors thực sự được pinned version hỗ trợ. Cú pháp và command catalog lấy từ thư viện, không quảng cáo đủ GNU Bash/POSIX.

Chỉ bật native command families cần cho các tác vụ trên và python/Monty; dùng CommandsBlock allow của Mirage, có cả builtins cần thiết. Không tự viết parser/deny-list bằng regex. Chương trình không có host FS, host env, socket/network hoặc arbitrary Python external callbacks. Không inject native clients/credentials vào Monty; chỉ adapter runtime mới có trusted clients.

Network policy của sandbox tách khỏi native transport của adapter: model không được cấp network chỉ vì worker cần gọi LetFS/OpenRouter. Không đưa signed URLs, DB DSN, Redis URL hoặc token vào shell env. Không nối shell fallback sang subprocess, SSH, host /bin/bash, pip hoặc arbitrary external commands khi lệnh không hỗ trợ.

Trong một exec_shell, cwd/env thay đổi có tác dụng cho chính command/script đó. Mỗi tool call bắt đầu từ cwd explicit hoặc /home và clean virtual env có HOME; không có implicit cd/export qua các tool calls. exec_python cũng bắt đầu ở /home. Chỉ files là state bền vững; biến Python/process không sống qua call/batch/restart.

Dùng native memory/time/output/walk budgets, không xây collector hoặc watchdog mới:

- Timeout do runtime policy, điểm khởi đầu 30 giây và được cap bởi operation deadline/cancellation budget; model không có timeout argument để tăng ceiling.
- Memory budget hữu hạn cho Mirage và Monty; Monty 16 MiB là điểm khởi đầu theo runtime cũ, chưa phải kết quả benchmark.
- Stdout/stderr và traversal có giới hạn; return native truncation/timeout indicators rõ ràng, không báo kết quả đầy đủ khi thiếu dữ liệu. Image preview có native dimension limit riêng.
- Không giữ background job phục vụ tool call sau khi đã trả result. Cancel/timeout đóng execution và chờ native cleanup/write settlement trước khi release writer barrier.

Giới hạn output cho model không được cắt nội dung file write rồi lưu bản thiếu. File write phải nhận đủ payload hợp lệ hoặc fail theo text/quota budget; các side effects trước khi command lỗi vẫn giữ semantics non-atomic bên dưới.

## 7. Lifetime, nhiều năm và Temporal

Native gRPC clients/pools thuộc worker process. run_agent có thể chạy dài và heartbeat, không đóng activity theo chu kỳ năm phút. Mirage Workspace/session mở theo tool batch rồi đóng; RAM buffers/session history không sống theo tuổi đời activity. Redis content/index cache tái dùng qua batches với prefix ổn định và TTL; mount discovery result giữ trong runtime để refresh lazily. Các tool calls cùng batch dùng cùng bindings/cache; chờ tất cả executions/writes settle trước khi close.

```text
run_agent giữ writer lock và cùng native graph thread
  → trước model call: bounded inbox middleware, control/model refresh
  → trước tools node: mở Workspace, bind home/external mounts, Monty và budgets
  → chạy tool batch, sync checkpoint/public projection, settle và close Workspace
  → tiếp tục model/tools khi còn việc; compaction/prune ngay trong activity
  → idle/pause/cancel: cleanup rồi nhả writer lock
Workflow chỉ rollover khi native suggestion ở workflow events
```

Khi rollover thật sự cần trong lúc runtime bận, workflow dùng native cancellation với WAIT_CANCELLATION_COMPLETED. Runner bảo vệ bước đang chạy tới checkpoint/public projection, đóng workspace/settle writes và nhả lock rồi mới ACK cancellation. Không model/tool timeout giả để ép rollover hoặc yield RPC/SQL flag riêng. User cancel/stop giữ domain semantics; technical rotation không kết thúc logical UI run.

Không đóng shared client vì một batch kết thúc. Cwd/env/session history không cần chuyển qua activity retry/CAN. Context/checkpoints do native saver giữ, file tree do LetFS giữ. Không thêm workflow/activity cho từng shell/file operation hoặc sandbox lifecycle service.

## 8. Concurrency và retry: giữ đúng giới hạn

Root và Leti có thể cùng sửa files trong box. file_edit dùng native atomic literal replacement: old_text phải khớp, default unique và giữ phần nội dung khác; conflict thì đọc lại. Low-level hooks cần read-modify-write trong một operation tự truyền native expected_version từ chính read đó; không model-managed version hoặc registry qua activity retries/restarts. Explicit file_write(overwrite=true) và shell redirection là full replace, không hứa auto-merge hoặc bảo vệ snapshot model đã đọc từ lâu bằng một fresh Stat. Existence/version/read-only/quota vẫn LetFS enforce tại mutation.

Đã chốt: current version persist tại LetFS.files.version. expected_version chỉ giữ trong RAM/local variable từ read tới mutation của chính adapter operation, không persist trong SQL/Redis/checkpoint Leta. Conflict trả về để đọc lại, không lấy version mới để ép original write thành công. file_read ở lượt trước rồi explicit file_write(overwrite=true) ở lượt sau không có snapshot guard; đây là semantics full replace được chấp nhận, không thêm version registry hoặc tiếp tục coi đây là một design decision còn mở.

Retry transport của một native mutation giữ nguyên request_id và canonical payload đã chuẩn bị. IDs cho một direct tool mutation có thể dựa tool-call identity; chỉ dedupe cùng request trong receipt horizon core. Không lấy cùng ID gắn cho payload khác, đổi key sau ambiguous ACK hoặc hứa dedupe vĩnh viễn. Permission/conflict/invalid/quota errors không tự retry thành thao tác khác.

Recovery quá horizon đã chốt: dùng timestamp của checkpoint chứa pending tool để lấy conservative age, không dùng ngày tạo agent/logical run. Pending mutation đã vượt receipt guarantee không tự phát lại; báo kết quả chưa xác định thay vì success hoặc đổi key rồi thử lại. Read-only recovery không cần receipt; shell/Python có thể mutate nên pending execution quá hạn đi cùng error path. Kiểm tra ở recovery boundary, không poll/timer hoặc thêm table/service/workflow. Khôi phục trong horizon vẫn phải giữ canonical key/payload và các giới hạn multi-effect script bên dưới.

Một shell script gồm nhiều RPC không atomic và không exactly-once. Ví dụ hai append, append đầu commit rồi worker chết trước checkpoint: replay tool có thể lặp append. Nếu request bị dựng lại với version/payload khác, receipt có thể conflict thay vì âm thầm dedupe. Không thêm per-command counter ledger, filesystem saga hoặc custom tool journal để che giới hạn này.

Đây là giới hạn có chủ ý cho tác vụ tài liệu; các action tài chính/irreversible bên ngoài hệ thống phải đi qua owning domain tool với receipt riêng. Khi cần đảm bảo một mutation text cụ thể, dùng direct edit/write API thay vì gói nhiều side effects vào shell. Không nâng guarantee của toàn script lên từ guarantee của một native mutation.

rm đưa vào trash; không expose purge trong shell. Artifact descendants readonly do LetFS bảo vệ. Directory copy/move/trash dùng native behavior/budgets, không viết recursive mutator trong Leta. Quyền và containment luôn ở server, không phụ thuộc model có tuân system prompt.

## 9. Folder structure và tests cần thiết

Phần filesystem đã chốt chỉ cần:

```text
src/leta/filesystem/
  workspace.py       # home/mount refresh, Redis content/index configs, Mirage/Monty, lifetime
  letfs.py           # concrete native VFS adapter + bounded image/search helpers
src/leta/runtime/
  tools.py           # schemas và calls trực tiếp, cùng các tools feature khác
tests/
  test_filesystem.py # essential behavior, không một file cho mỗi VFS hook
```

Không tạo policy.py, factories/repositories cho nhiều backend, shell gateway, custom process manager hoặc persistent session tables. Không thêm cột/bảng filesystem trong SQL Leta; storage_id/home_node_id hiện tại và native file.version là đủ.

Viết tests mới theo behavior, dùng một dependency environment chia sẻ:

1. Root/Leti thấy đúng home và external mounts; ~ expansion hoạt động. Public mount mặc định read, HITL private mount xuất hiện sau grant và biến mất sau revoke/refresh. Path traversal/raw ID/copy/move không thoát containment; không có external alias mở root home cho Leti. Hai Leti cùng box chia sẻ được home.
2. Read–warm hit–atomic edit–read qua file tools/shell/Python dùng chung dispatcher; warm hit không có remote Stat/auth, mutation invalidates và đọc sau thấy thay đổi. Reuse cache qua batch, TTL refresh external edits; fresh backend request sau revoke bị từ chối, cached bytes không đòi immediate revocation. Kiểm integration wiring, không test lại mọi cache internal của Mirage.
3. Một text create/edit/version-conflict roundtrip, rm thành trash và write vào artifact readonly bị chặn. Một small adapter spy check xác nhận head/lines/literal search/copy chọn đúng native APIs và selections; regex fallback không dùng literal fast path. Không test mọi command/flag của Mirage.
4. Một pipeline Mirage thật và một Monty program đọc/ghi cùng mount; timeout/cancel đóng session/settle writes, không ảnh hưởng shared clients.

Không per-command compatibility matrix, old fixture replay, paid model call hoặc start cả stack riêng cho từng case. Các tests trên là implementation acceptance, chưa chạy trong lượt đề xuất này.

## 10. Đối chiếu nguồn và điều chưa kiểm

Đã đọc bốn archive files [workspace](../../archive/2026-11-11/apps/leta/src/leta/filesystem/workspace.py), [VFS](../../archive/2026-11-11/apps/leta/src/leta/filesystem/letfs_vfs.py), [tools](../../archive/2026-11-11/apps/leta/src/leta/filesystem/tools.py), [policy](../../archive/2026-11-11/apps/leta/src/leta/filesystem/access_policy.py), tổng 998 lines, và tool schemas/dependency manifest cũ. Không copy implementation/tests.

Đối chiếu [native LetFS proto](../../packages/contracts/proto/openlet_api/letfs/v1/letfs.proto), selected active handlers và core plan. Mirage API đã đối chiếu public wheel [0.0.8](https://pypi.org/project/mirage-ai/0.0.8/): VFS hooks, CommandsBlock.allow, native output/time budgets, RedisCacheConfig/RedisIndexConfig, ReadSpec/IndexConfig defaults 600, bounded reconciler, session.vfs read/write/dispatch, high-level tool edit và dispatcher custom WRITE invalidation. RAM control stores/Monty giữ nguyên. Wheel chỉ đọc source, không install/update dependency.

Chưa chạy Mirage/Monty/native services hoặc benchmark. Native cache/adapter wiring, same-namespace invalidation, command cancellation/settlement và pinned command catalog cần focused integration khi implementation. Defaults TTL/mount refresh là tuning, không decision kiến trúc còn mở. Không sửa database, archive source, shared contracts, active Zed hoặc dependencies trong lượt này.
