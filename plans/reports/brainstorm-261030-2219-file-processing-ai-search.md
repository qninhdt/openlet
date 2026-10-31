# File Processing phase 2 — đề xuất thiết kế

Ngày: 2026-10-30; cập nhật ngày 2026-10-31. Trạng thái: hướng thiết kế đã chốt trong hội thoại; chi tiết triển khai và hyperparameter sẽ cụ thể hóa khi lập plan.

## Kết quả mong muốn và giới hạn

Phase 2 có hai bước: **Semantic Enrichment** tạo thông tin ngữ nghĩa và hoàn thiện artifact; **Search Indexing** tạo embedding, lexical index và đánh dấu cả cây đã index xong. Search trả về file; chunk chỉ là đơn vị truy hồi nội bộ.

- Outcome: original file có title/description/type/context phục vụ UI; artifact có cây tối đa hai tầng nội dung, tên có nghĩa và README; tìm file bằng tên/filter hoặc hybrid semantic search có reranker.
- Constraints: Qdrant, Python Instructor, OpenRouter cho generation/embedding/reranking, Temporal hiện tại; giữ nguyên original bytes, upload transport, authorization, artifact read-only, quota, source identity và stale-attempt fencing. Hyperparameter cấu hình sau. Xử lý một original file và toàn bộ cây artifact như một job; không thêm distributed lock hay trạng thái index riêng từng child.
- Non-goals: triển khai trong phiên brainstorm; image-to-image search; tìm từng dòng CSV; thiết kế PPTX nâng cao; tính công thức và diễn giải merged cells của Excel; chatbot/RAG sinh câu trả lời.
- Acceptance: mô tả được layout 0/1/2 tầng; sampling có token bound và không làm mất dữ liệu gốc; metadata đi từ lá lên root; index text dài dùng toàn bộ nội dung; kết quả được gộp thành file; retry AI không chạy lại OCR; index cũ không làm lộ dữ liệu đã thay thế, trash hoặc mất quyền.

Các quyết định người dùng đã xác nhận trong phiên:

1. Excel không tạo content.md. Văn bản ngoài bảng nằm trực tiếp trong README.md của sheet.
2. CSV chỉ cần tìm ra file/bảng bằng ngữ nghĩa, không index từng dòng/giá trị.
3. Ảnh được vision LLM mô tả rồi embed context bằng text embedding model; không có vector ảnh riêng.
4. Dùng một generic text sampler trước; filetype-specific sampling defer.
5. Dùng OpenRouter cho cả ba nhóm model. Chunking dùng package độc lập, structured generation giữ Instructor.
6. Payload tối thiểu, indexing theo cả cây; bỏ thiết kế active-index-generation và stage fencing riêng cho phase 2.
7. Quy tắc chọn layout dùng min_leaf_tokens và split_tokens như phần dưới; chọn trước khi export.
8. Semantic search trả unique original files, kèm breadcrumb của artifact khớp để mở nội dung liên quan.
9. Chưa có production: triển khai dùng workflow input/API mới trực tiếp, cập nhật test histories; không cần backward compatibility. Implementation plan viết bằng tiếng Anh tại [file-processing AI/search plan](../261031-0801-file-processing-ai-search/plan.md).

## Cơ sở từ repository

- [Workflow hiện tại](../../services/letfs/src/temporal/process_file_workflow.rs) có một Rust ProcessFile và một Python process_file activity.
- [Processor](../../services/letfs/processor/src/openlet_processor/activity.py) chỉ nhận PDF/DOCX/XLSX/PPTX, tải nguồn bằng scoped capability, convert, upload rồi complete.
- [Exporter](../../services/letfs/processor/src/openlet_processor/exporters.py) đang chia main-section Markdown hoặc slide, dùng prefix ba chữ số, images/ và các CSV positional cho Excel.
- [Processing publication](../../services/letfs/src/fs/processing.rs) mint node ID lúc complete, từ chối cây đã có children và chỉ publish một lần. Không thể nối AI vào rồi giả định API complete hiện tại đã hỗ trợ cập nhật cây.
- [Intent](../../services/letfs/src/fs/artifacts.rs) hiện dựa vào extension của bốn format và được gọi từ upload publication. Cần nối thêm các đường text create/replace và eligible copy publication.
- [Data model](../../docs/data-model.md) và [workflow contract](../../docs/workflows.md) quy định source bytes không đổi khi gắn artifact; nguồn vẫn là file; copy không kế thừa processing intent; trạng thái publisher succeeded còn phục vụ accounting khi xóa descendants.

Đây là phase 2 của sản phẩm file processing mà người dùng đang mô tả, không phải phase-02-artifacts trong implementation plan cũ.

## Pipeline được đề xuất

