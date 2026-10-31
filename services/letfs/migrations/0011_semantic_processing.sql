ALTER TABLE nodes
    ADD COLUMN media_type text,
    ADD COLUMN title text,
    ADD COLUMN description text,
    ADD COLUMN semantic_type text,
    ADD COLUMN context text;

ALTER TABLE operations
    ADD COLUMN enrichment_state text NOT NULL DEFAULT 'pending'
        CHECK(enrichment_state IN ('pending','running','succeeded','failed')),
    ADD COLUMN enrichment_error text,
    ADD COLUMN enriched_at timestamptz,
    ADD COLUMN index_state text NOT NULL DEFAULT 'pending'
        CHECK(index_state IN ('pending','running','succeeded','failed')),
    ADD COLUMN index_error text,
    ADD COLUMN indexed_at timestamptz,
    ADD COLUMN embedding_model text,
    ADD COLUMN vector_collection text,
    ADD COLUMN vector_dimension integer CHECK(vector_dimension>0),
    ADD COLUMN index_cleanup_state text CHECK(index_cleanup_state IN ('pending','succeeded'));

ALTER TABLE uploads ADD COLUMN processing_stage text;
UPDATE uploads SET processing_stage='parse' WHERE processing_operation_id IS NOT NULL;
ALTER TABLE uploads DROP CONSTRAINT uploads_processing_owner;
ALTER TABLE uploads ADD CONSTRAINT uploads_processing_owner CHECK (
    (processing_operation_id IS NULL AND processing_generation IS NULL
        AND processing_attempt_id IS NULL AND relative_path IS NULL AND processing_stage IS NULL)
    OR (processing_operation_id IS NOT NULL AND relative_path IS NOT NULL AND processing_stage IS NOT NULL AND (
        (processing_stage='parse' AND processing_generation IS NOT NULL AND processing_generation>0 AND processing_attempt_id IS NOT NULL)
        OR (processing_stage='enrichment' AND processing_generation IS NULL
            AND processing_attempt_id IS NULL)
    ))
);
DROP INDEX processing_output_path;
CREATE UNIQUE INDEX processing_output_path
    ON uploads(processing_operation_id,processing_generation,relative_path)
    WHERE processing_stage='parse';
