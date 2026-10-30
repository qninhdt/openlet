CREATE TABLE file_data (
    node_id uuid PRIMARY KEY REFERENCES nodes(id) ON DELETE CASCADE,
    storage_kind text NOT NULL CHECK (storage_kind IN ('inline','object')),
    inline_bytes bytea,
    object_key text UNIQUE,
    CHECK ((storage_kind='inline' AND inline_bytes IS NOT NULL AND object_key IS NULL)
        OR (storage_kind='object' AND inline_bytes IS NULL AND object_key IS NOT NULL))
);
CREATE TABLE trash_entries (
    id uuid PRIMARY KEY,
    filesystem_id uuid NOT NULL REFERENCES filesystems(id),
    node_id uuid NOT NULL UNIQUE REFERENCES nodes(id),
    original_parent_id uuid,
    original_name text NOT NULL,
    actor_id uuid NOT NULL,
    state text NOT NULL DEFAULT 'trashed' CHECK (state IN ('trashed','purging')),
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY(filesystem_id,node_id) REFERENCES nodes(filesystem_id,id)
);
CREATE INDEX trash_page ON trash_entries(filesystem_id,id);
CREATE TABLE operations (
    id uuid PRIMARY KEY,
    filesystem_id uuid NOT NULL REFERENCES filesystems(id),
    actor_id uuid NOT NULL,
    kind text NOT NULL,
    request_key uuid NOT NULL,
    fingerprint jsonb NOT NULL,
    state text NOT NULL DEFAULT 'running' CHECK (state IN ('running','succeeded','discarding','failed')),
    result_node_id uuid,
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(filesystem_id,actor_id,kind,request_key)
);
CREATE INDEX operations_outstanding ON operations(filesystem_id,state) WHERE state IN ('running','discarding');
