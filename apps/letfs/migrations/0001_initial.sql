-- +goose Up
-- +goose StatementBegin
CREATE TABLE public.idempotency_keys (
    scope text NOT NULL,
    operation text NOT NULL,
    request_key text NOT NULL,
    request_hash text NOT NULL,
    result jsonb NOT NULL,
    expires_at timestamptz,
    PRIMARY KEY (scope,operation,request_key)
);
CREATE INDEX letfs_receipt_expiry ON public.idempotency_keys(expires_at) WHERE expires_at IS NOT NULL;
CREATE INDEX processing_receipts ON public.idempotency_keys((result->>'file_id'),(result->>'generation')) WHERE operation='process-file' AND expires_at IS NULL;
CREATE INDEX upload_receipts ON public.idempotency_keys((result->>'id')) WHERE operation='create-upload' AND expires_at IS NULL;

CREATE TABLE public.files (
    node_id uuid NOT NULL,
    media_type text,
    title text,
    description text,
    semantic_type text,
    context text,
    storage_kind text NOT NULL,
    inline_bytes bytea,
    object_key text,
    desired_generation bigint DEFAULT 0 NOT NULL CHECK (desired_generation >= 0),
    processing_format text,
    publication_status text DEFAULT 'not_required' NOT NULL CHECK (publication_status IN ('not_required','pending','parsed','enriched','ready','failed','index_failed')),
    processing_error text,
    processing_updated_at timestamptz DEFAULT now() NOT NULL,
    CHECK (publication_status='not_required' OR (desired_generation>0 AND processing_format IS NOT NULL)),
    CONSTRAINT files_payload_check CHECK ((((storage_kind = 'inline'::text) AND (inline_bytes IS NOT NULL) AND (object_key IS NULL)) OR ((storage_kind = 'object'::text) AND (inline_bytes IS NULL) AND (object_key IS NOT NULL)))),
    CONSTRAINT files_storage_kind_check CHECK ((storage_kind = ANY (ARRAY['inline'::text, 'object'::text])))
);

CREATE TABLE public.filesystems (
    id uuid PRIMARY KEY,
    limit_bytes bigint NOT NULL CHECK (limit_bytes >= 0),
    used_bytes bigint DEFAULT 0 NOT NULL CHECK (used_bytes >= 0),
    node_count bigint DEFAULT 0 NOT NULL CHECK (node_count >= 0),
    state text DEFAULT 'active' NOT NULL CHECK (state IN ('active','deleting','deleted')),
    created_at timestamptz DEFAULT now() NOT NULL
);

CREATE TABLE public.scopes (
    id uuid PRIMARY KEY,
    filesystem_id uuid NOT NULL REFERENCES public.filesystems(id),
    root_id uuid,
    allow_blob_files boolean NOT NULL DEFAULT true,
    allow_indexing boolean NOT NULL DEFAULT true,
    state text DEFAULT 'active' NOT NULL CHECK (state IN ('active','deleting','deleted')),
    created_at timestamptz DEFAULT now() NOT NULL,
    CHECK (state <> 'active' OR root_id IS NOT NULL)
);
CREATE INDEX scopes_by_filesystem ON public.scopes(filesystem_id,id);

CREATE TABLE public.nodes (
    id uuid NOT NULL,
    scope_id uuid NOT NULL,
    parent_id uuid,
    name text NOT NULL COLLATE pg_catalog."C",
    kind text NOT NULL,
    size_bytes bigint DEFAULT 0 NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT nodes_kind_check CHECK ((kind = ANY (ARRAY['file'::text, 'directory'::text]))),
    CONSTRAINT nodes_name_check CHECK ((((octet_length(name) >= 1) AND (octet_length(name) <= 255)) AND (name <> ALL (ARRAY['.'::text, '..'::text])) AND (POSITION(('/'::text) IN (name)) = 0))),
    CONSTRAINT nodes_revision_check CHECK ((revision > 0)),
    CONSTRAINT nodes_size_bytes_check CHECK ((size_bytes >= 0))
);

