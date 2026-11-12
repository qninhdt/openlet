-- +goose Up
CREATE TABLE users (
 id uuid PRIMARY KEY,
 clerk_subject text UNIQUE NOT NULL,
 display_name text NOT NULL,
 avatar_url text
);
CREATE TABLE workspaces (
 id uuid PRIMARY KEY,
 name text NOT NULL,
 state text NOT NULL CHECK (state IN ('provisioning','active','deleting')),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX workspaces_lifecycle ON workspaces (id) WHERE state <> 'active';
CREATE TABLE invitations (
 id uuid PRIMARY KEY,
 workspace_id uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
 email text NOT NULL,
 token_hash bytea UNIQUE NOT NULL,
 expires_at timestamptz NOT NULL,
 accepted_by uuid REFERENCES users
);
CREATE INDEX invitations_workspace_page ON invitations (workspace_id,id);
CREATE INDEX invitations_expiry ON invitations (expires_at);
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
DROP TABLE idempotency_keys,invitations,workspaces,users;
