# Testcontainers và Compose cho E2E

Tra cứu: 2026-10-31 14:46 +07:00. Phạm vi: tài liệu chính thức Testcontainers for Go hiện hành, Docker Compose và script Openlet; chưa chạy thử hoặc thay đổi bộ test.

Testcontainers dùng được cho E2E. Quickstart chính thức nêu integration và end-to-end là các trường hợp sử dụng phù hợp. Compose và Testcontainers không loại trừ nhau: module Compose của Testcontainers cho Go có thể đọc YAML hiện có, chờ service sẵn sàng và quản lý teardown.

| Cách tổ chức | Phù hợp khi | Trách nhiệm cleanup |
|---|---|---|
| Compose qua script | Cần dùng lại topology của môi trường triển khai | Script phải dừng/xóa đúng project và lựa chọn volume/image cần giữ |
| Testcontainers trực tiếp | Cần tạo môi trường từ code test, cấu hình động từng suite | Đăng ký cleanup; Ryuk hỗ trợ thu gom tài nguyên được gắn nhãn của phiên test |
| Testcontainers với module Compose | Đã có YAML và muốn quản lý vòng đời trong Go test | Gọi Down và cấu hình xử lý volume/image; cấu hình Ryuk theo tài liệu module |

Trong Openlet, `scripts/verify-foundation.sh:11` đã gọi `down --remove-orphans` qua EXIT trap. `scripts/backup-restore-drill.sh:12` cũng dừng cả source và restore stack. Các lệnh này giữ volume/image; đó là lựa chọn retention hiện tại, không phải giới hạn của Compose. EXIT trap không xử lý được mọi kiểu kết thúc đột ngột, chẳng hạn SIGKILL.

Ryuk hỗ trợ cleanup container/network/volume của Testcontainers sau khi phiên mất kết nối. Không xem đây là cơ chế giới hạn BuildKit cache hoặc dọn mọi image/volume trên máy. Khi dùng tài nguyên cần giữ để kiểm tra restore, phải phân định rõ tài nguyên tạm và bằng chứng cần lưu trước khi bật xóa volume.

Đề xuất cho Openlet: tối ưu Dockerfile trước để giải quyết cache tăng nhanh; giữ Compose topology. Nếu tiếp tục cải tiến vòng đời E2E, đánh giá một suite dùng module Compose của Testcontainers, thay vì viết lại toàn bộ topology bằng API Go. Đây là đề xuất kỹ thuật theo đặc điểm repo, không phải kết luận về thị phần công cụ.

Nguồn:

- [Testcontainers Go Quickstart](https://golang.testcontainers.org/quickstart/)
- [Testcontainers Go Compose module](https://golang.testcontainers.org/features/docker_compose/)
- [Testcontainers Go Garbage Collector](https://golang.testcontainers.org/features/garbage_collector/)
- [Docker Compose down](https://docs.docker.com/reference/cli/docker/compose/down/)

Chưa xác minh: tương thích cụ thể của module Compose với secret mounts, cấu hình generated, restart barriers và snapshot/restore của Openlet. Cần kiểm tra trước khi quyết định chuyển runner.
