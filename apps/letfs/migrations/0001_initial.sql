-- +goose Up
-- +goose StatementBegin
CREATE TABLE public.idempotency_keys (
    scope text NOT NULL,
    operation text NOT NULL,
    request_key text NOT NULL,
    request_hash text NOT NULL,
    result jsonb NOT NULL,
    completed_at timestamptz,
    expires_at timestamptz,
    PRIMARY KEY (scope,operation,request_key),
    CHECK ((completed_at IS NULL) = (expires_at IS NULL)),
    CHECK (expires_at IS NULL OR expires_at = completed_at + interval '24 hours')
);
CREATE INDEX letfs_receipt_expiry ON public.idempotency_keys(expires_at) WHERE expires_at IS NOT NULL;

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
    processing_actor_id uuid,
    processing_format text,
    processing_source_identity text,
    accepted_attempt integer DEFAULT 0 NOT NULL CHECK (accepted_attempt BETWEEN 0 AND 3),
    accepted_attempt_id uuid,
    publication_status text DEFAULT 'not_required' NOT NULL CHECK (publication_status IN ('not_required','pending','parsed','ready','failed')),
    published_generation bigint,
    artifact_root_id uuid,
    parse_manifest_hash text,
    publication_manifest_hash text,
    index_status text DEFAULT 'not_required' NOT NULL CHECK (index_status IN ('not_required','pending','ready','failed')),
    indexed_generation bigint,
    embedding_model text,
    vector_collection text,
    vector_dimension integer CHECK (vector_dimension > 0),
    processing_error text,
    processing_updated_at timestamptz DEFAULT now() NOT NULL,
    CHECK ((accepted_attempt = 0) = (accepted_attempt_id IS NULL)),
    CHECK (published_generation IS NULL OR published_generation = desired_generation),
    CHECK (indexed_generation IS NULL OR (published_generation IS NOT NULL AND indexed_generation = published_generation)),
    CHECK (publication_status != 'ready' OR published_generation IS NOT NULL),
    CHECK (index_status != 'ready' OR (publication_status='ready' AND indexed_generation IS NOT NULL AND embedding_model IS NOT NULL AND vector_collection IS NOT NULL AND vector_dimension IS NOT NULL)),
    CHECK (publication_status NOT IN ('pending','parsed','ready') OR (desired_generation > 0 AND processing_actor_id IS NOT NULL AND processing_format IS NOT NULL AND processing_source_identity IS NOT NULL)),
    CONSTRAINT files_payload_check CHECK ((((storage_kind = 'inline'::text) AND (inline_bytes IS NOT NULL) AND (object_key IS NULL)) OR ((storage_kind = 'object'::text) AND (inline_bytes IS NULL) AND (object_key IS NOT NULL)))),
    CONSTRAINT files_storage_kind_check CHECK ((storage_kind = ANY (ARRAY['inline'::text, 'object'::text])))
);

CREATE TABLE public.filesystems (
    id uuid NOT NULL,
    bucket_id uuid NOT NULL,
    provision_key text NOT NULL,
    root_id uuid,
    state text DEFAULT 'active'::text NOT NULL,
    node_count bigint DEFAULT 1 NOT NULL,
    max_nodes bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT filesystem_live_root CHECK (((state <> 'active'::text) OR (root_id IS NOT NULL))),
    CONSTRAINT filesystems_check CHECK (((max_nodes > 0) AND (node_count <= max_nodes))),
    CONSTRAINT filesystems_node_count_check CHECK ((node_count >= 0)),
    CONSTRAINT filesystems_provision_key_check CHECK (((length(provision_key) >= 1) AND (length(provision_key) <= 200))),
    CONSTRAINT filesystems_state_check CHECK ((state = ANY (ARRAY['active'::text, 'deleting'::text, 'deleted'::text])))
);

CREATE TABLE public.nodes (
    id uuid NOT NULL,
    filesystem_id uuid NOT NULL,
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
    bucket_id uuid NOT NULL,
    eligible_at timestamp with time zone DEFAULT (now() + '00:15:00'::interval) NOT NULL,
    state text DEFAULT 'pending'::text NOT NULL,
    ambiguous_write boolean DEFAULT false NOT NULL,
    open_writes bigint DEFAULT 0 NOT NULL CHECK (open_writes >= 0),
    attempts bigint DEFAULT 0 NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT object_deletions_state_check CHECK ((state = ANY (ARRAY['pending'::text, 'deleting'::text, 'deleted'::text])))
);

