---
title: Lập plan xử lý file bằng AI và tìm kiếm hybrid
date: 2026-10-31
summary: Chốt bốn phase từ artifact layout tới search API và UX contracts.
---

# Lập plan xử lý file bằng AI và tìm kiếm hybrid

Đã tạo kế hoạch triển khai tại plans/261031-0801-file-processing-ai-search/plan.md dựa trên brainstorm đã chốt. Kế hoạch gồm artifact layout/parser, Semantic Enrichment, Search Indexing và search API/UX contracts.

Đã kiểm tra source, contracts, lệnh test và Rust SDK patching. Giữ nguyên các activity/polling hiện tại; bổ sung enrich_file và index_file theo toàn cây. Parse publication/accounting được giữ khi enrichment/index retry hoặc backfill. Qdrant payload vẫn có năm fields đã thống nhất.

Bước tiếp theo là triển khai phase-01-artifact-layout.md. Chưa thay đổi application code, schema hoặc dữ liệu; chưa gọi model. AgentWiki publish skipped.

Sau đó người dùng xác nhận chưa có production và yêu cầu plan bằng tiếng Anh. Plan được sửa để bỏ backward compatibility, legacy workflow input/patch marker và old API shape; test histories sẽ được tạo lại theo sequence mới.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