```text
Upload hoặc text create/replace commit source + durable processing intent
  |
  +-- PDF/DOCX/XLSX/PPTX: Parse & Structure -> publish parsed artifacts
  |
  +-- inline/object text, standalone CSV/image: đọc trực tiếp, không tạo artifact
  |
  Semantic Enrichment
    sample/profile -> leaf metadata -> folder metadata -> root metadata
    -> slug tên -> sửa liên kết -> render README -> publish enrichment atomically
  |
  Search Indexing
    file representations + full-content text chunks
    -> dense embeddings + BM25 -> Qdrant upsert -> đánh dấu job index ready
```

Parse thành công vẫn có giá trị ngay cả khi AI chưa chạy được. UI phân biệt parsed, enriched và searchable. Bản parsed có thể chứa tên untitled; enrichment xuất bản đồng thời tên cuối cùng và metadata, không để UI thấy một cây được rename dở.

Small text và large text đi cùng một pipeline ngữ nghĩa. Inline/object chỉ quyết định cách đọc bytes, không quyết định thuật toán AI và không thay đổi cách lưu bytes. Kiểm tra encoding/MIME để xử lý nội dung không có nghĩa là đổi upload transport.

## Artifact layout và ownership

Root là original file trong letfs, không cần thư mục artifacts/ hoặc run/ mới. Giới hạn hai tầng được tính cho **cây nội dung bên trong source**: một tầng thư mục semantic và một tầng file lá. README và media là thành phần biểu diễn, không làm phát sinh thêm thư mục theo file type.

### 0 tầng

```text
notice.pdf/
  README.md                 # metadata root + toàn bộ nội dung
  1-untitled.png            # nếu có media độc lập
  2-untitled.csv            # nếu có bảng cần xuất riêng
```

0 tầng nghĩa là không chia nội dung thành các leaf Markdown riêng; không có nghĩa là cấm media. PDF/DOCX không bắt buộc tách tất cả bảng inline thành CSV: giữ các bảng đang có ngữ cảnh inline, chỉ xuất CSV riêng khi lựa chọn representation yêu cầu.

### 1 tầng

```text
handbook.docx/
  README.md                 # metadata root + lời mở đầu thuộc root
  1-untitled.md
  2-untitled.md
  3-untitled.png             # media thuộc section, nằm cùng semantic container
```

Leaf Markdown không có thư mục riêng. Không tạo một README phụ cho từng leaf.

### 2 tầng

```text
textbook.pdf/
  README.md
  1-untitled/                # part 1
    README.md               # metadata part + nội dung riêng của part
    1-untitled.md            # chapter 1
    2-untitled.md
    3-untitled.md
    4-untitled.md
  2-untitled/
    README.md
    1-untitled.md
    ...
  3-untitled/
    README.md
    ...
  4-untitled/
    README.md
    ...
```

Với sách bốn part, mỗi part bốn chapter: bốn thư mục part, mỗi thư mục bốn Markdown chapter; parser chưa dùng title làm tên. Các heading sâu hơn nằm trong Markdown, không sinh thêm tầng thư mục.

Quy tắc đồng nhất áp dụng cho section cùng cấp: nếu chọn layout hai tầng, một part ít cấu trúc hơn vẫn là thư mục và chứa một Markdown cho nội dung lá của nó. Không trộn part.md với part/ ở cùng tầng nội dung. README và media không phải các section cạnh tranh với quy tắc này. Không tạo file rỗng chỉ để đủ hình dạng.

Mỗi media đặt tại semantic container gần nhất, có source locator/owner trong dữ liệu nội bộ và liên kết từ đoạn Markdown tương ứng. Không tạo images/, text/ hoặc tables/.

### Chọn độ sâu trước khi xuất file

Parser đọc toàn bộ outline và phân bố độ dài trước, chọn một layout cho cả tài liệu rồi mới export. Hai ngưỡng cấu hình sau là min_leaf_tokens để hạn chế file quá nhỏ và split_tokens để xác định phần nội dung đáng cân nhắc chia.

1. Chọn 0 tầng khi tổng text không vượt split_tokens hoặc outline không có ranh giới chia hữu ích.
2. Chọn 1 tầng làm mặc định cho tài liệu cần chia. Main sections thành Markdown; bỏ qua một heading wrapper bao trùm toàn tài liệu. Gộp các section nhỏ liền kề trong cùng nhóm dựa trên min_leaf_tokens và giữ heading gốc.
3. Chọn 2 tầng khi có hai cấp cấu trúc có ý nghĩa, đa số main sections vượt split_tokens và đa số có ít nhất hai subsection đủ nội dung. Áp dụng folder shape cho cả tầng; nhóm nhỏ có thể chỉ chứa một leaf.
4. Một chapter dài riêng lẻ vẫn có thể ở layout 1 tầng. Search Indexing chunk phần dài đó. Ngưỡng chia không phải giới hạn cứng cho độ dài file.

Heading nguồn và breadcrumbs vẫn giữ được khi flatten. Baseline quyết định từ outline và độ dài, không dùng LLM planner hoặc hệ thống scoring layout. Excel dùng layout theo sheet; PPTX giữ một README như đã chốt.

