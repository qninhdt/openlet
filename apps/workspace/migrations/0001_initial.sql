-- +goose Up
-- +goose StatementBegin
CREATE TABLE public.idempotency_keys (
    actor_id uuid NOT NULL,
    operation text NOT NULL CHECK (operation = 'create-workspace'),
    request_key uuid NOT NULL,
    request_hash text NOT NULL,
    request_input jsonb NOT NULL,
    workspace_id uuid NOT NULL,
    workflow_id text NOT NULL UNIQUE,
    completed_at timestamptz,
    expires_at timestamptz,
    PRIMARY KEY (actor_id, operation, request_key),
    CHECK ((completed_at IS NULL) = (expires_at IS NULL)),
    CHECK (expires_at IS NULL OR expires_at = completed_at + interval '24 hours')
);

CREATE TABLE public.workspace_invitations (
    id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    email text NOT NULL,
    role text NOT NULL,
    token_hash bytea NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    accepted_user_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT workspace_invitations_check CHECK (((status = 'accepted'::text) = (accepted_user_id IS NOT NULL))),
    CONSTRAINT workspace_invitations_email_check CHECK (((length(email) >= 3) AND (length(email) <= 254))),
    CONSTRAINT workspace_invitations_role_check CHECK ((role = ANY (ARRAY['editor'::text, 'viewer'::text]))),
    CONSTRAINT workspace_invitations_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'revoked'::text, 'accepted'::text, 'expired'::text]))),
    CONSTRAINT workspace_invitations_token_hash_check CHECK ((octet_length(token_hash) = 32))
);

CREATE TABLE public.workspace_members (
    workspace_id uuid NOT NULL,
    user_id uuid NOT NULL,
    role text NOT NULL,
    joined_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT workspace_members_role_check CHECK ((role = ANY (ARRAY['owner'::text, 'editor'::text, 'viewer'::text])))
);

CREATE TABLE public.workspaces (
    id uuid NOT NULL,
    name text NOT NULL,
    status text DEFAULT 'provisioning'::text NOT NULL,
    quota_bucket_id uuid UNIQUE,
    filesystem_id uuid UNIQUE,
    root_id uuid UNIQUE,
    limit_bytes bigint NOT NULL CHECK (limit_bytes >= 0),
    CHECK (status != 'active' OR (quota_bucket_id IS NOT NULL AND filesystem_id IS NOT NULL AND root_id IS NOT NULL)),
    revision bigint DEFAULT 1 NOT NULL,
    creation_workflow_id text NOT NULL,
    error_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT workspaces_name_check CHECK (((length(name) >= 1) AND (length(name) <= 100))),
    CONSTRAINT workspaces_revision_check CHECK ((revision > 0)),
    CONSTRAINT workspaces_status_check CHECK ((status = ANY (ARRAY['provisioning'::text, 'active'::text, 'deleting'::text, 'deleted'::text, 'failed'::text])))
);

ALTER TABLE ONLY public.workspace_invitations
    ADD CONSTRAINT workspace_invitations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.workspace_invitations
    ADD CONSTRAINT workspace_invitations_token_hash_key UNIQUE (token_hash);

ALTER TABLE ONLY public.workspace_members
    ADD CONSTRAINT workspace_members_pkey PRIMARY KEY (workspace_id, user_id);

ALTER TABLE ONLY public.workspaces
    ADD CONSTRAINT workspaces_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.workspaces
    ADD CONSTRAINT workspaces_creation_workflow_id_key UNIQUE (creation_workflow_id);

CREATE UNIQUE INDEX workspace_pending_invitation ON public.workspace_invitations(workspace_id,email) WHERE status='pending';

CREATE INDEX workspace_invitation_page ON public.workspace_invitations USING btree (workspace_id, id);

CREATE INDEX workspace_members_by_user ON public.workspace_members USING btree (user_id, workspace_id);

CREATE UNIQUE INDEX workspace_one_owner ON public.workspace_members USING btree (workspace_id) WHERE (role = 'owner'::text);

CREATE INDEX workspace_pending_lifecycle ON public.workspaces(updated_at,id) WHERE status IN ('provisioning','deleting');
CREATE INDEX workspace_receipt_expiry ON public.idempotency_keys(expires_at) WHERE expires_at IS NOT NULL;

ALTER TABLE ONLY public.idempotency_keys
    ADD FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);

ALTER TABLE ONLY public.workspace_invitations
    ADD CONSTRAINT workspace_invitations_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);

ALTER TABLE ONLY public.workspace_members
    ADD CONSTRAINT workspace_members_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);

-- +goose StatementEnd
