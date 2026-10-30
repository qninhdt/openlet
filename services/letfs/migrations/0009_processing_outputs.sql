ALTER TABLE uploads
    ADD COLUMN processing_operation_id uuid REFERENCES operations(id),
    ADD COLUMN processing_generation integer,
    ADD COLUMN processing_attempt_id uuid,
    ADD COLUMN relative_path text,
    ADD CONSTRAINT uploads_processing_owner CHECK (
        (processing_operation_id IS NULL AND processing_generation IS NULL AND processing_attempt_id IS NULL AND relative_path IS NULL)
        OR (processing_operation_id IS NOT NULL AND processing_generation>0 AND processing_attempt_id IS NOT NULL AND relative_path IS NOT NULL)
    );
CREATE UNIQUE INDEX processing_output_path ON uploads(processing_operation_id,processing_generation,relative_path)
    WHERE processing_operation_id IS NOT NULL;