Nội dung không được mất hoặc nhân đôi khi regroup: preamble thuộc root; phần giới thiệu part thuộc README part; chapter body thuộc leaf. Nếu part chỉ là một nhãn nhóm thì body README part có thể rỗng.

### Đánh số và slug

- Ordinal dựa trên thứ tự nguồn, không dựa trên title AI.
- Với mỗi tập sibling được đánh số, width bằng số chữ số của ordinal lớn nhất: 1–9 dùng 1, 2; 10–99 dùng 01, 02; không mặc định 001.
- Không tính README vào ordinal. Media cùng container cũng có ordinal ổn định; extension và prefix giúp tránh xung đột.
- Enrichment đổi <index>-untitled thành <index>-<slug(title)>, giữ index và extension. Original filename do người dùng đặt được giữ nguyên.
- Slug là hàm deterministic trong code: Unicode normalization, lọc ký tự đường dẫn, giới hạn độ dài, xử lý tên dự phòng/collision. Không dùng nguyên output LLM làm path.
- Dùng node ID làm danh tính. Hoàn thành bảng ID -> final path rồi mới render lại các relative links và README. Title đổi không được làm đứt liên kết.

### Excel và PPTX

```text
budget.xlsx/
  README.md                 # metadata workbook
  1-untitled/                # sheet 1, sau enrichment có slug
    README.md               # metadata sheet + mọi văn bản ngoài bảng
    1-untitled.csv
    2-untitled.csv
    3-untitled.png           # nếu có ảnh
  2-untitled/
    README.md               # có cả với sheet rỗng
```

Tên sheet gốc và tọa độ ô/bảng được giữ làm provenance, ngay cả khi AI đặt tên hiển thị mới. Phân tách table và text không được bỏ singleton cells hoặc đoạn hướng dẫn. Khi không chắc một vùng là text hay bảng, giữ nội dung và vị trí, không âm thầm loại bỏ.

Merged-cell interpretation và formula evaluation defer. Không hạ cấp việc bảo toàn nội dung hiện có: giữ công thức dạng literal/cached value có nhãn nguồn nếu đọc được; không tự tính hoặc bịa kết quả. Đây không phải cam kết giải quyết lại backend Excel trong phiên này.

PPTX tạm dùng một README.md chứa metadata và content, giữ ranh giới slide trong body. Thiết kế chia slide, visual layout và tối ưu artifact PPTX defer; original PPTX luôn còn nguyên. Các chi tiết media PPTX phải được chốt khi quay lại thiết kế PPTX, không được coi nhánh Markdown tối giản là đã biểu diễn đầy đủ mọi visual.

## Metadata contract

Phân biệt rõ:

| Field | Ý nghĩa |
|---|---|
| title | Tên hiển thị có nghĩa, ngắn, giữ ngôn ngữ nguồn theo mặc định |
| description | Một câu mô tả nội dung node |
| context | Vài câu chứa chủ đề, thực thể, phạm vi, mục đích; phục vụ embedding |
| type | Semantic type; schema theo loại node, root là document category |
| content | Nội dung gốc của node, nằm trong body Markdown/bytes; không phải summary AI |

kind=file/directory và MIME/format là dữ kiện kỹ thuật độc lập, không để LLM thay đổi. Root dùng type để lưu document category, không lưu thêm một category trùng nghĩa. Text sampling profile là thuộc tính kỹ thuật nội bộ, có thể khác semantic type.

Metadata chuẩn được letfs sở hữu; README là biểu diễn được render từ metadata đã validate cùng own content. Leaf metadata cũng lưu theo node ID trong DB, vì parent README chỉ mang title/description/type của leaf và không mang context của leaf.

Ví dụ README của một part sau enrichment:

```yaml
---
title: Nền tảng xác suất
description: Phần này trình bày các khái niệm cơ bản về xác suất và biến ngẫu nhiên.
type: part
context: >-
  Phần đầu của giáo trình xác suất, giới thiệu không gian mẫu, biến cố và biến
  ngẫu nhiên. Các chương đi từ định nghĩa đến phép tính và ví dụ minh họa.
children:
  1-khong-gian-mau.md:
    title: Không gian mẫu
    description: Chương này giải thích không gian mẫu và các phép toán trên biến cố.
    type: expository
  2-bien-ngau-nhien.md:
    title: Biến ngẫu nhiên
    description: Chương này giới thiệu biến ngẫu nhiên và phân phối xác suất.
    type: expository
---

Nội dung mở đầu thực sự thuộc part, nếu có.
```

children chỉ mô tả con trực tiếp, với path là khóa định vị và đúng ba field title/description/type. Không nhét context của con hay toàn bộ descendants vào README cha. Root README không lặp lại cả sách; nó đại diện toàn bộ sách bằng metadata và chứa own content ở body.

