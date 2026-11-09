---
title: "Roadmap refactor, tối ưu và giảm phức tạp toàn source"
status: in-progress
branch: dev
created: 2026-11-09
---

# Roadmap toàn source

Nên bắt đầu ở `apps/leta/src/leta/store.py`, sau đó xử lý runtime Leta, rồi mới đi sâu vào LetFS. Đây là thứ tự ưu tiên khảo sát và cải tiến; không mặc định mọi folder đều phải sửa.

## Kết quả cần đạt

Giảm trách nhiệm trộn lẫn, chuyển đổi dữ liệu và bước trung gian không cần thiết; giữ đầy đủ tính năng, hợp đồng, quyền truy cập, tính toàn vẹn dữ liệu và khả năng hồi phục. Chỉ tuyên bố tối ưu tốc độ khi có phép đo trước/sau phù hợp.

Phạm vi bao phủ năm ứng dụng, shared packages, contracts/codegen, kiểm thử, scripts, infrastructure và tài liệu. Mỗi thay đổi đi cùng callers, exports, fixtures và kiểm thử bị ảnh hưởng. Generated code được kiểm tra qua nguồn sinh.

Không bao gồm viết lại toàn bộ hệ thống, thêm framework/service/dependency, đổi public API/schema, triển khai hoặc commit. Thay đổi các quyết định kiến trúc đã chốt là phạm vi riêng cần quyết định riêng.

## Căn cứ hiện tại

Khảo sát ngày 2026-11-09 dùng CodeGraph, danh sách file Git, AST Python, tài liệu, manifests, CI và các kế hoạch đã hoàn tất. Working tree sạch trước khảo sát. Vòng lập roadmap ban đầu chưa chạy tests; baseline thực thi và audit chặng 1 đã hoàn tất sau đó, liên kết bên dưới. Chưa benchmark latency/throughput trước/sau refactor.

| Điểm khảo sát | Bằng chứng | Ý nghĩa |
| --- | --- | --- |
| `apps/leta/src/leta/store.py` | 1.733 dòng, 64 method của `Store`; gom lifecycle, messages, activity, runs, HITL, schedules và API reads | Ưu tiên kiểm tra ranh giới trách nhiệm và phụ thuộc. |
| `apps/leta/src/leta/runtime/` và `temporal/` | Lần lượt 10/16 file Python; middleware 545 dòng | Luồng thực thi đi qua nhiều cơ chế checkpoint, orchestration và publication. |
| `apps/letfs/internal/filesystem/` | 84 file Go gồm tests; khoảng 7.892 dòng ngoài tests | Phạm vi lớn, nhiều invariant dữ liệu; xử lý theo từng operation. |
| `packages/python/src/openlet/clients/letfs.py` | 2.116 dòng; ProcessingClient, FilesystemClient và StorageAdministrationClient cùng nhiều DTO | Khảo sát theo caller thực tế; tách file chỉ có ích nếu giảm phụ thuộc hoặc làm rõ hợp đồng. |
| `apps/workspace/internal/workspace/` | Đã có feature files cho membership, invitations, scope access, resource access và recovery | Tiếp tục cấu trúc hiện có; tránh thêm tầng repository/service chung. |
| `apps/account/internal/account/` | Khoảng 192 dòng ngoài tests | Ưu tiên sau; phạm vi nhỏ và boundary danh tính nhạy cảm. |

Số dòng là physical lines của file được Git theo dõi, gồm comment/dòng trống. Test được nhận diện theo tên/path; không phải coverage hay độ phức tạp thực thi. Đây là tín hiệu chọn nơi đọc, không phải bằng chứng overengineering.

## Thứ tự thực hiện

