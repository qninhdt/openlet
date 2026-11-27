-- +goose Up
CREATE TABLE letas (
    id           UUID PRIMARY KEY,
    workspace_id UUID NOT NULL,
    storage_id   UUID NOT NULL,
    state        TEXT NOT NULL CHECK (state IN ('provisioning', 'active', 'deleting', 'archived')),
    paused       BOOLEAN NOT NULL DEFAULT false,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX letas_workspace_idx ON letas (workspace_id, id);

CREATE TABLE agents (
    id                  UUID PRIMARY KEY,
    leta_id             UUID NOT NULL REFERENCES letas(id),
    parent_agent_id     UUID REFERENCES agents(id),
    depth               INT NOT NULL DEFAULT 0 CHECK (depth >= 0),
    name                TEXT NOT NULL,
    title               TEXT NOT NULL DEFAULT '',
    description         TEXT NOT NULL DEFAULT '',
    appearance          JSONB NOT NULL DEFAULT '{}',
    handle              TEXT NOT NULL,
    custom_instructions TEXT NOT NULL DEFAULT '',
    model_id            TEXT,
    reasoning_effort    TEXT,
    inbox_seq           BIGINT NOT NULL DEFAULT 0 CHECK (inbox_seq >= 0),
    activity_seq        BIGINT NOT NULL DEFAULT 0 CHECK (activity_seq >= 0),
    lease_token         UUID,
    lease_expires_at    TIMESTAMPTZ,
    state               TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'stopped')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((parent_agent_id IS NULL) = (id = leta_id))
);
CREATE UNIQUE INDEX agents_active_handle_uidx
    ON agents (leta_id, handle) WHERE state = 'active';
CREATE INDEX agents_parent_idx ON agents (parent_agent_id) WHERE state = 'active';
CREATE INDEX agents_leta_idx ON agents (leta_id, state);

CREATE TABLE inbox_items (
    agent_id        UUID NOT NULL REFERENCES agents(id),
    seq             BIGINT NOT NULL CHECK (seq > 0),
    idempotency_key TEXT NOT NULL,
    kind            TEXT NOT NULL CHECK (kind IN ('channel', 'reaction', 'agent', 'hitl', 'schedule', 'notification')),
    channel         TEXT,
    reply_address   TEXT,
    sender          JSONB NOT NULL,
    content         TEXT NOT NULL,
    attachments     JSONB NOT NULL DEFAULT '[]',
    metadata        JSONB NOT NULL DEFAULT '{}',
    silent          BOOLEAN NOT NULL DEFAULT false,
    delivery_state  TEXT NOT NULL DEFAULT 'pending'
                    CHECK (delivery_state IN ('pending', 'previewed', 'delivered')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_id, seq),
    UNIQUE (agent_id, idempotency_key)
);
CREATE INDEX inbox_items_pending_idx
    ON inbox_items (agent_id, seq) WHERE delivery_state IN ('pending', 'previewed');
CREATE INDEX inbox_items_wake_seq_idx
    ON inbox_items (agent_id, seq DESC) WHERE NOT silent AND delivery_state IN ('pending', 'previewed');

CREATE TABLE runs (
    id                  UUID PRIMARY KEY,
    agent_id            UUID NOT NULL REFERENCES agents(id),
    status              TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'cancelled')),
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at         TIMESTAMPTZ,
    heartbeat_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    error_code          TEXT,
    input_tokens        BIGINT NOT NULL DEFAULT 0,
    cached_input_tokens BIGINT NOT NULL DEFAULT 0,
    output_tokens       BIGINT NOT NULL DEFAULT 0,
    reasoning_tokens    BIGINT NOT NULL DEFAULT 0,
    cost_usd            DOUBLE PRECISION NOT NULL DEFAULT 0,
    llm_calls           INT NOT NULL DEFAULT 0,
    CHECK ((status IN ('completed', 'failed', 'cancelled')) = (finished_at IS NOT NULL))
);
CREATE UNIQUE INDEX runs_single_running_uidx ON runs (agent_id) WHERE status = 'running';
CREATE INDEX runs_timeline_idx ON runs (agent_id, started_at DESC);

CREATE TABLE activity_events (
    agent_id   UUID NOT NULL REFERENCES agents(id),
    seq        BIGINT NOT NULL CHECK (seq > 0),
    run_id     UUID REFERENCES runs(id),
    type       TEXT NOT NULL CHECK (type IN (
        'run.started', 'run.finished',
        'activity.inbox_received', 'activity.message', 'activity.tool_call',
        'activity.tool_result', 'activity.compacted', 'activity.agent_message',
        'subagent.spawned', 'subagent.stopped',
        'hitl.updated', 'schedule.updated'
    )),
    data       JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_id, seq)
);
CREATE INDEX activity_events_run_idx ON activity_events (agent_id, run_id, seq);

CREATE TABLE hitl_requests (
    id                 UUID PRIMARY KEY,
    leta_id            UUID NOT NULL REFERENCES letas(id),
    requester_agent_id UUID NOT NULL REFERENCES agents(id),
    recipient_user_id  UUID NOT NULL,
    type               TEXT NOT NULL CHECK (type IN ('ask', 'approval')),
    title              TEXT NOT NULL,
    payload            JSONB NOT NULL,
    status             TEXT NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending', 'answered', 'accepted', 'denied', 'cancelled', 'expired')),
    response           JSONB,
    outcome            JSONB,
    expires_at         TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at        TIMESTAMPTZ,
    CHECK ((status = 'pending') = (resolved_at IS NULL)),
    CHECK (outcome IS NULL OR (type = 'approval' AND status = 'accepted'))
);
CREATE INDEX hitl_requests_recipient_idx ON hitl_requests (recipient_user_id, created_at DESC);
CREATE INDEX hitl_requests_leta_pending_idx ON hitl_requests (leta_id) WHERE status = 'pending';

CREATE TABLE schedules (
    id               UUID PRIMARY KEY,
    leta_id          UUID NOT NULL REFERENCES letas(id),
    creator_agent_id UUID NOT NULL REFERENCES agents(id),
    target_agent_id  UUID NOT NULL REFERENCES agents(id),
    title            TEXT NOT NULL,
    content          TEXT NOT NULL,
    type             TEXT NOT NULL CHECK (type IN ('at', 'interval', 'calendar', 'cron')),
    spec             JSONB NOT NULL,
    paused           BOOLEAN NOT NULL DEFAULT false,
    deleted_at       TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX schedules_leta_active_idx ON schedules (leta_id) WHERE deleted_at IS NULL;

CREATE TABLE idempotency_receipts (
    scope        TEXT NOT NULL,
    action       TEXT NOT NULL,
    request_id   UUID NOT NULL,
    request_hash TEXT NOT NULL,
    response     JSONB NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (scope, action, request_id)
);
CREATE INDEX idempotency_receipts_created_idx ON idempotency_receipts (created_at);

-- +goose Down
DROP TABLE IF EXISTS idempotency_receipts;
DROP TABLE IF EXISTS schedules;
DROP TABLE IF EXISTS hitl_requests;
DROP TABLE IF EXISTS activity_events;
DROP TABLE IF EXISTS runs;
DROP TABLE IF EXISTS inbox_items;
DROP TABLE IF EXISTS agents;
DROP TABLE IF EXISTS letas;
