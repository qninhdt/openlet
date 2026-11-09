# Baseline source và audit probes

Revision: `043f4e529b2a014b9a9404cef3fabbc51257b4cc`, branch `dev`, ngày 2026-11-09. Source được giữ nguyên trong toàn bộ audit; chỉ có plan/report và ignored verification artifacts được tạo.

Trạng thái: hoàn tất. Native, focused probes, API/recovery và replay đều PASS. Baseline này không đồng nghĩa các đề xuất refactor đã được triển khai.

## Môi trường

Go 1.27.3, Node 26.13.0, pnpm 12.18.0, uv 0.13.7, Python 3.14.10, Docker Server 29.8.1. Go dùng `/usr/local/go/bin`; Node/uv được gọi từ package/tool environment riêng, không thay bản cài global của người dùng.

Wrapper `pnpm dlx` ngoài cùng báo 12.9.1 ở cuối log; `versions.json` của runner ghi pnpm 12.18.0 bên trong môi trường chạy commands. Không diễn giải phiên bản wrapper thành phiên bản package manager của mọi task.

Lần focused run đầu đạt 29 tests, 2 setup errors vì shell thiếu Go trên PATH. Sau khi dùng toolchain được repo hướng dẫn, hai test đó chạy lại trong full Leta integration và pass. Không sửa test/source để vượt lỗi môi trường này.

## Kết quả

| Gate | Kết quả |
| --- | --- |
| `pnpm exec turbo run build check test test:workflow test:integration --concurrency=1` | PASS, 32/32 tasks, 12m34.929s. Bao gồm contracts drift, E2E typecheck, builds, lint/vet/format và native tests. |
| Leta unit, nằm trong graph trên | 157 passed. |
| Leta integration, nằm trong graph trên | 124 passed, 6 skipped do native-owner/opt-in fixture boundaries, 170 deselected. |
| Script Ruff lint và format | PASS; 12 files format-clean. |
| `uv run --locked --package letfs-ingest pytest scripts -q` | 33 passed. |
| LetFS replay với histories của native integration lần này | PASS. |
| Leta replay | 13 passed. |
| Audit-only persistence probes | 3 passed; chi tiết bên dưới. |
| Parser corpus, offline model cache | 11 passed. |
| Real setup/recovery checks | 3 passed; gồm isolated database+S3 restore và cleanup khi cancel. |
| Playwright API/recovery | PASS, 45/45 tests, 8.3 phút theo Playwright; 500.5s cho command. Bao gồm coordinated restore metadata, exact bytes và interrupted workflow. |
| `OPENLET_HISTORY_DIR=…/.local/api-e2e/histories pnpm test:replay` | PASS, 4/4 tasks: Account, Workspace và LetFS replay fresh API histories; Leta chạy lại 13 fixture replay tests hiện có. Không tuyên bố Leta đã replay API histories từ thư mục này. |

Turbo không dùng task cache; một số native Go package tests được Go đánh dấu `(cached)`. Không diễn giải toàn graph thành một lượt cold/uncached cho mọi package. Các số deselected là marker selection theo package, không phải thất bại.

## Phép thử phục vụ audit

Ba tests ở ignored `.local/audit-261109-2054/test_persistence_probes.py` dùng real PostgreSQL và migrations của Leta. Không sửa implementation. HTTP probe dùng external authorization fake theo test pattern hiện có; không chứng minh một real SpiceDB journey.

- Box metadata với 2 Leti/1 edge: 5 `AsyncCursor.execute` calls, gồm 2 timeout settings và 3 SELECT. `details=False` vẫn trả child rows và edges.
- Pause root đó: 9 execute calls; source trace xác nhận 4 snapshot queries phục vụ dữ liệu không được consumer pause/resume sử dụng.
- Root tạo schedule cho chính nó: 2 root admission locks trong cùng transaction.
- Hai POST schedules với timezone `Invalid/Zone` và keys riêng: hai HTTP 400; SQL còn hai reservations có `expires_at=NULL`, không có schedule được tạo.
- Một execute chứa hai fixed `SET LOCAL`, với `prepare=False`: hai timeout đúng `2s` bên trong transaction; session settings được trả về giá trị cũ khi transaction kết thúc.

Đếm cursor execute không bao gồm BEGIN/COMMIT nội bộ hoặc protocol bookkeeping; không phải latency/round-trip measurement. Probe xác nhận defect/extra work, chưa đo speedup của một implementation mới.

## Commands và artifacts

Log, tool versions, per-command exit codes/thời gian và Store method inventory được giữ trong ignored `.local/audit-261109-2054/`:

- `native.log`, `scripts-lint.log`, `scripts-tests.log`.
- `native-letfs-replay.log`, `leta-replay.log`, `persistence-probes.log`, `parser.log`.
- `setup-recovery.log`, `api.log`, `api-replay.log`, `remaining.log`.
- `versions.json`, `results.json`, `store-inventory.json`, `native-histories/`.

Các gate bổ sung chạy tuần tự bằng audit-only runner; failures được lưu exit code riêng và không bị biến thành PASS. Parser dùng model cache `.local/processor-models` với Hugging Face/Transformers offline. API stack, test SQL và object data là tài nguyên disposable do fixture sở hữu; không chạy dev-stack reset hoặc thay schema/data đang dùng.

Sau run, runner và Playwright đã thoát; `docker ps --filter name=openlet-api-e2e` không còn container đang chạy. Không dừng các container của project khác.

## Giới hạn

Không deploy, remote CI, live Clerk, external S3 provider, paid-model quality, production load benchmark hoặc long-duration soak. Warnings deprecation từ pinned SDK/test dependencies không làm suite fail và không được sửa trong scope audit.

Kết luận source nằm trong [audit report](audit-261109-2054-leta-persistence.md); đây là baseline kiểm chứng, không phải bằng chứng các đề xuất refactor đã được triển khai.