CREATE TABLE public.index_deletions (
    file_id uuid NOT NULL,
    generation bigint NOT NULL CHECK (generation > 0),
    embedding_model text NOT NULL,
    vector_collection text NOT NULL,
    vector_dimension integer NOT NULL CHECK (vector_dimension > 0),
    eligible_at timestamptz DEFAULT now() NOT NULL,
    PRIMARY KEY (file_id,generation,embedding_model,vector_collection,vector_dimension)
);
CREATE INDEX index_deletions_due ON public.index_deletions (eligible_at);

CREATE TABLE public.quota_buckets (
    id uuid NOT NULL,
    provision_key text NOT NULL,
    limit_bytes bigint NOT NULL,
    used_bytes bigint DEFAULT 0 NOT NULL,
    state text DEFAULT 'active'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT quota_buckets_limit_bytes_check CHECK ((limit_bytes >= 0)),
    CONSTRAINT quota_buckets_provision_key_check CHECK (((length(provision_key) >= 1) AND (length(provision_key) <= 200))),
    CONSTRAINT quota_buckets_state_check CHECK ((state = ANY (ARRAY['active'::text, 'frozen'::text, 'deleted'::text]))),
    CONSTRAINT quota_buckets_used_bytes_check CHECK ((used_bytes >= 0))
);

CREATE TABLE public.trash_entries (
    id uuid NOT NULL,
    filesystem_id uuid NOT NULL,
    node_id uuid NOT NULL,
    original_parent_id uuid,
    original_name text NOT NULL,
    actor_id uuid NOT NULL,
    state text DEFAULT 'trashed'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT trash_entries_state_check CHECK ((state = ANY (ARRAY['trashed'::text, 'purging'::text])))
);

CREATE TABLE public.uploads (
    id uuid NOT NULL,
    filesystem_id uuid NOT NULL,
    bucket_id uuid NOT NULL,
    actor_id uuid NOT NULL,
    input jsonb NOT NULL,
    candidate_key text,
    state text DEFAULT 'open'::text NOT NULL,
    expires_at timestamp with time zone DEFAULT (now() + '01:00:00'::interval) NOT NULL,
    transfer_deadline timestamp with time zone,
    size_bytes bigint,
    sha256 text,
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
    write_expires_at timestamp with time zone,
    result jsonb,
    processing_file_id uuid,
    processing_generation bigint,
    processing_attempt integer,
    processing_attempt_id uuid,
    relative_path text,
    processing_stage text,
    CONSTRAINT uploads_direct_metadata CHECK ((((expected_size IS NOT NULL) AND (expected_size >= 0)))),
    CONSTRAINT uploads_object_identity CHECK ((((transport = 'inline'::text) AND (candidate_key IS NULL) AND (multipart_id IS NULL) AND (part_size IS NULL) AND (content_md5 IS NULL) AND (write_expires_at IS NULL)) OR ((transport = 'single'::text) AND (candidate_key IS NOT NULL) AND (multipart_id IS NULL) AND (part_size IS NULL) AND (content_md5 IS NOT NULL)) OR ((transport = 'multipart'::text) AND (candidate_key IS NOT NULL) AND (part_size IS NOT NULL) AND (part_size >= 5242880) AND (content_md5 IS NULL)))),
    CONSTRAINT uploads_processing_owner CHECK (
      (processing_file_id IS NULL AND processing_generation IS NULL AND processing_attempt IS NULL AND processing_attempt_id IS NULL AND relative_path IS NULL AND processing_stage IS NULL)
      OR (processing_file_id IS NOT NULL AND processing_generation IS NOT NULL AND processing_generation > 0 AND relative_path IS NOT NULL AND processing_attempt IS NOT NULL AND processing_attempt BETWEEN 1 AND 3 AND processing_attempt_id IS NOT NULL AND processing_stage IS NOT NULL AND processing_stage IN ('parse','enrichment'))
    ),
    CONSTRAINT uploads_size_bytes_check CHECK ((size_bytes >= 0)),
    CONSTRAINT uploads_state_check CHECK ((state = ANY (ARRAY['open'::text, 'completing'::text, 'finalized'::text, 'aborted'::text]))),
    CONSTRAINT uploads_finalized_result CHECK (state != 'finalized' OR (result IS NOT NULL AND size_bytes IS NOT NULL AND size_bytes = expected_size)),
    CONSTRAINT uploads_transport CHECK ((transport = ANY (ARRAY['inline'::text, 'single'::text, 'multipart'::text])))
);

ALTER TABLE ONLY public.files
    ADD CONSTRAINT files_object_key_key UNIQUE (object_key);

ALTER TABLE ONLY public.files
    ADD CONSTRAINT files_pkey PRIMARY KEY (node_id);

ALTER TABLE ONLY public.filesystems
    ADD CONSTRAINT filesystems_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.filesystems
    ADD CONSTRAINT filesystems_provision_key_key UNIQUE (provision_key);

