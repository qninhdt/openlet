-- +goose Up
CREATE TABLE conversations (
    id                   UUID PRIMARY KEY,
    workspace_id         UUID NOT NULL,
    type                 TEXT NOT NULL CHECK (type IN ('dm', 'group')),
    dm_key               TEXT,
    handle               TEXT,
    title                TEXT NOT NULL DEFAULT '',
    storage_id           UUID,
    storage_ready        BOOLEAN NOT NULL DEFAULT false,
    last_seq             BIGINT NOT NULL DEFAULT 0 CHECK (last_seq >= 0),
    last_msg_at          TIMESTAMPTZ,
    last_message_preview JSONB,
    created_by           UUID NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((type = 'dm') = (dm_key IS NOT NULL)),
    CHECK ((type = 'group') = (handle IS NOT NULL))
);
CREATE UNIQUE INDEX conversations_dm_uidx
    ON conversations (workspace_id, dm_key) WHERE type = 'dm';
CREATE UNIQUE INDEX conversations_group_handle_uidx
    ON conversations (workspace_id, handle) WHERE type = 'group';
CREATE INDEX conversations_recent_idx
    ON conversations (workspace_id, last_msg_at DESC NULLS LAST, created_at DESC);

CREATE TABLE conversation_members (
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    workspace_id    UUID NOT NULL,
    actor_type      TEXT NOT NULL CHECK (actor_type IN ('user', 'agent')),
    actor_id        UUID NOT NULL,
    role            TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('admin', 'member')),
    last_read_seq   BIGINT NOT NULL DEFAULT 0 CHECK (last_read_seq >= 0),
    muted           BOOLEAN NOT NULL DEFAULT false,
    joined_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (conversation_id, actor_type, actor_id)
);
CREATE INDEX conv_members_workspace_actor_idx
    ON conversation_members (workspace_id, actor_type, actor_id, conversation_id);

CREATE TABLE messages (
    id              UUID PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    seq             BIGINT NOT NULL CHECK (seq > 0),
    idempotency_key UUID,
    sender_type     TEXT NOT NULL CHECK (sender_type IN ('user', 'agent', 'system')),
    sender_id       UUID NOT NULL,
    content         TEXT NOT NULL DEFAULT '',
    reply_to_id     UUID REFERENCES messages(id) ON DELETE SET NULL,
    attachments     JSONB NOT NULL DEFAULT '[]',
    mentions        JSONB NOT NULL DEFAULT '[]',
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    edited_at       TIMESTAMPTZ,
    deleted_at      TIMESTAMPTZ,
    UNIQUE (conversation_id, seq),
    UNIQUE (conversation_id, sender_type, sender_id, idempotency_key)
);
CREATE INDEX messages_conv_seq_idx ON messages (conversation_id, seq DESC);

CREATE TABLE message_reactions (
    message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    actor_type TEXT NOT NULL CHECK (actor_type IN ('user', 'agent')),
    actor_id   UUID NOT NULL,
    emoji      TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (message_id, actor_type, actor_id, emoji)
);
CREATE INDEX reactions_msg_idx ON message_reactions (message_id);

CREATE TABLE outbox_events (
    id              BIGSERIAL PRIMARY KEY,
    destination     TEXT NOT NULL CHECK (destination IN ('centrifugo', 'leta')),
    conversation_id UUID NOT NULL,
    message_id      UUID,
    target_id       TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    payload         JSONB NOT NULL,
    attempts        INT NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX outbox_pending_idx
    ON outbox_events (next_attempt_at, id) WHERE delivered_at IS NULL;
CREATE INDEX outbox_cleanup_idx
    ON outbox_events (delivered_at) WHERE delivered_at IS NOT NULL;

CREATE TABLE sidebar_layouts (
    workspace_id UUID NOT NULL,
    user_id      UUID NOT NULL,
    revision     INT NOT NULL DEFAULT 0 CHECK (revision >= 0),
    layout       JSONB NOT NULL DEFAULT '{"folders":[],"assignments":{},"pins":[],"order":[],"collapsed":[]}',
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, user_id)
);

-- +goose Down
DROP TABLE IF EXISTS sidebar_layouts;
DROP TABLE IF EXISTS outbox_events;
DROP TABLE IF EXISTS message_reactions;
DROP TABLE IF EXISTS messages;
DROP TABLE IF EXISTS conversation_members;
DROP TABLE IF EXISTS conversations;
