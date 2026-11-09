-- +goose Up
ALTER TABLE files
    ADD COLUMN text_content text,
    ADD COLUMN newline_count bigint,
    ADD COLUMN text_sha256 text,
    DROP CONSTRAINT files_payload_check,
    DROP CONSTRAINT files_storage_kind_check;

ALTER TABLE files ADD CONSTRAINT files_payload_check CHECK (
    (storage_kind='text' AND text_content IS NOT NULL AND inline_bytes IS NULL AND object_key IS NULL
        AND newline_count IS NOT NULL AND text_sha256 IS NOT NULL
        AND newline_count=octet_length(text_content)-octet_length(replace(text_content,E'\n',''))
        AND text_sha256=encode(sha256(convert_to(text_content,'UTF8')),'hex'))
    OR (storage_kind='inline' AND inline_bytes IS NOT NULL AND object_key IS NULL
        AND text_content IS NULL AND newline_count IS NULL AND text_sha256 IS NULL)
    OR (storage_kind='object' AND object_key IS NOT NULL AND inline_bytes IS NULL
        AND text_content IS NULL AND newline_count IS NULL AND text_sha256 IS NULL)
);