| Chặng | Phạm vi chính | Kết quả mong muốn | Phụ thuộc |
| --- | --- | --- | --- |
| 0 | Toàn repo: baseline và inventory | Có trạng thái kiểm thử hiện tại, luồng cần bảo vệ và tiêu chí đo | Không |
| 1 | Leta persistence, bắt đầu schedules | Giảm trách nhiệm trộn trong Store theo ranh giới thật | 0 |
| 2 | Leta runtime, Temporal, filesystem, HTTP/events | Giảm bước điều phối/chuyển đổi thừa, giữ checkpoint và replay | 1 |
| 3 | LetFS filesystem, transport, clients, Temporal | Đơn giản từng operation; đo SQL/RPC/I/O ở đường nóng | 0; nên sau 2 để ổn định consumer Leta |
| 4 | Workspace và Account | Rà luồng membership/access/onboarding và lớp adapter | 2, 3 cho các boundary liên quan |
| 5 | LetFS ingest | Rà pipeline, parser và lifecycle tài nguyên | 3 |
| 6 | Shared Go/Python, contracts/generation | Rà phần dùng chung còn lại, kiểm chứng toàn bộ consumer | 1–5; cập nhật phần bị ảnh hưởng ngay trong từng chặng |
| 7 | Scripts, infra, E2E, CI, docs và nghiệm thu | Hoàn tất coverage toàn repo, recovery và bàn giao | 1–6 |

Thực hiện tuần tự từng lát cắt. Tests, shared clients và docs có liên quan được cập nhật cùng thay đổi; bảng không trì hoãn chúng tới chặng cuối. Chi tiết thao tác, điều kiện nghiệm thu và rollback nằm trong [execution.md](execution.md).

## Tiến độ khảo sát

Ngày 2026-11-09: đã scout và triển khai cleanup chặng 1 theo các nhóm overengineering, dead code, backward compatibility, testing, performance và maintainability. [Audit trước sửa](../reports/audit-261109-2054-leta-persistence.md) và [baseline](../reports/baseline-261109-2054-source.md) giữ bằng chứng ban đầu. [Implementation](implementation.md) và [kết quả refactor/benchmark](../reports/refactor-261109-leta-persistence.md) ghi thay đổi đã được người dùng chấp thuận, checks và giới hạn. Người dùng yêu cầu commit và push batch chặng 1 sau verification.

| Phạm vi | Trạng thái tại revision `043f4e5` và working-tree diff | Bằng chứng / bước tiếp |
| --- | --- | --- |
| Chặng 0: baseline toàn repo | Hoàn tất; native 32/32 tasks, API/recovery 45/45, replay và các gate bổ sung PASS | Baseline report; giữ lại làm mốc trước sửa |
| Chặng 1: Leta persistence + callers/tests liên quan | Cleanup, benchmark và kiểm chứng hoàn tất | Implementation report; không migration/dependency/API change |
| Chặng 2–7 | Có inventory và roadmap, chưa audit sâu đầy đủ | Tiếp tục theo phạm vi và nghiệm thu trong execution.md; không coi baseline PASS là kết luận code sạch |

## Quy tắc nghiệm thu

- Mỗi PR giải thích được phần phức tạp nào đã bỏ và vì sao hành vi vẫn đúng; move/rename đơn thuần chưa đủ.
- Mỗi vùng có kết luận: sửa với bằng chứng, giữ nguyên có lý do, hoặc còn thiếu bằng chứng cần thu thập. Không ép mọi file phải thay đổi.
- Không đặt mục tiêu phần trăm giảm LOC, số abstraction phải xóa hoặc tốc độ phải tăng khi chưa có baseline.
- Phân biệt PR refactor giữ hành vi và PR optimization thay thuật toán/query; không trộn với feature hoặc dependency upgrade.
- Hoàn tất khi toàn bộ phạm vi đã được disposition, checks theo rủi ro đạt, docs còn đúng và không còn regression chưa xử lý.

## Tài liệu chi phối

- [Kiến trúc hiện tại](../../docs/architecture.md), [data model](../../docs/data-model.md), [workflows](../../docs/workflows.md), [testing](../../docs/testing.md).
- [Quyết định service boundary đã chốt](../261103-1348-service-refactor/tmp-refactor-decision.md): giữ native business operations, shared destination clients, HTTP/gRPC adapter riêng; không dựng generic repository framework.
- [Leta engine đã hoàn tất](../261108-0001-leta-agent-engine/plan.md): sáu workflow, LangGraph checkpoints, Redis cache/replay, HITL và schedules là scope hiện hữu.
- [SQL optimization đã thực hiện](../reports/performance-261107-1204-api-sql.md) và [inventory đo từng query](../reports/performance-261107-1342-per-query-sql.md): dùng làm bối cảnh lịch sử; đo lại trên revision đang thay đổi.