ALTER TABLE ONLY public.nodes
    ADD CONSTRAINT nodes_filesystem_id_id_key UNIQUE (filesystem_id, id);

ALTER TABLE ONLY public.nodes
    ADD CONSTRAINT nodes_filesystem_id_parent_id_name_key UNIQUE (filesystem_id, parent_id, name);

ALTER TABLE ONLY public.nodes
    ADD CONSTRAINT nodes_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.object_deletions
    ADD CONSTRAINT object_deletions_pkey PRIMARY KEY (object_key);

ALTER TABLE ONLY public.quota_buckets
    ADD CONSTRAINT quota_buckets_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.quota_buckets
    ADD CONSTRAINT quota_buckets_provision_key_key UNIQUE (provision_key);

ALTER TABLE ONLY public.trash_entries
    ADD CONSTRAINT trash_entries_node_id_key UNIQUE (node_id);

ALTER TABLE ONLY public.trash_entries
    ADD CONSTRAINT trash_entries_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.uploads
    ADD CONSTRAINT uploads_candidate_key_key UNIQUE (candidate_key);

ALTER TABLE ONLY public.uploads
    ADD CONSTRAINT uploads_pkey PRIMARY KEY (id);

CREATE INDEX nodes_detached_roots ON public.nodes USING btree (filesystem_id, id) WHERE parent_id IS NULL;

CREATE INDEX filesystems_bucket ON public.filesystems USING btree (bucket_id, id);

CREATE INDEX object_deletions_backlog ON public.object_deletions USING btree (bucket_id, eligible_at) WHERE (state <> 'deleted'::text OR ambiguous_write OR open_writes>0);

CREATE INDEX object_deletions_due ON public.object_deletions USING btree (eligible_at, object_key);


CREATE INDEX processing_dispatch ON public.files (processing_updated_at,node_id) WHERE publication_status IN ('pending','parsed') OR (publication_status='ready' AND index_status='pending');

CREATE UNIQUE INDEX processing_output_path ON public.uploads (processing_file_id, processing_generation, processing_stage, processing_attempt, relative_path);

CREATE INDEX trash_page ON public.trash_entries USING btree (filesystem_id, id);

CREATE INDEX uploads_multipart_cleanup ON public.uploads USING btree (updated_at, id) WHERE ((state = ANY (ARRAY['aborted'::text])) AND (multipart_id IS NOT NULL));

CREATE INDEX uploads_outstanding ON public.uploads USING btree (bucket_id, state, expires_at) WHERE (state = ANY (ARRAY['open'::text, 'completing'::text]));


ALTER TABLE ONLY public.files
    ADD CONSTRAINT files_node_id_fkey FOREIGN KEY (node_id) REFERENCES public.nodes(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.filesystems
    ADD CONSTRAINT filesystem_root FOREIGN KEY (id, root_id) REFERENCES public.nodes(filesystem_id, id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.filesystems
    ADD CONSTRAINT filesystems_bucket_id_fkey FOREIGN KEY (bucket_id) REFERENCES public.quota_buckets(id);

ALTER TABLE ONLY public.nodes
    ADD CONSTRAINT nodes_filesystem_id_fkey FOREIGN KEY (filesystem_id) REFERENCES public.filesystems(id);

ALTER TABLE ONLY public.nodes
    ADD CONSTRAINT nodes_filesystem_id_parent_id_fkey FOREIGN KEY (filesystem_id, parent_id) REFERENCES public.nodes(filesystem_id, id);

ALTER TABLE ONLY public.object_deletions
    ADD CONSTRAINT object_deletions_bucket_id_fkey FOREIGN KEY (bucket_id) REFERENCES public.quota_buckets(id);

ALTER TABLE ONLY public.trash_entries
    ADD CONSTRAINT trash_entries_filesystem_id_fkey FOREIGN KEY (filesystem_id) REFERENCES public.filesystems(id);

ALTER TABLE ONLY public.trash_entries
    ADD CONSTRAINT trash_entries_filesystem_id_node_id_fkey FOREIGN KEY (filesystem_id, node_id) REFERENCES public.nodes(filesystem_id, id);

ALTER TABLE ONLY public.trash_entries
    ADD CONSTRAINT trash_entries_node_id_fkey FOREIGN KEY (node_id) REFERENCES public.nodes(id);

ALTER TABLE ONLY public.uploads
    ADD CONSTRAINT uploads_bucket_id_fkey FOREIGN KEY (bucket_id) REFERENCES public.quota_buckets(id);

ALTER TABLE ONLY public.uploads
    ADD CONSTRAINT uploads_filesystem_id_fkey FOREIGN KEY (filesystem_id) REFERENCES public.filesystems(id);


-- +goose StatementEnd
