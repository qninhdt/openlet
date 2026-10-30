CREATE TABLE uploads (
    id uuid PRIMARY KEY,
    filesystem_id uuid NOT NULL REFERENCES filesystems(id),
    bucket_id uuid NOT NULL REFERENCES quota_buckets(id),
    actor_id uuid NOT NULL,
    input jsonb NOT NULL,
    candidate_key text UNIQUE NOT NULL,
    state text NOT NULL DEFAULT 'created' CHECK(state IN ('created','transferring','uploaded','finalized','aborted','expired')),
    expires_at timestamptz NOT NULL DEFAULT (now()+interval '1 hour'),
    transfer_deadline timestamptz,
    size_bytes bigint CHECK(size_bytes>=0),
    sha256 text,
    inline_bytes bytea,
    result_node_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX uploads_outstanding ON uploads(bucket_id,state,expires_at) WHERE state IN ('created','transferring','uploaded');
