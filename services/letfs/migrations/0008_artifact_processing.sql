-- Root aliases must not shadow existing names.
DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM nodes n JOIN filesystems f ON f.id=n.filesystem_id
        WHERE n.parent_id=f.root_id
          AND n.name ~* '^@[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    ) THEN
        RAISE EXCEPTION 'rename root UUID alias collisions before artifact migration';
    END IF;
END $$;

ALTER TABLE operations
    ADD COLUMN superseded_at timestamptz,
    ADD COLUMN workflow_started_at timestamptz,
    ADD COLUMN attempt_generation integer NOT NULL DEFAULT 0 CHECK(attempt_generation>=0),
    ADD COLUMN attempt_id uuid,
    ADD CONSTRAINT processing_attempt_identity CHECK ((attempt_generation=0)=(attempt_id IS NULL));

CREATE UNIQUE INDEX processing_current_source ON operations(source_id)
    WHERE kind='process-file' AND superseded_at IS NULL;
CREATE INDEX processing_dispatch ON operations(updated_at,id)
    WHERE kind='process-file' AND state='running' AND superseded_at IS NULL;
CREATE INDEX artifact_cleanup ON operations(updated_at,id)
    WHERE kind='discard-artifacts' AND state='running';

-- Capture a file's immediate artifact roots with its payload, including an empty set.
ALTER TABLE copy_items ADD COLUMN file_child_ids uuid[] NOT NULL DEFAULT '{}';
