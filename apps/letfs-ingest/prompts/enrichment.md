Generate concise, factual retrieval metadata for every item listed under `--- ARTIFACT id="..." (<media>) ---` in this batch.

For each item in the batch, output an entry with its exact `id`:
- `title`: specific 2-8 word title identifying the core topic, document subject, or entity (max 64 characters). Never use generic structural labels such as "Introduction", "Overview", "Contents", "Table of Contents", "Page 1", "Image", "Table", "Index", "Document Sections", "Document Section Index", "Workbook Index", or "Workbook Sheet Index".
- `description`: dense 1-2 sentence retrieval summary stating concrete facts, metrics, column schemas, entities, or visual content (max 256 characters). Do not repeat the title verbatim.
- `slug`: descriptive lowercase kebab-case filename stem without extension (max 64 characters, `[a-z0-9-]`). Provide a `slug` for extracted document files (`text/markdown`, `text/csv`, `image/*` charts/figures/diagrams).
- For `id="README.md"`, synthesize a document-level `title` and `description` describing the whole file's topic and contents using the artifacts in this batch; do not provide `slug`. Do not provide `slug` for `id="."`.

Return only JSON matching the requested schema. Preserve exact artifact IDs from the prompt. Do not invent facts absent from the text, spreadsheet sample, or image.
