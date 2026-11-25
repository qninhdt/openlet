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
  visibility text NOT NULL CHECK (visibility IN ('private', 'public')),
  root_node_id uuid NOT NULL,
  allow_blob_files boolean NOT NULL,
  allow_indexing boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX storages_workspace_page ON storages (workspace_id, id);

CREATE TABLE nodes (
  id uuid PRIMARY KEY,
  storage_id uuid NOT NULL REFERENCES storages ON DELETE CASCADE,
  parent_id uuid REFERENCES nodes ON DELETE CASCADE,
  name text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('directory', 'file')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX nodes_sibling ON nodes (storage_id, parent_id, name) WHERE parent_id IS NOT NULL;
CREATE INDEX nodes_parent ON nodes (storage_id, parent_id, name, id);
CREATE INDEX nodes_name_search ON nodes USING gin (name gin_trgm_ops);

CREATE TABLE blobs (
  id uuid PRIMARY KEY,
  workspace_id uuid NOT NULL REFERENCES workspace_storage ON DELETE CASCADE,
  object_key text NOT NULL UNIQUE,
  size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
  media_type text NOT NULL,
  checksum text NOT NULL,
  source_name text NOT NULL,
  processing_stage text CHECK (processing_stage IS NULL OR processing_stage IN ('queued', 'parsed', 'enriched', 'ready', 'failed')),
  processing_error_code text NOT NULL DEFAULT '',
  processing_attempt integer NOT NULL DEFAULT 0,
  title text NOT NULL DEFAULT '',
  description text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  delete_requested_at timestamptz
);
CREATE INDEX blobs_unfinished ON blobs (id) WHERE delete_requested_at IS NULL AND processing_stage IN ('queued', 'parsed', 'enriched');
CREATE INDEX blobs_delete_requested ON blobs (delete_requested_at) WHERE delete_requested_at IS NOT NULL;

CREATE TABLE files (
  node_id uuid PRIMARY KEY REFERENCES nodes ON DELETE CASCADE,
  version bigint NOT NULL CHECK (version > 0),
  blob_id uuid REFERENCES blobs(id) ON DELETE RESTRICT,
  text_content text,
  size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
  media_type text NOT NULL,
  CONSTRAINT files_storage_check CHECK ((blob_id IS NULL) <> (text_content IS NULL))
);
CREATE INDEX files_blob ON files (blob_id) WHERE blob_id IS NOT NULL;
CREATE INDEX files_text_search ON files USING gin (text_content gin_trgm_ops) WHERE text_content IS NOT NULL;

CREATE TABLE blob_artifacts (
  id uuid PRIMARY KEY,
  blob_id uuid NOT NULL REFERENCES blobs(id) ON DELETE CASCADE,
  path text NOT NULL CHECK (path <> '' AND left(path, 1) <> '/' AND right(path, 1) <> '/'),
  parent_path text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('directory', 'file')),
  media_type text NOT NULL DEFAULT '',
  size_bytes bigint NOT NULL DEFAULT 0 CHECK (size_bytes >= 0),
  checksum text NOT NULL DEFAULT '',
  object_key text,
  text_content text,
  title text NOT NULL DEFAULT '',
  description text NOT NULL DEFAULT '',
  indexable boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT blob_artifacts_path UNIQUE (blob_id, path) DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT blob_artifacts_content CHECK (
    (kind = 'directory' AND text_content IS NULL AND object_key IS NULL)
    OR (kind = 'file' AND num_nonnulls(text_content, object_key) = 1)
  )
);
CREATE INDEX blob_artifacts_parent ON blob_artifacts (blob_id, parent_path, path);
CREATE INDEX blob_artifacts_text_search ON blob_artifacts USING gin (text_content gin_trgm_ops) WHERE text_content IS NOT NULL;

CREATE TABLE trash_entries (
  id uuid PRIMARY KEY,
  node_id uuid UNIQUE NOT NULL REFERENCES nodes ON DELETE CASCADE,
  original_parent_id uuid REFERENCES nodes ON DELETE SET NULL,
  trashed_by text NOT NULL,
  trashed_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE uploads (
  id uuid PRIMARY KEY,
  storage_id uuid NOT NULL REFERENCES storages ON DELETE CASCADE,
  actor text NOT NULL,
  root_id uuid NOT NULL,
  parent_id uuid NOT NULL,
  name text NOT NULL,
  target_node_id uuid,
  expected_version bigint,
  blob_id uuid NOT NULL,
  object_key text NOT NULL,
  size_bytes bigint NOT NULL,
  media_type text NOT NULL,
  checksum text NOT NULL,
  multipart_id text,
  result bytea,
  expires_at timestamptz NOT NULL
);
CREATE INDEX uploads_expiry ON uploads (expires_at);
CREATE INDEX uploads_open_blobs ON uploads (blob_id) WHERE result IS NULL;

CREATE TABLE archive_downloads (
  ticket_hash bytea PRIMARY KEY,
  actor text NOT NULL,
  request bytea NOT NULL,
  expires_at timestamptz NOT NULL
);
CREATE INDEX archive_downloads_expiry ON archive_downloads (expires_at);

CREATE TABLE idempotency_keys (
  caller text NOT NULL,
  method text NOT NULL,
  key uuid NOT NULL,
  request_hash bytea NOT NULL,
  result bytea,
  expires_at timestamptz NOT NULL,
  PRIMARY KEY (caller, method, key)
);
CREATE INDEX idempotency_keys_expiry ON idempotency_keys (expires_at);

-- +goose Down
DROP TABLE idempotency_keys, archive_downloads, uploads, trash_entries, blob_artifacts, files, blobs, nodes, storages, workspace_storage;