CREATE TABLE public.object_deletions (
    object_key text NOT NULL,
    filesystem_id uuid NOT NULL,
    eligible_at timestamp with time zone DEFAULT (now() + '00:15:00'::interval) NOT NULL,
    state text DEFAULT 'pending'::text NOT NULL,
    ambiguous_write boolean DEFAULT false NOT NULL,
    open_writes bigint DEFAULT 0 NOT NULL CHECK (open_writes >= 0),
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT object_deletions_state_check CHECK ((state = ANY (ARRAY['pending'::text, 'deleting'::text, 'deleted'::text])))
);

CREATE TABLE public.index_deletions (
    file_id uuid NOT NULL,
    generation bigint NOT NULL CHECK (generation > 0),
    eligible_at timestamptz DEFAULT now() NOT NULL,
    PRIMARY KEY (file_id,generation)
);
CREATE INDEX index_deletions_due ON public.index_deletions (eligible_at);

CREATE TABLE public.trash_entries (
    id uuid NOT NULL,
    scope_id uuid NOT NULL,
    node_id uuid NOT NULL,
    original_parent_id uuid,
    original_name text NOT NULL,
    actor_id uuid NOT NULL,
    actor_kind text NOT NULL CHECK (actor_kind IN ('user','leta')),
    state text DEFAULT 'trashed'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT trash_entries_state_check CHECK ((state = ANY (ARRAY['trashed'::text, 'purging'::text])))
);

CREATE TABLE public.uploads (
    id uuid NOT NULL,
    scope_id uuid NOT NULL,
    actor_id uuid,
    actor_kind text CHECK (actor_kind IN ('user','leta')),
    input jsonb NOT NULL,
    candidate_key text,
    state text DEFAULT 'open'::text NOT NULL,
    expires_at timestamp with time zone DEFAULT (now() + '01:00:00'::interval) NOT NULL,
    transfer_deadline timestamp with time zone,
    inline_bytes bytea,
    result_node_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    transport text NOT NULL,
    expected_size bigint,
    content_md5 text,
    multipart_id text,
    part_size bigint,
    completion_parts jsonb,
    result jsonb,
    processing_file_id uuid,
    processing_generation bigint,
    relative_path text,
    processing_stage text,
    CONSTRAINT uploads_direct_metadata CHECK ((((expected_size IS NOT NULL) AND (expected_size >= 0)))),
    CONSTRAINT uploads_object_identity CHECK ((((transport = 'inline'::text) AND (candidate_key IS NULL) AND (multipart_id IS NULL) AND (part_size IS NULL) AND (content_md5 IS NULL) AND (transfer_deadline IS NULL)) OR ((transport = 'single'::text) AND (candidate_key IS NOT NULL) AND (multipart_id IS NULL) AND (part_size IS NULL) AND (content_md5 IS NOT NULL)) OR ((transport = 'multipart'::text) AND (candidate_key IS NOT NULL) AND (part_size IS NOT NULL) AND (part_size >= 5242880) AND (content_md5 IS NULL)))),
    CONSTRAINT uploads_processing_owner CHECK (
      (actor_id IS NOT NULL AND actor_kind IS NOT NULL AND processing_file_id IS NULL AND processing_generation IS NULL AND relative_path IS NULL AND processing_stage IS NULL)
      OR (actor_id IS NULL AND actor_kind IS NULL AND processing_file_id IS NOT NULL AND processing_generation IS NOT NULL AND processing_generation > 0 AND relative_path IS NOT NULL AND processing_stage IS NOT NULL AND processing_stage IN ('parse','enrichment'))
    ),
    CONSTRAINT uploads_state_check CHECK ((state = ANY (ARRAY['open'::text, 'completing'::text, 'finalized'::text, 'aborted'::text]))),
    CONSTRAINT uploads_finalized_result CHECK (state != 'finalized' OR result IS NOT NULL),
    CONSTRAINT uploads_transport CHECK ((transport = ANY (ARRAY['inline'::text, 'single'::text, 'multipart'::text])))
);

ALTER TABLE ONLY public.files
    ADD CONSTRAINT files_object_key_key UNIQUE (object_key);

ALTER TABLE ONLY public.files
    ADD CONSTRAINT files_pkey PRIMARY KEY (node_id);

ALTER TABLE ONLY public.nodes
    ADD CONSTRAINT nodes_scope_id_id_key UNIQUE (scope_id, id);

