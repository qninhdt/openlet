-- +goose Up
-- +goose StatementBegin
CREATE TABLE public.idempotency_keys (
    actor_id uuid NOT NULL,
    request_key uuid NOT NULL,
    request_hash text NOT NULL,
    workspace_id uuid NOT NULL,
    expires_at timestamptz,
    PRIMARY KEY (actor_id, request_key)
);

CREATE TABLE public.workspace_invitations (
    id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    email text NOT NULL,
    role text NOT NULL,
    token_hash bytea NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    accepted_account_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT workspace_invitations_check CHECK (((status = 'accepted'::text) = (accepted_account_id IS NOT NULL))),
    CONSTRAINT workspace_invitations_email_check CHECK (((length(email) >= 3) AND (length(email) <= 254))),
    CONSTRAINT workspace_invitations_role_check CHECK ((role = ANY (ARRAY['admin'::text, 'member'::text]))),
    CONSTRAINT workspace_invitations_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'revoked'::text, 'accepted'::text, 'expired'::text]))),
    CONSTRAINT workspace_invitations_token_hash_check CHECK ((octet_length(token_hash) = 32))
);

CREATE TABLE public.workspace_members (
    workspace_id uuid NOT NULL,
    account_id uuid NOT NULL,
    role text NOT NULL,
    personal_scope_id uuid NOT NULL UNIQUE,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive')),
    joined_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT workspace_members_role_check CHECK ((role = ANY (ARRAY['owner'::text, 'admin'::text, 'member'::text])))
);

CREATE TABLE public.workspaces (
    id uuid NOT NULL,
    name text NOT NULL,
    status text DEFAULT 'active' NOT NULL,
    filesystem_id uuid NOT NULL UNIQUE,
    shared_scope_id uuid NOT NULL UNIQUE,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT workspaces_name_check CHECK (((length(name) >= 1) AND (length(name) <= 100))),
    CONSTRAINT workspaces_status_check CHECK ((status = ANY (ARRAY['active'::text, 'deleting'::text, 'deleted'::text])))
);

ALTER TABLE ONLY public.workspace_invitations
    ADD CONSTRAINT workspace_invitations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.workspace_invitations
    ADD CONSTRAINT workspace_invitations_token_hash_key UNIQUE (token_hash);

ALTER TABLE ONLY public.workspace_members
    ADD CONSTRAINT workspace_members_pkey PRIMARY KEY (workspace_id, account_id);

ALTER TABLE ONLY public.workspaces
    ADD CONSTRAINT workspaces_pkey PRIMARY KEY (id);


CREATE UNIQUE INDEX workspace_pending_invitation ON public.workspace_invitations(workspace_id,email) WHERE status='pending';

CREATE INDEX workspace_invitation_page ON public.workspace_invitations USING btree (workspace_id, id);

CREATE INDEX workspace_members_by_account ON public.workspace_members USING btree (account_id, workspace_id);

CREATE UNIQUE INDEX workspace_one_owner ON public.workspace_members USING btree (workspace_id) WHERE role='owner' AND status='active';

CREATE INDEX workspace_pending_lifecycle ON public.workspaces(updated_at,id) WHERE status='deleting';
CREATE INDEX workspace_receipt_expiry ON public.idempotency_keys(expires_at) WHERE expires_at IS NOT NULL;

ALTER TABLE ONLY public.idempotency_keys
    ADD FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);

ALTER TABLE ONLY public.workspace_invitations
    ADD CONSTRAINT workspace_invitations_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);

ALTER TABLE ONLY public.workspace_members
    ADD CONSTRAINT workspace_members_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);

-- +goose StatementEnd
