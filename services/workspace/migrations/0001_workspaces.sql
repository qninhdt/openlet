CREATE TABLE workspaces (
    id uuid PRIMARY KEY,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
    state text NOT NULL DEFAULT 'provisioning' CHECK (state IN ('provisioning','active','deleting','deleted')),
    revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
    provision_key text UNIQUE NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE workspace_members (
    workspace_id uuid NOT NULL REFERENCES workspaces(id),
    user_id uuid NOT NULL,
    role text NOT NULL CHECK (role IN ('owner','editor','viewer')),
    joined_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(workspace_id,user_id)
);
CREATE UNIQUE INDEX workspace_one_owner ON workspace_members(workspace_id) WHERE role='owner';
CREATE INDEX workspace_members_by_user ON workspace_members(user_id,workspace_id);
CREATE TABLE workspace_storage (
    workspace_id uuid PRIMARY KEY REFERENCES workspaces(id),
    quota_bucket_id uuid UNIQUE NOT NULL,
    filesystem_id uuid UNIQUE NOT NULL,
    root_id uuid UNIQUE NOT NULL,
    limit_bytes bigint NOT NULL CHECK (limit_bytes >= 0)
);
CREATE TABLE operations (
    id uuid PRIMARY KEY,
    workspace_id uuid NOT NULL REFERENCES workspaces(id),
    actor_id uuid NOT NULL,
    kind text NOT NULL CHECK (kind IN ('create','delete')),
    request_key uuid NOT NULL,
    fingerprint text NOT NULL,
    state text NOT NULL DEFAULT 'running' CHECK (state IN ('running','succeeded','failed')),
    error_code text,
    result jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(actor_id,kind,request_key)
);
CREATE INDEX workspace_operations_scope ON operations(workspace_id,id);
CREATE TABLE workspace_invitations (
    id uuid PRIMARY KEY,
    workspace_id uuid NOT NULL REFERENCES workspaces(id),
    email text NOT NULL CHECK (length(email) BETWEEN 3 AND 254),
    role text NOT NULL CHECK (role IN ('editor','viewer')),
    token_hash bytea UNIQUE NOT NULL CHECK (octet_length(token_hash)=32),
    expires_at timestamptz NOT NULL,
    state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','revoked','accepted')),
    accepted_user_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((state='accepted')=(accepted_user_id IS NOT NULL))
);
CREATE INDEX workspace_invitation_page ON workspace_invitations(workspace_id,id);