ALTER TABLE ONLY public.nodes
    ADD CONSTRAINT nodes_scope_id_parent_id_name_key UNIQUE (scope_id, parent_id, name);

ALTER TABLE ONLY public.nodes
    ADD CONSTRAINT nodes_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.object_deletions
    ADD CONSTRAINT object_deletions_pkey PRIMARY KEY (object_key);

ALTER TABLE ONLY public.trash_entries
    ADD CONSTRAINT trash_entries_node_id_key UNIQUE (node_id);

ALTER TABLE ONLY public.trash_entries
    ADD CONSTRAINT trash_entries_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.uploads
    ADD CONSTRAINT uploads_candidate_key_key UNIQUE (candidate_key);

ALTER TABLE ONLY public.uploads
    ADD CONSTRAINT uploads_pkey PRIMARY KEY (id);

CREATE INDEX nodes_detached_roots ON public.nodes USING btree (scope_id, id) WHERE parent_id IS NULL;
CREATE INDEX nodes_children_page ON public.nodes(scope_id,parent_id,id);



CREATE INDEX object_deletions_backlog ON public.object_deletions USING btree (filesystem_id, eligible_at) WHERE (state <> 'deleted'::text OR ambiguous_write OR open_writes>0);

CREATE INDEX object_deletions_due ON public.object_deletions USING btree (eligible_at, object_key);
CREATE INDEX object_deletions_by_filesystem ON public.object_deletions(filesystem_id);


CREATE INDEX processing_dispatch ON public.files (processing_updated_at,node_id) WHERE publication_status IN ('pending','parsed','enriched');


CREATE INDEX trash_page ON public.trash_entries USING btree (scope_id, id);
CREATE INDEX trash_original_parent ON public.trash_entries(scope_id,original_parent_id) WHERE original_parent_id IS NOT NULL;

CREATE INDEX uploads_multipart_cleanup ON public.uploads USING btree (updated_at, id) WHERE ((state = ANY (ARRAY['aborted'::text])) AND (multipart_id IS NOT NULL));

CREATE INDEX uploads_outstanding ON public.uploads USING btree (scope_id, state, expires_at) WHERE (state = ANY (ARRAY['open'::text, 'completing'::text]));
CREATE INDEX uploads_processing ON public.uploads(processing_file_id,processing_generation) WHERE processing_file_id IS NOT NULL;
CREATE INDEX uploads_by_scope ON public.uploads(scope_id);
CREATE INDEX uploads_user_outstanding ON public.uploads(scope_id) WHERE processing_file_id IS NULL AND state IN ('open','completing');


ALTER TABLE ONLY public.files
    ADD CONSTRAINT files_node_id_fkey FOREIGN KEY (node_id) REFERENCES public.nodes(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.scopes
    ADD CONSTRAINT scope_root FOREIGN KEY (id, root_id) REFERENCES public.nodes(scope_id, id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.nodes
    ADD CONSTRAINT nodes_scope_id_fkey FOREIGN KEY (scope_id) REFERENCES public.scopes(id);

ALTER TABLE ONLY public.nodes
    ADD CONSTRAINT nodes_scope_id_parent_id_fkey FOREIGN KEY (scope_id, parent_id) REFERENCES public.nodes(scope_id, id);

ALTER TABLE ONLY public.object_deletions
    ADD CONSTRAINT object_deletions_filesystem_id_fkey FOREIGN KEY (filesystem_id) REFERENCES public.filesystems(id);

ALTER TABLE ONLY public.trash_entries
    ADD CONSTRAINT trash_entries_scope_id_fkey FOREIGN KEY (scope_id) REFERENCES public.scopes(id);

ALTER TABLE ONLY public.trash_entries
    ADD CONSTRAINT trash_entries_scope_id_node_id_fkey FOREIGN KEY (scope_id, node_id) REFERENCES public.nodes(scope_id, id);

ALTER TABLE ONLY public.trash_entries
    ADD CONSTRAINT trash_entries_node_id_fkey FOREIGN KEY (node_id) REFERENCES public.nodes(id);

ALTER TABLE ONLY public.uploads
    ADD CONSTRAINT uploads_scope_id_fkey FOREIGN KEY (scope_id) REFERENCES public.scopes(id);


-- +goose StatementEnd