Original node có title/description/type/context nullable khi chưa enrich, kèm trạng thái và content identity/version của metadata. list/stat trả summary metadata; context có thể chỉ trả ở stat/detail để không làm phình danh sách. AI update không thay original bytes. Khi cập nhật API, bảo đảm cache/list nhận metadata mới theo cơ chế hiện có; chưa thiết kế thêm một hệ thống metadata version.

## Semantic Enrichment: thuật toán và taxonomy

### Text sampling: một thuật toán generic với tối đa X token

Chọn **sample các cửa sổ trải đều toàn file**, có lấy đầu và cuối. Một thuật toán cho mọi text; không classify bằng LLM rồi mới chọn sampler.

1. Nếu nội dung không quá X token, gửi toàn bộ.
2. Nếu dài hơn, chia thành các block có token bound bằng recursive text splitter. Ưu tiên paragraph, newline, sentence/space; fallback ký tự để xử lý cả text không xuống dòng.
3. Chọn K block ở các vị trí cách đều từ đầu đến cuối, gồm block đầu/cuối. K và block budget cấu hình sau; mỗi block khoảng (X - marker budget)/K token.
4. Giữ thứ tự nguồn, chèn marker giữa các đoạn bị bỏ. Không nối chúng thành một đoạn văn giả liên tục.
5. Đếm lại bằng tokenizer phù hợp model và giảm sample nếu cần để serialized evidence <= X; prompt/schema/output có budget riêng.

Tái sử dụng cùng splitter package với chunking nhưng sampling không cần overlap. Với text dài, chỉ các block được chọn đi vào LLM enrichment; nội dung đầy đủ vẫn được chunk ở bước indexing.

**Defer filetype-specific text sampling:** code symbols/AST, log templates, semantic-section scoring, near-duplicate detection và sampler chuyên biệt cho từng format. Classification semantic vẫn trả cùng metadata, không dùng để điều khiển sampler hiện tại.

Giới hạn được chấp nhận: có thể bỏ sót một chủ đề/chi tiết hiếm hoặc chọn đoạn lặp. LLM phải được phép trả unknown khi không đủ bằng chứng, đặc biệt với random/opaque text. Đây là đổi chác để có baseline đơn giản, kiểm thử được.

### Text semantic types: 16 nhóm

`narrative`, `expository`, `instructions`, `reference`, `qa`, `correspondence`, `source_code`, `configuration`, `structured_records`, `logs`, `tabular_text`, `markup`, `opaque_text`, `mixed`, `empty`, `unknown`.

Các nhóm này mô tả kiểu nội dung của leaf, không phải ngành nghề và không phải MIME. Ví dụ Markdown có thể là instructions hoặc reference; một .txt có thể là source_code hoặc logs. Chỉ lấy một primary type để filter ổn định.

### Ảnh: 14 nhóm

`photograph`, `screenshot`, `chart`, `diagram`, `map`, `scanned_document`, `illustration`, `logo`, `icon`, `ui_design`, `handwriting`, `composite`, `other`, `unknown`.

Đưa ảnh thực sự vào vision LLM cùng caption/vị trí nếu có. Giới hạn pixels/request size riêng; ảnh lớn có thể downscale hoặc tile có bound, không đồng nhất image budget với X text tokens. title/description/context phải bám bằng chứng nhìn thấy; không bịa con số nhỏ không đọc được hoặc suy đoán danh tính. Text embedding chỉ encode context và breadcrumb, nên không cung cấp visual similarity.

### CSV/table: profile và 14 nhóm

Profile gồm delimiter/header evidence, tên cột, inferred type + độ tin cậy/mixed/null rate, số hàng/cột, đơn vị hoặc key nếu có bằng chứng, range/distinct estimates khi phù hợp và các sample rows theo coverage/diversity. Giữ mã như 00123 là chuỗi nếu việc cast có thể phá nghĩa; không suy ra tiền tệ/đơn vị từ con số thuần túy.

Sample rows gồm đầu/cuối và deterministic reservoir trên toàn file, thêm ví dụ null/mixed/khác nhóm nếu có chỗ. Cột quá rộng phải sample cả columns, báo omitted count; không giả định toàn schema luôn vừa X. Không gửi nguyên CSV lớn vào LLM và không chỉ lấy vài dòng đầu.

Types: `records`, `time_series`, `summary`, `matrix`, `cross_tab`, `key_value`, `lookup`, `financial_ledger`, `schedule`, `inventory`, `questionnaire`, `mixed`, `other`, `unknown`.

CSV có một file-level representation, không có row chunks. Vì vậy tìm theo ý nghĩa bảng/schema/samples, không cam kết truy hồi mọi mã hàng hoặc giá trị ở một dòng bất kỳ.

### Root document categories: taxonomy khởi điểm 34 nhóm

Không có enum hữu hạn liệt kê được mọi tài liệu có thể có. Chọn taxonomy theo hình thái/mục đích, có other/unknown; tránh trộn ngành nghề vào document category.

