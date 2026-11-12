-- Design for a fresh Leta database; not an active migration.
-- Native LangGraph owns its checkpoint schema and migrations.
-- Box directory provisioning needs the contract decision in boundaries.md.

CREATE TABLE letas (
    id uuid PRIMARY KEY,
    workspace_id uuid NOT NULL,
    storage_id uuid NOT NULL,
    state text NOT NULL CHECK (state IN ('provisioning', 'active', 'deleting', 'archived')),
    paused boolean NOT NULL DEFAULT false
);
CREATE INDEX letas_workspace ON letas (workspace_id, id);

CREATE TABLE agents (
    id uuid PRIMARY KEY,
    leta_id uuid NOT NULL REFERENCES letas(id),
    box_id uuid,
    name text NOT NULL,
    description text NOT NULL DEFAULT '',
    system_prompt text NOT NULL,
    model_id text,
    reasoning_effort text,
    inbox_seq bigint NOT NULL DEFAULT 0 CHECK (inbox_seq >= 0),
    history_seq bigint NOT NULL DEFAULT 0 CHECK (history_seq >= 0),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (leta_id, id),
    UNIQUE (box_id, id),
    UNIQUE (box_id, name)
);

CREATE TABLE boxes (
    id uuid PRIMARY KEY,
    leta_id uuid NOT NULL REFERENCES letas(id),
    name text NOT NULL,
    description text NOT NULL DEFAULT '',
    representative_agent_id uuid NOT NULL,
    home_node_id uuid NOT NULL UNIQUE,
    state text NOT NULL CHECK (state IN ('provisioning', 'active', 'deleting', 'archived')),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (leta_id, id),
    FOREIGN KEY (id, representative_agent_id) REFERENCES agents(box_id, id)
        DEFERRABLE INITIALLY DEFERRED
);
ALTER TABLE agents ADD CONSTRAINT agents_box
    FOREIGN KEY (leta_id, box_id) REFERENCES boxes(leta_id, id);
CREATE UNIQUE INDEX boxes_live_name
    ON boxes (leta_id, name) WHERE state <> 'archived';

CREATE TABLE box_edges (
    box_id uuid NOT NULL REFERENCES boxes(id),
    agent_low_id uuid NOT NULL,
    agent_high_id uuid NOT NULL,
    PRIMARY KEY (box_id, agent_low_id, agent_high_id),
    CHECK (agent_low_id < agent_high_id),
    FOREIGN KEY (box_id, agent_low_id) REFERENCES agents(box_id, id),
    FOREIGN KEY (box_id, agent_high_id) REFERENCES agents(box_id, id)
);

CREATE TABLE agent_messages (
    id uuid PRIMARY KEY,
    recipient_agent_id uuid NOT NULL REFERENCES agents(id),
    seq bigint NOT NULL CHECK (seq > 0),
    source_kind text NOT NULL CHECK (source_kind IN ('user', 'agent', 'box', 'hitl', 'schedule')),
    source_id uuid NOT NULL,
    conversation_id uuid NOT NULL,
    in_reply_to_message_id uuid,
    scheduled_at timestamptz,
    content text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    read_at timestamptz,
    UNIQUE (recipient_agent_id, seq),
    CHECK ((source_kind = 'schedule') = (scheduled_at IS NOT NULL))
);
CREATE INDEX agent_messages_conversation
    ON agent_messages (recipient_agent_id, conversation_id, seq);
CREATE INDEX agent_messages_unread
    ON agent_messages (recipient_agent_id, conversation_id, seq) WHERE read_at IS NULL;
CREATE INDEX agent_messages_user_chat
    ON agent_messages (recipient_agent_id, created_at, id) WHERE source_kind = 'user';

CREATE TABLE user_messages (
    id uuid PRIMARY KEY,
    leta_id uuid NOT NULL REFERENCES letas(id),
    recipient_user_id uuid NOT NULL,
    conversation_id uuid NOT NULL,
    in_reply_to_message_id uuid,
    content text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX user_messages_chat ON user_messages (leta_id, created_at, id);

CREATE TABLE runs (
    id uuid PRIMARY KEY,
    agent_id uuid NOT NULL REFERENCES agents(id),
    status text NOT NULL CHECK (status IN ('running', 'paused', 'completed', 'failed', 'cancelled')),
    started_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at timestamptz,
    error_code text,
    UNIQUE (agent_id, id),
    CHECK ((status IN ('completed', 'failed', 'cancelled')) = (finished_at IS NOT NULL)),
    CHECK ((status = 'failed') = (error_code IS NOT NULL))
);
CREATE UNIQUE INDEX runs_unfinished ON runs (agent_id) WHERE status IN ('running', 'paused');
CREATE INDEX runs_timeline ON runs (agent_id, started_at, id);

CREATE TABLE history (
    id uuid PRIMARY KEY,
    agent_id uuid NOT NULL REFERENCES agents(id),
    run_id uuid NOT NULL,
    seq bigint NOT NULL CHECK (seq > 0),
    kind text NOT NULL CHECK (kind IN ('inbox_input', 'assistant', 'tool_call', 'tool_result', 'final_note', 'compaction')),
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (agent_id, seq),
    FOREIGN KEY (agent_id, run_id) REFERENCES runs(agent_id, id)
);
CREATE INDEX history_run ON history (agent_id, run_id, seq);
CREATE INDEX history_search ON history USING gin
    (jsonb_to_tsvector('simple'::regconfig, payload, '["string"]'::jsonb));

CREATE TABLE hitl_requests (
    id uuid PRIMARY KEY,
    requester_agent_id uuid NOT NULL REFERENCES agents(id),
    recipient_user_id uuid NOT NULL,
    type text NOT NULL CHECK (type IN ('ask', 'approval')),
    title text NOT NULL,
    payload jsonb NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'answered', 'accepted', 'denied', 'cancelled', 'expired')),
    response jsonb,
    outcome jsonb,
    expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at timestamptz,
    CHECK ((status = 'pending') = (resolved_at IS NULL)),
    CHECK (outcome IS NULL OR (type = 'approval' AND status = 'accepted'))
);
CREATE INDEX hitl_requests_recipient ON hitl_requests (recipient_user_id, created_at, id);
CREATE INDEX hitl_requests_requester ON hitl_requests (requester_agent_id, created_at, id);

CREATE TABLE schedules (
    id uuid PRIMARY KEY,
    creator_agent_id uuid NOT NULL REFERENCES agents(id),
    target_agent_id uuid NOT NULL REFERENCES agents(id),
    title text NOT NULL,
    content text NOT NULL,
    type text NOT NULL CHECK (type IN ('at', 'interval', 'calendar')),
    spec jsonb NOT NULL,
    paused boolean NOT NULL DEFAULT false,
    deleted_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX schedules_creator ON schedules (creator_agent_id, id);
CREATE INDEX schedules_target ON schedules (target_agent_id, id);

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
