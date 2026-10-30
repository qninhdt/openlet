CREATE TABLE object_deletions (
    object_key text PRIMARY KEY,
    bucket_id uuid NOT NULL REFERENCES quota_buckets(id),
    eligible_at timestamptz NOT NULL DEFAULT (now()+interval '15 minutes'),
    state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','deleting','deleted')),
    ambiguous_write boolean NOT NULL DEFAULT false,
    attempts bigint NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX object_deletions_backlog ON object_deletions(bucket_id,eligible_at) WHERE state!='deleted';
