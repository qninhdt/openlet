CREATE TABLE export_attempts (
    id uuid PRIMARY KEY,
    operation_id uuid NOT NULL REFERENCES operations(id),
    object_key text UNIQUE NOT NULL,
    multipart_id text,
    deadline timestamptz NOT NULL,
    expires_at timestamptz,
    size_bytes bigint CHECK(size_bytes>=0)
);
CREATE INDEX exports_reconcile ON operations(updated_at,id) WHERE kind='export-archive' AND state='running';
CREATE INDEX export_attempt_cleanup ON export_attempts(deadline) WHERE multipart_id IS NOT NULL;
