-- Drain the old proxy protocol before changing its persisted contract.
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM uploads WHERE state IN ('created','transferring','uploaded')) THEN
        RAISE EXCEPTION 'drain existing uploads before direct-storage migration';
    END IF;
END $$;
ALTER TABLE uploads ALTER COLUMN candidate_key DROP NOT NULL;
ALTER TABLE uploads
    ADD COLUMN transport text NOT NULL DEFAULT 'legacy',
    ADD COLUMN request_key uuid,
    ADD COLUMN expected_size bigint,
    ADD COLUMN content_md5 text,
    ADD COLUMN multipart_id text,
    ADD COLUMN part_size bigint,
    ADD COLUMN completion_parts jsonb,
    ADD COLUMN expected_etag text,
    ADD COLUMN write_expires_at timestamptz,
    ADD COLUMN result jsonb,
    ADD CONSTRAINT uploads_transport CHECK (transport IN ('legacy','inline','single','multipart')),
    ADD CONSTRAINT uploads_direct_metadata CHECK (
        transport='legacy' OR (request_key IS NOT NULL AND expected_size IS NOT NULL AND expected_size>=0)
    ),
    ADD CONSTRAINT uploads_object_identity CHECK (
        transport='legacy' OR
        (transport='inline' AND candidate_key IS NULL AND multipart_id IS NULL AND part_size IS NULL AND content_md5 IS NULL AND write_expires_at IS NULL) OR
        (transport='single' AND candidate_key IS NOT NULL AND multipart_id IS NULL AND part_size IS NULL AND content_md5 IS NOT NULL) OR
        (transport='multipart' AND candidate_key IS NOT NULL AND part_size IS NOT NULL AND part_size>=5242880 AND content_md5 IS NULL)
    );
ALTER TABLE uploads ALTER COLUMN transport DROP DEFAULT;
CREATE UNIQUE INDEX uploads_request_identity ON uploads(filesystem_id,actor_id,request_key) WHERE request_key IS NOT NULL;
CREATE INDEX uploads_multipart_cleanup ON uploads(updated_at,id) WHERE state IN ('aborted','expired') AND multipart_id IS NOT NULL;
