# Đề xuất VFS, shell và Python sandbox của Leta

Ngày 2026-11-12. Đây là thiết kế đề xuất, chưa triển khai. Một storage_id là home binding bền vững, không phải giới hạn agent chỉ truy cập một storage. Giữ dynamic mounts cho public/shared và private storages được cấp quyền theo [kiến trúc](design.md#10-filesystem-và-cache) và [native APIs](boundaries.md#5-file-operations-mounts-và-cache). Đề xuất giản lược mới: không dùng persistent file cache ở bản đầu; nếu chốt, bỏ filesystem/policy.py khỏi folder structure. Không đổi schema, Temporal inventory hoặc transport Leta đang hoãn.

## 1. Mục tiêu và quyết định

Agent thao tác tài liệu, tìm kiếm, xử lý text và tính toán trong một filesystem bền vững. Giữ Mirage làm virtual shell/VFS engine, Monty làm Python sandbox, LetFS làm owner của dữ liệu và quyền. Viết mới adapter từng dòng; archive chỉ cho biết behavior cần giữ và cơ chế cần bỏ.

run_shell là shell ảo có cú pháp Bash do Mirage hỗ trợ, không phải /bin/bash trên host. run_python là Python subset của Monty, không phải một CPython environment có thể pip install. Không tạo terminal service, container cho từng agent, FUSE mount hoặc durable process manager.

```text
Agent tools
  ├─ run_shell / run_python → Mirage shell / Monty
  │                            └─ Mirage VFS operations
  └─ files / image / search ─────────────┐
                                       ↓
                          concrete LetFS adapter
                                       ↓ native gRPC
                                     LetFS
```

Một adapter inject binding/actor cho mọi call. Mirage sở hữu parser, pipes, redirection, glob và lệnh có sẵn. LetFS sở hữu auth, live tree/containment, readonly artifacts, content/version, quota, receipts và blob processing. Leta không xây thêm bản sao của hai engine này.

## 2. Mount và identity

Mỗi root giữ workspace_id/storage_id làm home binding như schema đã duyệt. Các storage đọc được khác được discover từ LetFS và mount trong RAM; không thêm mount/grant table. Adapter nhận actor và các bindings đã authorize từ runtime, không nhận actor/root tùy ý từ model.

| Execution | Actor gửi LetFS | Mount /home |
|---|---|---|
| Root Leta A | agent:A | storage root lấy từ GetStorage |
| Leti trong box B | agent:A | box.home_node_id của cùng storage |

Đường dẫn hướng agent dùng ~ và ~/path. Virtual HOME/cwd mặc định là /home; Mirage native expand_tilde hỗ trợ ~ và ~/... qua HOME. Tool nhận path dùng cùng native expansion trước routing. Không mount một directory tên literal ~ hoặc tự viết shell expander. pwd vẫn trả absolute path; Python open không tự expand ~ nên dùng relative path từ home hoặc explicit expansion.

Hai Leti cùng box chia sẻ home; hai box khác nhau có containment roots khác nhau. Root nhìn toàn home storage của nó, kể cả các box homes bên trong. Đây là isolation theo box, không phải mỗi Leti một storage/quyền graph riêng.

Virtual /home được đổi thành locator tương đối bên dưới mount root. Mọi NodeLocator mang root_node_id, kể cả node_id trực tiếp và cwd_node_id. Copy/move inject root cho cả source và destination. LetFS resolver kiểm live ancestry; chuẩn hóa đường dẫn phía Leta chỉ phục vụ routing, không thay server enforcement.

Giữ các external mounts theo một quy tắc đường dẫn ổn định:

```text
~                         # home của root hoặc box
/mnt/<public-storage-id>  # public/shared trong cùng workspace
/mnt/<private-storage-id> # private đã cấp viewer/editor cho root agent
```

Tên storage là metadata hiển thị, ID làm mount key để rename không đổi đường dẫn. Không cần /users/<owner> hoặc personal resolver vì một user có thể có nhiều storages. Public chỉ trong workspace, mặc định read; write cần owner/editor. Private được share trực tiếp hoặc qua HITL dùng cùng quy tắc mount.

Discovery gọi ListStorages(workspace_id) bằng root agent, không owned_only và không dùng quyền của human owner. Follow native pagination đến hết kể cả page không có visible items nhưng còn next_page_token. Response có root_node_id/capabilities, không N+1 GetStorage cho mỗi item. Loại home storage_id khỏi external mounts: đặc biệt không tạo /mnt/<home-storage-id> cho Leti vì alias đó sẽ mở lại toàn home storage, vượt box containment.

Refresh lúc mở slice và trước tool batch ở safe boundaries, gồm sau khi nhận HITL result; không đổi mount giữa command đang chạy. So mount map với discovery rồi dùng Mirage add_mount/unmount/set_mount_mode có sẵn. Public/storage share mới xuất hiện khi refresh; revoke/delete bị LetFS chặn ở native operation và mount được gỡ ở refresh tiếp theo. Mount mode/capabilities không là permission authority hoặc local grant mirror.

Accepted HITL cấp root agent quyền vào storage đích qua SetStorageAccess; refresh tiếp theo đưa storage đó vào /mnt. Mọi Leti dùng root actor nên có cùng external grants; chỉ home riêng chịu box containment. Không mount home storage của root dưới alias khác. Không thay root.storage_id, không thêm workflow/activity cho mounting, không cần user chạy mount thủ công hoặc vòng polling nền. Việc đổi home binding vẫn là tính năng khác đang hoãn. Những virtual views Mirage cần cho engine không được ánh xạ sang host disk.

Home phải provision xong trước khi box active và trước khi runtime mở session. VFS không ngầm tạo box home, chọn ID thay lifecycle hoặc thay nullability schema; hợp đồng provisioning còn được theo dõi ở boundaries.md.

## 3. Bảy tools cho agent

| Tool | Input chính | Behavior |
|---|---|---|
| list_files | path=~, depth=1, limit=100, cursor | Metadata; flat listing có native page token; recursive tree có truncated |
| read_file | path, start_line=1, max_lines=200 | Text window; image thành multimodal image; blob khác thành descriptor/artifact references |
| write_file | path, content, overwrite=false | Tạo UTF-8 text; file có sẵn chỉ ghi đè khi explicit |
| edit_file | path, old_text, new_text, replace_all=false | Native literal replace; mặc định phải khớp đúng một chỗ |
| run_shell | command, cwd=~, timeout_seconds=30 | Chạy command/pipeline trong Mirage; trả native result/output có budget |
| run_python | code, timeout_seconds=30 | Chạy Monty qua native runtime integration, cùng /home |
| semantic_search | query, paths, limit=10 | Native LetFS SemanticSearch dưới mount được chọn; mặc định home |

Tool definitions đặt trong runtime/tools.py. File operations gọi concrete adapter hoặc Mirage VFS dispatch tương ứng, dùng chung binding và native contracts; không thêm FilesystemTools façade hoặc xây shell string cho từng file tool. run_python dùng native Mirage/Monty integration, không host subprocess.

list_files depth=1 dùng ListNodes và trả native cursor. depth>1 dùng ReadTree, giữ max_depth/max_nodes của server và trả truncated khi chạm budget; không giả vờ ReadTree có cursor hoặc tự thu thập cả cây. Không nhận cursor của flat listing cho recursive tree.

read_file có ba representation rõ ràng:

- Text: nội dung và line window/version, không tự cắt âm thầm rồi báo đã đọc cả file.
- Image: native ReadImage preview có giới hạn dimensions, trả image content cho model; không base64 nhét vào stdout hoặc transcript text.
- PDF/DOCX/blob khác: metadata, processing status và artifact tree có giới hạn. Agent đọc text artifacts qua path thực mà LetFS trả. Không tự parse/download toàn blob để đoán text.

Artifact tree dùng tên/node kinds thực của LetFS; không tạo một namespace artifacts tự chế. File/image/shell tools nhận cả ~/... và /mnt/<id>/...; adapter chọn binding tương ứng, giữ containment root của mount đó. Semantic search mặc định home; target external path thì gọi search trong storage/mount tương ứng, không mặc định quét tất cả grants rồi tự merge ranking. Blob transfer nguyên bản thuộc signed-transfer contract của LetFS, không mở binary upload/edit qua shell này.

## 4. Adapter LetFS tối thiểu

| Nhu cầu | Native API hoặc engine |
|---|---|
| stat | Stat |
| readdir / flat list | ListNodes, giữ native pagination/bounded walk |
| recursive model-facing list / blob artifacts | ReadTree, giữ truncated |
| read text | ReadText |
| create text | CreateNode với text content |
| replace / append / literal edit | MutateText mutation tương ứng |
| mkdir -p | CreateDirectories |
| copy / move | CopyNode / MoveNode, source/destination storage và containment root theo từng mount |
| rm / rmdir | TrashNode theo native node/tree semantics |
| image preview | ReadImage |
| semantic search | SemanticSearch |
| regex/glob/text transforms của shell | Engine Mirage trên native VFS reads |

Chỉ implement optional VFS hooks cần để giữ behavior hoặc tránh một chuỗi RPC rõ ràng như append/copy/move. Native mutation trả Node thì dùng ngay response; không mặc định Stat lại sau mỗi write. Không implement toàn bộ hook catalog để đạt POSIX coverage.

Text của LetFS là UTF-8 không NUL; sample config core giới hạn 256 KiB/file. Adapter tuân theo limit thực của server, không giữ giới hạn 1 MiB từ archive làm authority mới. Bytes từ một shell write phải decode UTF-8 hợp lệ trước gửi native text API; binary/hole writes trả unsupported/invalid rõ ràng.

VFS read không advertise arbitrary native byte ranges. Bản đầu dùng ReadText đầy đủ cho text file có giới hạn, encode UTF-8, để Mirage slice bytes khi cần. Native ReadText byte range không cho cắt giữa ký tự UTF-8; không viết thuật toán vá range. read_file line windows có thể gọi native line selection trực tiếp.

Không emulation pwrite/truncate zero-fill, symlink/hardlink, executable binaries hoặc tail-follow vô hạn. Nếu cần một hook truncate cho text replacement thì chỉ native truncate-shrink hợp lệ; không thêm sparse/binary storage. Các chương trình phải thấy lỗi khi behavior không được hỗ trợ.

Regex của rg/grep giữ bởi Mirage; không đổi regex thành native literal TextSearch rồi trả kết quả sai. Bản đầu chưa cần native search fast path cho shell. TextSearch chỉ được dùng khi input/flags thật sự có semantics literal tương ứng. Không tự viết regex/search engine, cross-mount merge hoặc reciprocal-rank fusion. SemanticSearch gọi LetFS đúng một owning search pipeline; không query Qdrant/rerank từ Leta.

gRPC errors được map một lần sang native VFS errors thích hợp: missing, permission denied, conflict, invalid input, quota và transient transport failure. Không đổi permission/quota/conflict thành file rỗng hoặc success; không dựng error taxonomy/framework riêng.

## 5. Cache: đề xuất bỏ persistent file cache ở bản đầu

Baseline trước đây giữ Redis file cache, native Stat/version và policy trước cache hits. Đề xuất mới cấu hình file-content cache của Mirage bằng 0, không RedisCacheConfig hoặc cache dùng chung qua slices. Dùng RAM control/session state mặc định trong lifetime workspace, bỏ nó khi đóng. Redis của Leta vẫn dùng cho public events theo plan riêng.

Lý do: file text đã nhỏ và nằm trong PostgreSQL LetFS; một cache hit đúng quyền vẫn cần native admission. Chưa có số đo chứng minh phần tiết kiệm bytes đáng đổi lấy policy/fingerprint/invalidation machinery. Đây là lựa chọn đơn giản hơn, không phải kết luận rằng cache không bao giờ hữu ích.

Kết quả: mỗi read mới lấy dữ liệu qua owning LetFS API; không cache quyền/listings/artifact descriptors hoặc dùng RAM snapshot làm authorization authority. RAM buffers trong command đang chạy vẫn cần thiết, giống bytes đã được giao cho caller; không hứa thu hồi dữ liệu đã đọc khi quyền đổi giữa một operation.

Không dựng observed-ID registry, fingerprint table, mount digest, cache namespace lifecycle, content invalidation bus hoặc cache fallback mode. Session/command-local metadata chỉ phục vụ operation đang chạy; không reuse nó để bỏ admission ở tool tiếp theo. Native Mirage history/session views là ephemeral, không hydrate chúng từ agent cũ hoặc biến thành storage thứ hai.

Điều kiện bắt buộc để dùng cấu hình này: real Mirage integration phải xác nhận read/write/copy/derived reads ở cache=0 không phục vụ persistent snapshots ngoài native admission. Nếu thư viện cần một ephemeral working buffer thì dùng buffer có lifetime command/slice; không âm thầm bật lại Redis cache để làm test xanh.

Nếu đo được read traffic là bottleneck thực, lần tối ưu sau mới cân nhắc bounded text cache. Khi đó cache hit vẫn native Stat với quyền read/containment, token tối thiểu node.id + file.version và read response version; không cache blob artifact tree bằng source-file version vì processing có thể thay cây mà không đổi source version. Chưa viết policy.py hoặc cache optimization trong bản đầu này.

## 6. Shell và Python execution

Lệnh text/filesystem có sẵn của Mirage đủ cho bước đầu: ls/cat/head/tail/rg/grep, pipes/redirection, mkdir/cp/mv/rm và các text processors thực sự được pinned version hỗ trợ. Cú pháp và command catalog lấy từ thư viện, không quảng cáo đủ GNU Bash/POSIX.

Chỉ bật native command families cần cho các tác vụ trên và python/Monty; dùng CommandsBlock allow của Mirage, có cả builtins cần thiết. Không tự viết parser/deny-list bằng regex. Chương trình không có host FS, host env, socket/network hoặc arbitrary Python external callbacks. Không inject native clients/credentials vào Monty; chỉ adapter runtime mới có trusted clients.

Network policy của sandbox tách khỏi native transport của adapter: model không được cấp network chỉ vì worker cần gọi LetFS/OpenRouter. Không đưa signed URLs, DB DSN, Redis URL hoặc token vào shell env. Không nối shell fallback sang subprocess, SSH, host /bin/bash, pip hoặc arbitrary external commands khi lệnh không hỗ trợ.

Trong một run_shell, cwd/env thay đổi có tác dụng cho chính command/script đó. Mỗi tool call bắt đầu từ cwd explicit hoặc /home và clean virtual env có HOME; không có implicit cd/export qua các tool calls. run_python cũng bắt đầu ở /home. Chỉ files là state bền vững; biến Python/process không sống qua call/slice/restart.

Dùng native memory/time/output/walk budgets, không xây collector hoặc watchdog mới:

- Timeout mặc định 30 giây; giá trị tool yêu cầu phải nằm trong ceiling hữu hạn của runtime và được cap bởi remaining slice/cancellation deadline.
- Memory budget hữu hạn cho Mirage và Monty; Monty 16 MiB là điểm khởi đầu theo runtime cũ, chưa phải kết quả benchmark.
- Stdout/stderr và traversal có giới hạn; return native truncation/timeout indicators rõ ràng, không báo kết quả đầy đủ khi thiếu dữ liệu. Image preview có native dimension limit riêng.
- Không giữ background job phục vụ tool call sau khi đã trả result. Cancel/timeout đóng execution và chờ native cleanup/write settlement trước khi release writer barrier.

Giới hạn output cho model không được cắt nội dung file write rồi lưu bản thiếu. File write phải nhận đủ payload hợp lệ hoặc fail theo text/quota budget; các side effects trước khi command lỗi vẫn giữ semantics non-atomic bên dưới.

## 7. Lifetime, nhiều năm và Temporal

Native gRPC clients/pools thuộc worker process, chia sẻ đúng lifetime của process. Mirage Workspace/session thuộc một run_agent slice hữu hạn; không tạo một sandbox/terminal sống cả năm cho mỗi agent.

```text
run_agent lấy writer lock theo thiết kế runtime
  → đọc active root/box và home binding
  → mở ephemeral Workspace, bind home, discover external mounts, Monty và budgets
  → chạy các tool calls trong native graph slice
  → checkpoint tại safe boundaries
  → cancel/settle executions còn lại, close workspace trong finally
  → release writer lock; return slice outcome
Agent workflow dispatch slice sau hoặc Continue-As-New như thiết kế đã chốt
```

Không đóng shared client vì một session kết thúc. Cwd/env/cache/session history không cần chuyển qua Continue-As-New. Agent logical context/checkpoints do native saver giữ; file tree do LetFS giữ. Đóng session mỗi slice khiến runtime resource lifetime hữu hạn kể cả agent luôn bận nhiều năm.

Không thêm workflow/activity cho từng shell/file operation. Các calls nằm trong run_agent activity, dùng cancellation/heartbeat/writer barrier đã có. Sandbox không là owner của checkpoint hoặc scheduler.

## 8. Concurrency và retry: giữ đúng giới hạn

Root và Leti có thể cùng sửa files trong box. Targeted edit/read-modify-write truyền native expected_version từ lần đọc liên quan; conflict trả cho agent đọc lại, không tự rebase hoặc overwrite lại. Explicit write_file(overwrite=true) và shell redirection là chủ ý replace; không giả vờ đó là merge. Các điều kiện existence/version/read-only/quota để LetFS enforce tại mutation.

Retry transport của một native mutation giữ nguyên request_id và canonical payload đã chuẩn bị. IDs cho một direct tool mutation có thể dựa tool-call identity; chỉ dedupe cùng request trong receipt horizon core. Không lấy cùng ID gắn cho payload khác, đổi key sau ambiguous ACK hoặc hứa dedupe vĩnh viễn. Permission/conflict/invalid/quota errors không tự retry thành thao tác khác.

Một shell script gồm nhiều RPC không atomic và không exactly-once. Ví dụ hai append, append đầu commit rồi worker chết trước checkpoint: replay tool có thể lặp append. Nếu request bị dựng lại với version/payload khác, receipt có thể conflict thay vì âm thầm dedupe. Không thêm per-command counter ledger, filesystem saga hoặc custom tool journal để che giới hạn này.

Đây là giới hạn có chủ ý cho tác vụ tài liệu; các action tài chính/irreversible bên ngoài hệ thống phải đi qua owning domain tool với receipt riêng. Khi cần đảm bảo một mutation text cụ thể, dùng direct edit/write API thay vì gói nhiều side effects vào shell. Không nâng guarantee của toàn script lên từ guarantee của một native mutation.

rm đưa vào trash; không expose purge trong shell. Artifact descendants readonly do LetFS bảo vệ. Directory copy/move/trash dùng native behavior/budgets, không viết recursive mutator trong Leta. Quyền và containment luôn ở server, không phụ thuộc model có tuân system prompt.

## 9. Folder structure và tests cần thiết

Nếu chốt đề xuất cache=0, phần filesystem chỉ cần:

```text
src/leta/filesystem/
  workspace.py       # home + native dynamic mount refresh, Mirage/Monty, lifetime/budgets
  letfs.py           # concrete native VFS adapter + bounded image/search helpers
src/leta/runtime/
  tools.py           # schemas và calls trực tiếp, cùng các tools feature khác
tests/
  test_filesystem.py # essential behavior, không một file cho mỗi VFS hook
```

Không tạo policy.py, factories/repositories cho nhiều backend, shell gateway, custom process manager hoặc persistent session tables. Không thêm cột/bảng filesystem trong SQL Leta; storage_id/home_node_id hiện tại và native file.version là đủ.

Viết tests mới theo behavior, dùng một dependency environment chia sẻ:

1. Root/Leti thấy đúng home và external mounts; ~ expansion hoạt động. Public mount mặc định read, HITL private mount xuất hiện sau grant và biến mất sau revoke/refresh. Path traversal/raw ID/copy/move không thoát containment; không có external alias mở root home cho Leti. Hai Leti cùng box chia sẻ được home.
2. Qua Mirage cache=0, read mới sau content change/revoke không trả snapshot cũ/bypass owning admission; kiểm cả copy/derived reads. Không test Redis file cache đã bỏ.
3. Một text create/edit/version-conflict roundtrip, rm thành trash và write vào artifact readonly bị chặn.
4. Một pipeline Mirage thật và một Monty program đọc/ghi cùng mount; timeout/cancel đóng session/settle writes, không ảnh hưởng shared clients.

Không per-command compatibility matrix, old fixture replay, paid model call hoặc start cả stack riêng cho từng case. Các tests trên là implementation acceptance, chưa chạy trong lượt đề xuất này.

## 10. Đối chiếu nguồn và điều chưa kiểm

Đã đọc bốn archive files [workspace](../../archive/2026-11-11/apps/leta/src/leta/filesystem/workspace.py), [VFS](../../archive/2026-11-11/apps/leta/src/leta/filesystem/letfs_vfs.py), [tools](../../archive/2026-11-11/apps/leta/src/leta/filesystem/tools.py), [policy](../../archive/2026-11-11/apps/leta/src/leta/filesystem/access_policy.py), tổng 998 lines, và tool schemas/dependency manifest cũ. Không copy implementation/tests.

Đối chiếu [native LetFS proto](../../packages/contracts/proto/openlet_api/letfs/v1/letfs.proto), selected active handlers và core plan. Mirage API đã đối chiếu public wheel [0.0.8](https://pypi.org/project/mirage-ai/0.0.8/): VFS hooks, CommandsBlock.allow, native output/time budgets, file cache configuration, RAM control stores và Monty runtime. Wheel chỉ tải để đọc source, không install/update dependency.

Chưa chạy Mirage/Monty/native services hoặc benchmark. cache=0 với real native adapter, command cancellation/settlement và pinned command catalog cần được kiểm bằng focused integration khi implementation. Không sửa database, archive source, shared contracts, active Zed hoặc dependencies trong lượt này.
