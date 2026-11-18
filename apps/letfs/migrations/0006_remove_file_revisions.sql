-- +goose Up
UPDATE workspace_storage w
SET used_bytes = w.used_bytes - retained.bytes
FROM (
 SELECT s.workspace_id, sum(r.size_bytes)::bigint AS bytes
 FROM file_revisions r
 JOIN nodes n ON n.id = r.node_id
 JOIN storages s ON s.id = n.storage_id
 GROUP BY s.workspace_id
) retained
WHERE w.workspace_id = retained.workspace_id;
DROP TABLE file_revisions;

-- +goose Down
-- Rollback restores the schema only; discarded historical contents cannot be recovered.
CREATE TABLE file_revisions (
 node_id uuid NOT NULL REFERENCES files(node_id) ON DELETE CASCADE,
 version bigint NOT NULL CHECK (version > 0),
 size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
 media_type text NOT NULL,
 text_content text,
 object_key text,
 replaced_by text NOT NULL,
 replaced_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (node_id,version),
 CHECK (num_nonnulls(text_content,object_key) = 1)
);
CREATE INDEX file_revisions_objects ON file_revisions(object_key) WHERE object_key IS NOT NULL;
