# Datalab document ingest

- [x] Verify native Markdown and image results with synthetic PDF and DOCX documents.
- [x] Route PDF and DOCX through Datalab Convert. Preserve the Temporal activity and LetFS publish contract. Use multipart for private development storage and presigned GET for reachable S3 endpoints. Use the official Python SDK for submit, poll, retries and signed results. The public convert method does not expose an in-flight request ID for Temporal resume.
- [x] Publish native Markdown from Datalab and Docling Slim. Keep referenced images and use the same Markdown splitter and large-table CSV publisher for all four formats.
- [x] Run XLSX and PPTX on Docling Slim. Remove model warmup, PyTorch and local OCR. Increase parse and enrichment slots with separate limits for Office subprocesses, remote requests and image-heavy results.
- [x] Verify synthetic live conversions, resumed jobs, versioned artifact publication, the parser build and Office regression tests.
- [ ] Before production rollout, verify signed GET against the target S3 endpoint and run the labeled PDF and DOCX comparison corpus. Measure peak RSS and throughput at the target worker settings.

Live PDF and DOCX samples returned Markdown and keyed JPEG payloads. Datalab flattened a nested table in the DOCX sample into an extra row. Oversized HTML tables are split into linked Markdown files at row boundaries that preserve merged cells. Docling Slim supplies spreadsheet tables. Visible worksheet headings and formula coordinates, expressions and available cached values are added before Markdown serialization.

The parser image shrank from 3.31 GB to 951 MB on amd64. With the external S3 mode enabled, Datalab validates the input container. Openlet still enforces the stored source byte limit, returned page count, output budgets and decoded image pixel limit. Multipart mode also runs Openlet's local PDF and OOXML preflight.