| Nhóm | Categories |
|---|---|
| Học tập | textbook, course_material, tutorial, reference_manual |
| Nghiên cứu | research_paper, thesis, research_notes |
| Công việc | report, proposal, business_plan, specification, policy, procedure, meeting_record |
| Pháp lý | contract, legal_document, regulatory_document |
| Tài chính | invoice, receipt, financial_statement, budget |
| Biểu mẫu/cá nhân | form, survey, resume, letter, personal_notes |
| Biên tập | book, article, correspondence, presentation |
| Dữ liệu/kỹ thuật | dataset, source_code, configuration, logs |

Thêm `mixed`, `other`, `unknown` làm ba giá trị escape: tổng cộng 37. Original CSV/XLSX thường là dataset, budget hoặc financial_statement tùy bằng chứng; không gán mọi spreadsheet thành budget. Standalone image dùng image taxonomy ở type. Domain như medical/legal/education là chiều khác; chưa cần thêm tags khi người dùng chưa yêu cầu.

### Sinh bottom-up

1. Enrich leaf text/image/CSV. Các leaf độc lập có thể chạy concurrent có bound.
2. Enrich folder sau khi children hoàn thành: input là own content đã sample và title/description của children; type kỹ thuật của children có thể làm tín hiệu phụ. Giữ ordinal/source heading để không mất quan hệ.
3. Enrich root bằng cùng cách; root classification dựa cả own content và children summaries. Với nguồn không có artifact, root dùng evidence trực tiếp từ nguồn.
4. Nếu tổng children descriptions vượt budget, reduce có thứ tự theo nhóm rồi tổng hợp. Inventory đầy đủ vẫn còn trong metadata/README; reduction chỉ áp dụng prompt. Không truncate mất các child cuối.
5. Khi cả cây xong, slug tên, sửa relative links, render README và publish đồng thời metadata/tên/bytes mới.
6. Lưu kết quả enrichment của cả job. Index retry dùng lại kết quả này; chưa thêm durable checkpoint/digest/version cho từng child. Enrichment lỗi giữa chừng có thể phải gọi lại một phần LLM khi retry; chấp nhận baseline này trước.

Bottom-up không đưa parent description còn chưa có vào leaf prompt. Contextual prefix của embedding được dựng sau khi toàn bộ enrichment đã hoàn tất.

## Search Indexing và contextualization

### Hai loại đơn vị truy hồi

- **File-level:** mỗi leaf file có một vector overview từ context. README đại diện folder/source có một vector tương ứng; original text/image/CSV không có artifact cũng có vector này.
- **Chunk-level:** text dài, kể cả body README dài, được chia từ toàn bộ nội dung; không dùng sample enrichment. Chunk là record trong index, không phải file mới và không phải loại kết quả công khai.

Không embed hai lần cùng một logical root chỉ vì có original PDF và README root. README là representation của original, được ánh xạ về cùng logical target. Tương tự folder và README của folder. Image embedding là text vector của vision context, không phải vector pixel.

Text ngắn có thể giữ original text trong text payload để không mất tên/mã cụ thể mà context AI bỏ qua; dense input dùng context như yêu cầu. Text dài có overview point và toàn bộ text chunks; text payload của chunk phải có nội dung gốc. CSV chỉ index profile/context đã được chọn, không toàn bộ cell values.

### Chunking: dùng thư viện độc lập

