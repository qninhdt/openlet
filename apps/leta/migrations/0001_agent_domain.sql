-- +goose Up
CREATE TABLE agents (
    id uuid PRIMARY KEY,
    leta_id uuid NOT NULL,
    kind text NOT NULL CHECK (kind IN ('leta','leti')),
    workspace_id uuid,
    created_by_user_id uuid,
    home_scope_id uuid UNIQUE,
    box_id uuid,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    description text NOT NULL,
    system_prompt text NOT NULL,
    model_id text,
    reasoning_effort text,
    status text NOT NULL DEFAULT 'initializing' CHECK (status IN ('initializing','active','deleting','archived')),
    paused boolean NOT NULL DEFAULT false,
    inbox_seq bigint NOT NULL DEFAULT 0 CHECK (inbox_seq >= 0),
    activity_seq bigint NOT NULL DEFAULT 0 CHECK (activity_seq >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    archived_at timestamptz,
    UNIQUE (id,leta_id),
    UNIQUE (id,box_id),
    FOREIGN KEY (leta_id) REFERENCES agents(id),
    CHECK (
      (kind='leta' AND id=leta_id AND workspace_id IS NOT NULL AND created_by_user_id IS NOT NULL
       AND home_scope_id IS NOT NULL AND box_id IS NULL AND model_id IS NOT NULL)
      OR (kind='leti' AND id<>leta_id AND workspace_id IS NULL AND created_by_user_id IS NULL
          AND home_scope_id IS NULL AND box_id IS NOT NULL AND NOT paused)
    ),
    CHECK ((status='archived') = (archived_at IS NOT NULL))
);
CREATE UNIQUE INDEX agents_live_leti_name ON agents(leta_id,name) WHERE kind='leti' AND status<>'archived';
CREATE INDEX agents_workspace ON agents(workspace_id,id) WHERE kind='leta';

CREATE TABLE boxes (
    id uuid PRIMARY KEY,
    leta_id uuid NOT NULL REFERENCES agents(id),
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    description text NOT NULL,
    representative_agent_id uuid NOT NULL,
    home_node_id uuid NOT NULL UNIQUE,
    status text NOT NULL DEFAULT 'initializing' CHECK (status IN ('initializing','active','deleting','archived')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    archived_at timestamptz,
    UNIQUE (id,leta_id),
    CHECK ((status='archived') = (archived_at IS NOT NULL)),
    FOREIGN KEY (representative_agent_id,id) REFERENCES agents(id,box_id) DEFERRABLE INITIALLY DEFERRED
);
CREATE UNIQUE INDEX boxes_live_name ON boxes(leta_id,name) WHERE status<>'archived';
ALTER TABLE agents ADD FOREIGN KEY (box_id,leta_id) REFERENCES boxes(id,leta_id) DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE box_edges (
    box_id uuid NOT NULL REFERENCES boxes(id),
    agent_low_id uuid NOT NULL,
    agent_high_id uuid NOT NULL,
    PRIMARY KEY (box_id,agent_low_id,agent_high_id),
    CHECK (agent_low_id < agent_high_id),
    FOREIGN KEY (agent_low_id,box_id) REFERENCES agents(id,box_id),
    FOREIGN KEY (agent_high_id,box_id) REFERENCES agents(id,box_id)
);

CREATE TABLE messages (
    id uuid PRIMARY KEY,
    leta_id uuid NOT NULL REFERENCES agents(id),
    sender_agent_id uuid,
    recipient_agent_id uuid,
    recipient_user_id uuid,
    seq bigint,
    source_type text NOT NULL CHECK (length(source_type) BETWEEN 1 AND 100),
    source_id text NOT NULL CHECK (length(source_id) BETWEEN 1 AND 200),
    source_label text NOT NULL,
    conversation_key text,
    reply_to jsonb,
    in_reply_to_message_id uuid REFERENCES messages(id),
    content text NOT NULL,
    data jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    read_at timestamptz,
    UNIQUE (recipient_agent_id,seq),
    UNIQUE (id,leta_id),
    FOREIGN KEY (sender_agent_id,leta_id) REFERENCES agents(id,leta_id),
    FOREIGN KEY (recipient_agent_id,leta_id) REFERENCES agents(id,leta_id),
    FOREIGN KEY (in_reply_to_message_id,leta_id) REFERENCES messages(id,leta_id),
    CHECK ((recipient_agent_id IS NOT NULL AND recipient_user_id IS NULL AND seq IS NOT NULL AND seq>0)
        OR (recipient_agent_id IS NULL AND recipient_user_id IS NOT NULL AND seq IS NULL))
);
CREATE INDEX messages_inbox_group ON messages(recipient_agent_id,conversation_key,seq);
CREATE INDEX messages_unread ON messages(recipient_agent_id,seq) WHERE read_at IS NULL;
CREATE INDEX messages_conversation ON messages(leta_id,conversation_key,created_at,id);
CREATE INDEX messages_human ON messages(recipient_user_id,created_at,id) WHERE recipient_user_id IS NOT NULL;

CREATE TABLE runs (
    id uuid PRIMARY KEY,
    agent_id uuid NOT NULL REFERENCES agents(id),
    status text NOT NULL DEFAULT 'running' CHECK (status IN ('running','paused','completed','failed','cancelled')),
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    attempt integer NOT NULL DEFAULT 1 CHECK (attempt>0),
    inbox_cursor bigint NOT NULL DEFAULT 0 CHECK (inbox_cursor>=0),
    checkpoint_id text,
    checkpoint_ns text,
    continuation jsonb,
    yield_requested boolean NOT NULL DEFAULT false,
    result jsonb,
    error jsonb,
    UNIQUE (id,agent_id),
    CHECK ((status IN ('completed','failed','cancelled')) = (finished_at IS NOT NULL))
);
CREATE UNIQUE INDEX runs_unfinished ON runs(agent_id) WHERE status IN ('running','paused');
CREATE INDEX runs_agent ON runs(agent_id,started_at,id);

CREATE TABLE activity_log (
    id uuid PRIMARY KEY,
    agent_id uuid NOT NULL REFERENCES agents(id),
    run_id uuid,
    seq bigint NOT NULL CHECK (seq>0),
    kind text NOT NULL CHECK (kind IN ('inbox_input','assistant','tool_call','tool_result','final_note','compaction')),
    llm_message_id text,
    tool_call_id text,
    message_id uuid REFERENCES messages(id),
    dedup_key text NOT NULL,
    data jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (agent_id,seq),
    UNIQUE (agent_id,dedup_key),
    FOREIGN KEY (run_id,agent_id) REFERENCES runs(id,agent_id)
);
CREATE INDEX activity_log_run ON activity_log(agent_id,run_id,seq);

CREATE TABLE hitl_requests (
    id uuid PRIMARY KEY,
    leta_id uuid NOT NULL REFERENCES agents(id),
    requester_agent_id uuid NOT NULL,
    kind text NOT NULL CHECK (kind IN ('ask','approval')),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','resolved','cancelled','expired')),
    title text NOT NULL,
    payload jsonb NOT NULL,
    approver_user_id uuid NOT NULL,
    grantee_leta_id uuid REFERENCES agents(id),
    resource jsonb,
    requested_role text,
    decision jsonb,
    outcome jsonb,
    outcome_message_id uuid NOT NULL UNIQUE,
    grant_key uuid UNIQUE,
    expires_at timestamptz,
    resolved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (requester_agent_id,leta_id) REFERENCES agents(id,leta_id),
    CHECK ((status='pending') = (resolved_at IS NULL)),
    CHECK ((kind='ask' AND grantee_leta_id IS NULL AND resource IS NULL AND requested_role IS NULL AND grant_key IS NULL)
        OR (kind='approval' AND grantee_leta_id IS NOT NULL AND grantee_leta_id=leta_id AND resource IS NOT NULL
            AND requested_role IS NOT NULL AND requested_role IN ('viewer','editor') AND grant_key IS NOT NULL))
);
CREATE INDEX hitl_approver ON hitl_requests(approver_user_id,status,created_at,id);
CREATE INDEX hitl_requester ON hitl_requests(requester_agent_id,created_at,id);
CREATE INDEX hitl_unsettled ON hitl_requests(leta_id,id) WHERE status='pending' OR outcome IS NULL;

CREATE TABLE schedules (
    id uuid PRIMARY KEY,
    leta_id uuid NOT NULL REFERENCES agents(id),
    creator_agent_id uuid NOT NULL,
    target_agent_id uuid NOT NULL,
    box_id uuid,
    title text NOT NULL,
    content text NOT NULL,
    spec jsonb NOT NULL CHECK (spec ? 'type' AND spec->>'type' IS NOT NULL AND spec->>'type' IN ('at','interval','calendar')),
    paused boolean NOT NULL DEFAULT false,
    end_at timestamptz,
    deleted_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (creator_agent_id,leta_id) REFERENCES agents(id,leta_id),
    FOREIGN KEY (target_agent_id,leta_id) REFERENCES agents(id,leta_id),
    FOREIGN KEY (box_id,leta_id) REFERENCES boxes(id,leta_id),
    CHECK (spec->>'type'<>'at' OR end_at IS NULL)
);
CREATE INDEX schedules_root ON schedules(leta_id,id);
CREATE INDEX schedules_target ON schedules(target_agent_id,id) WHERE deleted_at IS NULL;
