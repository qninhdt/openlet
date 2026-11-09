-- +goose Up
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX files_text_content_trgm
    ON public.files USING gin (text_content gin_trgm_ops)
    WHERE storage_kind = 'text';