Chọn [langchain-text-splitters](https://docs.langchain.com/oss/python/integrations/splitters/recursive_text_splitter), dùng RecursiveCharacterTextSplitter với token-count length function và chunk_overlap. Package được cài và gọi riêng; không cần LangChain chains/agents hoặc Document abstraction trong code ứng dụng. Các dependency nội bộ của package vẫn do package manager resolve.

Đây là recursive splitting theo separators, không phải AI semantic-boundary detection. Nó có fallback cho chuỗi không có paragraph/newline. Dùng tokenizer tương thích model đã chọn; không mặc định một tokenizer chính xác cho mọi model trên OpenRouter.

Budget chunk trừ contextual prefix; kiểm tra embedding input sau khi ghép. Sampling dùng overlap=0; embedding chunks dùng overlap cấu hình sau. Không bắt buộc Docling HybridChunker, không tự viết một chunking framework; Docling tiếp tục làm parsing/OCR.

Structured LLM generation dùng Instructor + Pydantic. Không cần chuyển sang LangChain chỉ để có cả chunking và structured output.

### Contextual embedding hiện nay

Có hai cách triển khai liên quan nhưng khác nhau:

1. **Bổ sung context trước khi embed.** [Anthropic Contextual Retrieval](https://www.anthropic.com/research/contextual-retrieval) dùng LLM viết lời giải thích riêng cho từng chunk trong ngữ cảnh tài liệu, prepend vào chunk rồi tạo embedding và BM25. Vẫn dùng embedding model thông thường; cải thiện nằm ở representation đầu vào, không phải thuật toán vector search mới.
2. **Model tạo contextualized chunk embeddings.** [Voyage contextualized chunk embeddings](https://docs.voyageai.com/docs/contextualized-chunk-embeddings) nhận một nhóm chunks của cùng tài liệu và encode mỗi chunk có xét các chunk còn lại. API riêng là contextualizedembeddings; không được giả định gọi embeddings thông thường với một list strings cũng có hành vi này.

Có thể gọi đây là nâng cấp cách tạo embedding cho retrieval, nhưng không phải một chuẩn bắt buộc thay thế embedding truyền thống và không bảo đảm mọi dataset đều tốt hơn.

Baseline đề xuất cho Openlet, tương thích OpenRouter embeddings thông thường:

```text
File overview = title + context của file + title/description của ancestors
Text chunk    = title/description của ancestors + title/description của file
                + nguyên văn chunk
```

Dựng prefix từ metadata đã có, không thêm LLM call cho từng chunk. Đây là contextualization bằng metadata, không gọi là triển khai đầy đủ công thức Anthropic hoặc model contextualized của Voyage. Vẫn dùng chunk text thật, không thay bằng summary.

Chưa xác nhận OpenRouter expose API contextualizedembeddings của Voyage. Vì người dùng đã chọn OpenRouter cho mọi model, không đưa khả năng này thành dependency của thiết kế. Contextual model chuyên dụng hoặc per-chunk LLM context chỉ cân nhắc sau eval; không thay provider đã chọn.

Chỉ lấy ancestors trong artifact tree; không lấy đường dẫn thư mục Drive bên ngoài source. Di chuyển original file vì thế không đổi embedding input.

## Qdrant, BM25 và payload tối thiểu

Theo [release Qdrant 1.20.0](https://github.com/qdrant/qdrant/releases/tag/v1.20.0), BM25 scoring trực tiếp trên full-text payload index được bổ sung ngày 22/10/2026. Với server/client tương thích, dùng dense vector và [BM25 text index](https://qdrant.tech/documentation/search/text-search/full-text-search/) trên field text; [hybrid query](https://qdrant.tech/documentation/search/text-search/hybrid-search/) kết hợp bằng RRF. Phiên bản cũ có thể dùng BM25 sparse vectors; không duy trì hai lexical index cùng lúc.

Dùng một collection cho embedding model hiện tại. Payload chung của file và chunk chỉ cần:

```json
{
  "filesystem_id": "uuid",
  "source_id": "original-file-uuid",
  "file_id": "readme-or-leaf-or-original-file-uuid",
  "operation_id": "existing-processing-operation-uuid",
  "text": "Text đã ghép context, dùng cho BM25 và reranker"
}
```

- filesystem_id dùng scope filter theo authorization hiện tại.
- source_id dùng gom kết quả và xóa index của cả cây.
- file_id tìm lại file tạo ra evidence; text không có artifact dùng original ID.
- operation_id tái dùng processing job hiện có cho cả cây; loại kết quả của job cũ khi source đã đổi. Không phải generation mới hoặc attempt riêng từng child.
- text dùng lại cho BM25/reranker, không nhân bản thành context/text/lexical_text.

File/chunk khác nhau ở input text và point ID. Point ID deterministic từ operation_id + file_id + file/chunk ordinal để retry upsert không nhân bản. Chưa cần unit_kind/chunk_index trong payload vì search không filter hoặc trả chunks riêng.

Title, description, type, parent/path, timestamps và thông tin UI lấy từ DB sau retrieval. Không copy hết metadata vào Qdrant. Query/document embedding model phải nhất quán; model selection nằm ở config, không ghi mọi config version trên từng point.

**Không cần Elasticsearch cho scope này.** PostgreSQL xử lý filename/title/filter/sort; Qdrant xử lý hybrid content retrieval. Chỉ cân nhắc Elasticsearch khi có yêu cầu cụ thể mà hai hệ thống hiện có không đáp ứng; chưa thêm dịch vụ hoặc analyzer framework.

## Search pipeline và API/UX

### Semantic search

1. Workspace xác thực user, role và filesystem/mount scope.
2. letfs validate query và filters; tạo query embedding bằng embedding space phù hợp.
3. Qdrant prefetch dense và BM25 với cùng filesystem scope; file và chunk points cùng tham gia. Dùng RRF để gộp rank, không cộng cosine và BM25 raw scores.
4. Batch-check source IDs ở letfs: live, thuộc scope, operation_id còn là job hiện tại và job đã index xong. Làm trước khi đưa text tới reranker hoặc trả evidence.
5. Khử overlap gần trùng, giới hạn số evidence trên mỗi source để một sách lớn không chiếm hết shortlist. Rerank query với các evidence tốt nhất của từng candidate; có bound tổng tokens và mỗi nguồn.
6. Gộp về original file cho giao diện khám phá file; giữ matched artifact/heading làm lý do match và đường dẫn mở nội dung, không trả chunk thành kết quả riêng. File-level root evidence vẫn tham gia để truy vấn tổng quan không bị lép vế.
7. Revalidate tại thời điểm lấy result/download theo API hiện có; hydrate filename/path/metadata mới nhất từ DB.

Nếu loại stale candidates khiến thiếu kết quả, refill với giới hạn công việc và trả cursor/partial status đúng hợp đồng. Semantic score không có đơn vị phần trăm tin cậy; không hiển thị như xác suất.

Reranker lỗi có thể trả hybrid ranking với degraded=true nếu đó là contract đã chốt; embedding hoặc Qdrant lỗi phải báo rõ dependency failure hoặc một lexical-only mode đã định nghĩa, không trả thành công rỗng giả như không có file.

### Hai API được đề xuất

- GET /v1/workspaces/{ws}/files/search: query tên/title, filters parent/type/MIME/date, sort và cursor; không phụ thuộc AI/Qdrant để liệt kê file vừa upload.
- POST /v1/workspaces/{ws}/files/semantic-search: query ngữ nghĩa và filters; trả unique original files, title/description/type, matched artifact breadcrumb, lý do match ngắn, next_cursor và degraded status nếu có.

Đây là route proposals, chưa phải API đã tồn tại. Cursors bind actor scope, query, filters, sort/model/index context; approximate semantic pagination không hứa snapshot tuyệt đối khi index đang cập nhật. Không tự thêm generated answer/chat.

UI đề xuất: filename vẫn có; AI title làm tên hiển thị bổ sung, description làm subtitle; breadcrumbs dẫn vào artifact; trạng thái riêng cho parse/enrich/index, retry đúng bước lỗi; search trả file card, không đổ ra hàng loạt chunks/README trùng với original. README được render như overview của node; vẫn cho xem raw khi người dùng mở file đó.

## Temporal: một job cho cả original file và cây artifact

Giữ ProcessFile workflow; parse hiện tại rồi thêm hai activity cấp **toàn cây**: enrich_file và index_file. Text/CSV/image không cần parse thì đi thẳng vào enrichment. Không workflow/activity cho mỗi child, không distributed lock, lease hoặc mutex mới.

```text
+ process_file: parse và publish cây
+ enrich_file: đọc cả cây, sinh bottom-up, publish metadata/tên/README của cả cây
+ index_file: embed cả cây và text chunks, upsert Qdrant, đánh dấu index ready
```

Enrichment hoàn tất được lưu để index retry không gọi lại LLM. Trước mắt không thêm checkpoint riêng từng node. Heartbeat dùng để Temporal biết activity còn sống; payload history chỉ có ID/status nhỏ.

Ranh giới activity dựa trên kết quả cần giữ khi retry: lỗi enrichment giữ kết quả parse; lỗi indexing giữ kết quả enrichment. Sampling, generation từng node, slug và render README là các hàm bên trong enrich_file. Chunking, embedding batches và Qdrant upsert nằm trong index_file. [Khảo sát activity toàn hệ thống](research-261031-0755-temporal-activity-boundaries.md) ghi lại tiêu chí và các ranh giới hiện tại.

### Điều kiện bảo vệ tối thiểu

Chỉ cần tái dùng operation/source checks hiện có: job còn là job hiện tại của source và source còn live. Finalize enrichment một lần cho cả cây; retry sau khi đã hoàn tất trả lại kết quả đã lưu, không overwrite bằng một bộ metadata mới. Không mở rộng attempt-generation protocol của parser thành một hệ thống stage fencing mới.

Bảng operations hiện có được giữ để phục vụ idempotency và quan hệ dữ liệu ứng dụng. Kế hoạch backend ban đầu tạo bảng cho direct inline-copy keys/fingerprints/result IDs, sau đó mở rộng cho durable copy và processing. Temporal sở hữu orchestration và retry; phase 2 tái dùng bảng hiện có.

Index upsert point IDs deterministic, retry có thể upsert lại cả cây. Chỉ đánh dấu ready sau khi tất cả batches được xác nhận. Nếu worker chết giữa chừng, search tạm bỏ cả source chưa ready; không cố cung cấp atomic index swap hoặc zero-downtime reindex.

Khi source bị thay thế: job mới có operation_id mới, search bỏ candidate mang operation_id cũ sau DB check, rồi cleanup index cũ theo operation_id đó. Attempt cũ chạy chậm không được đánh dấu job mới ready; đây là một kiểm tra current operation, không phải distributed lock. Cleanup phải chỉ xóa đúng operation cũ.

Đổi chác được chấp nhận: file có thể tạm không xuất hiện trong semantic search lúc indexing/reindexing. Basic filename search vẫn chạy. Không cần active_index_generation, double-buffer index hoặc trạng thái ready cho từng file con.

### Phần thực sự phải sửa trong implementation

- complete parse hiện tại chỉ publish lần đầu. Enrichment cần internal update cả cây, giữ readonly guard công khai, sửa tên/relative links/README cùng nhau và tính quota cho bytes đổi.
- Giữ parse publisher succeeded theo accounting cũ; trạng thái enrichment/indexing tách khỏi kết quả parse, không hồi succeeded thành running.
- Nối thêm text create/replace, copy, backfill và cleanup khi trash/delete; artifacts không tự kích hoạt pipeline đệ quy.
- Workflow timeout/replay và stage retry cần cập nhật cho sequence mới. Không cần thiết kế thêm dịch vụ khóa hay scheduler.

## OpenRouter, Instructor và chunking

Chốt OpenRouter cho cả ba nhóm model:

| Nhóm | API | Cách gọi |
|---|---|---|
| Generation + vision | chat/completions | Instructor + Pydantic qua OpenAI-compatible client trỏ OpenRouter |
| Embedding | embeddings | SDK/HTTP trực tiếp tới OpenRouter |
| Reranking | rerank | SDK/HTTP trực tiếp tới OpenRouter |

Nguồn xác nhận: [OpenRouter structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs), [embeddings API](https://openrouter.ai/docs/api/api-reference/embeddings/submit-an-embedding-request), [rerank API](https://openrouter.ai/docs/api/api-reference/rerank/submit-a-rerank-request). Base URL là https://openrouter.ai/api/v1. Chọn model generation có vision và structured-output support; model IDs và numeric settings cấu hình sau.

Không dùng Instructor để gọi embedding/reranker; nó chỉ validate structured generation. Không cần LangChain framework; chỉ dùng package langchain-text-splitters cho splitting. Validate schema/enum/slug bằng code; nội dung tài liệu không được điều khiển tools hay path.

Giữ worker Python cho background enrichment/indexing. Search API có thể gọi OpenRouter embedding/rerank trực tiếp từ backend đang phục vụ request; không cần thêm Python inference HTTP service chỉ để proxy OpenRouter và không tạo Temporal workflow cho mỗi query.

## Phần thiết kế còn phải cụ thể hóa khi lập plan

1. Layout 0/1/2 tầng và media ownership trong exporter, bảo toàn nội dung và sửa links sau slug.
2. Internal enrichment update cho cả cây, metadata DB/README và quota.
3. Generic sampler/chunker có token bound; tokenizer phù hợp model được chọn.
4. Whole-job indexing ready, deterministic upsert và current operation check; không per-child fencing.
5. Search endpoint gọi OpenRouter, RRF/rerank và gom thành kết quả file.
6. Triggers cho text edits/copy/backfill và lifecycle cleanup, reuse owner hiện tại.

## Trade-offs và hướng tốt hơn

- **Generic hoặc filetype-specific sampler:** generic giả định mẫu trải đều đủ để mô tả file, yếu trước nội dung hiếm hoặc lặp nhiều; chuyên biệt có thể chọn evidence tốt hơn nhưng cần nhiều logic và test. Chốt generic, defer chuyên biệt theo người dùng.
- **Package splitter hoặc tự viết:** package giả định recursive token-bounded splitting đủ cho baseline, yếu trước ranh giới ngữ nghĩa đặc thù; tự viết dễ thêm lỗi về tokenizer/Unicode/overlap. Chọn package độc lập, không framework.
- **Whole-job ready hoặc atomic generation swap:** whole-job ready chấp nhận semantic search tạm thiếu file khi reindex, đổi lại ít state; atomic swap phục vụ liên tục nhưng cần version/publication logic. Chọn whole-job ready.
- **Metadata prefix hoặc context riêng từng chunk:** metadata prefix tận dụng enrichment sẵn có, có thể thiếu quan hệ rất cục bộ; LLM context riêng tốn thêm calls. Giữ prefix trước, đánh giá chất lượng sau.

**Better approaches:** package chunker độc lập, OpenRouter calls trực tiếp và current-operation check của toàn cây thay thế các đề xuất tự xây chunker/inference proxy/stage fencing phức tạp trước đó. Payload chỉ giữ dữ liệu phục vụ scope, mapping, current-job check và retrieval text; DB tiếp tục sở hữu metadata.

## Kiểm chứng khi triển khai

- Fixture thật cho layout, Excel ngoài bảng/sheet rỗng và relative links sau rename.
- Sampler và embedding input không vượt token bound, xử lý Unicode và text một dòng dài.
- Index retry không nhân bản; lỗi giữa batch chưa làm source ready; source overwrite/trash trong lúc index loại được kết quả cũ.
- File retrieval eval Việt/Anh, chủ đề tổng quan và chi tiết ngoài enrichment sample; CSV chỉ theo schema/chủ đề.
- Smoke test OpenRouter generation/vision, embedding, rerank với model được chọn.

Phiên này chỉ sửa bản brainstorm và tra tài liệu. Chưa chạy API trả phí, model hoặc benchmark retrieval.

## Câu hỏi còn mở

Model IDs, token budgets, giá trị ngưỡng và taxonomy chi tiết sẽ cấu hình/eval khi lập plan. Baseline dùng metadata prefix với embedding API thông thường. Hướng kiến trúc và cách trả kết quả search đã chốt.
