-- +goose Up
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE TABLE workspace_storage (
 workspace_id uuid PRIMARY KEY,
 quota_bytes bigint NOT NULL CHECK (quota_bytes >= 0),
 used_bytes bigint NOT NULL DEFAULT 0 CHECK (used_bytes >= 0 AND used_bytes <= quota_bytes)
);
CREATE TABLE storages (
 id uuid PRIMARY KEY,
 workspace_id uuid NOT NULL REFERENCES workspace_storage ON DELETE CASCADE,
 name text NOT NULL,
 visibility text NOT NULL CHECK (visibility IN ('private','public')),
 root_node_id uuid UNIQUE NOT NULL,
 allow_blob_files boolean NOT NULL,
 allow_indexing boolean NOT NULL
);
CREATE INDEX storages_workspace_page ON storages (workspace_id,id);
CREATE TABLE nodes (
 id uuid PRIMARY KEY,
 storage_id uuid NOT NULL REFERENCES storages ON DELETE CASCADE,
 parent_id uuid,
 name text NOT NULL,
 kind text NOT NULL CHECK (kind IN ('directory','file')),
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE (storage_id,id),
 FOREIGN KEY (storage_id,parent_id) REFERENCES nodes (storage_id,id) DEFERRABLE INITIALLY DEFERRED,
 CHECK (parent_id IS NULL OR parent_id <> id)
);
CREATE UNIQUE INDEX nodes_sibling ON nodes (storage_id,parent_id,name) WHERE parent_id IS NOT NULL;
CREATE INDEX nodes_name_search ON nodes USING gin (name gin_trgm_ops);
CREATE TABLE files (
 node_id uuid PRIMARY KEY REFERENCES nodes ON DELETE CASCADE,
 version bigint NOT NULL CHECK (version > 0),
 size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
 media_type text NOT NULL,
 text_content text,
 object_key text,
 CHECK (num_nonnulls(text_content,object_key) = 1)
);
CREATE INDEX files_objects ON files (object_key) WHERE object_key IS NOT NULL;
CREATE INDEX files_text_search ON files USING gin (text_content gin_trgm_ops) WHERE text_content IS NOT NULL;
CREATE TABLE file_metadata (
 node_id uuid PRIMARY KEY REFERENCES files ON DELETE CASCADE,
 title text,
 description text,
 semantic_type text,
 context text
);
CREATE TABLE processing (
 file_id uuid PRIMARY KEY REFERENCES files ON DELETE CASCADE,
 stage text NOT NULL CHECK (stage IN ('pending','parsed','enriched','ready')),
 error_code text
);
CREATE INDEX processing_unfinished ON processing (file_id) WHERE stage <> 'ready' AND error_code IS NULL;
CREATE TABLE trash_entries (
 id uuid PRIMARY KEY,
 node_id uuid UNIQUE NOT NULL REFERENCES nodes ON DELETE CASCADE,
 original_parent_id uuid,
 trashed_by text NOT NULL,
 trashed_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE uploads (
 id uuid PRIMARY KEY,
 storage_id uuid NOT NULL REFERENCES storages ON DELETE CASCADE,
 actor text,
 root_id uuid,
 parent_id uuid,
 name text,
 target_node_id uuid,
 expected_version bigint,
 object_key text NOT NULL,
 size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
 media_type text NOT NULL,
 checksum text NOT NULL,
 multipart_id text,
 source_file_id uuid,
 source_version bigint,
 result bytea,
 expires_at timestamptz NOT NULL
);
CREATE INDEX uploads_expiry ON uploads (expires_at);
CREATE INDEX uploads_open_objects ON uploads (object_key) WHERE result IS NULL;
CREATE TABLE idempotency_keys (
 caller text NOT NULL,
 method text NOT NULL,
 key uuid NOT NULL,
 request_hash bytea NOT NULL,
 result bytea,
 expires_at timestamptz NOT NULL,
 PRIMARY KEY (caller,method,key)
);
CREATE INDEX idempotency_keys_expiry ON idempotency_keys (expires_at);
-- +goose Down
DROP TABLE idempotency_keys,uploads,trash_entries,processing,file_metadata,files,nodes,storages,workspace_storage;
