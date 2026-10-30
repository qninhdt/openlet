CREATE TABLE quota_buckets (
    id uuid PRIMARY KEY,
    provision_key text UNIQUE NOT NULL CHECK (length(provision_key) BETWEEN 1 AND 200),
    limit_bytes bigint NOT NULL CHECK (limit_bytes >= 0),
    used_bytes bigint NOT NULL DEFAULT 0 CHECK (used_bytes >= 0),
    state text NOT NULL DEFAULT 'active' CHECK (state IN ('active','frozen','deleted')),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE filesystems (
    id uuid PRIMARY KEY,
    bucket_id uuid NOT NULL REFERENCES quota_buckets(id),
    provision_key text UNIQUE NOT NULL CHECK (length(provision_key) BETWEEN 1 AND 200),
    root_id uuid NOT NULL,
    state text NOT NULL DEFAULT 'active' CHECK (state IN ('active','deleting','deleted')),
    node_count bigint NOT NULL DEFAULT 1 CHECK (node_count >= 0),
    max_nodes bigint NOT NULL CHECK (max_nodes > 0 AND node_count <= max_nodes),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX filesystems_bucket ON filesystems(bucket_id,id);
CREATE TABLE nodes (
    id uuid PRIMARY KEY,
    filesystem_id uuid NOT NULL REFERENCES filesystems(id),
    parent_id uuid,
    name text COLLATE "C" NOT NULL CHECK (octet_length(name) BETWEEN 1 AND 255 AND name NOT IN ('.','..') AND position('/' in name)=0),
    kind text NOT NULL CHECK (kind IN ('file','directory')),
    size_bytes bigint NOT NULL DEFAULT 0 CHECK (size_bytes >= 0),
    revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
    staging_operation_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(filesystem_id,id),
    UNIQUE(filesystem_id,parent_id,name),
    FOREIGN KEY(filesystem_id,parent_id) REFERENCES nodes(filesystem_id,id)
);
ALTER TABLE filesystems ADD CONSTRAINT filesystem_root FOREIGN KEY(id,root_id) REFERENCES nodes(filesystem_id,id) DEFERRABLE INITIALLY DEFERRED;
