-- +goose Up
ALTER TABLE agent_messages ADD COLUMN silent boolean NOT NULL DEFAULT false;
ALTER TABLE agent_messages ADD COLUMN input_type text NOT NULL DEFAULT 'message'
    CHECK (input_type IN ('message', 'reaction'));
ALTER TABLE agent_messages ADD COLUMN input_payload jsonb;
CREATE INDEX agent_messages_wake ON agent_messages (recipient_agent_id, seq) WHERE NOT silent;
CREATE INDEX agent_messages_silent ON agent_messages (recipient_agent_id, seq) WHERE silent;

CREATE TABLE message_reactions (
    leta_id uuid NOT NULL REFERENCES letas(id),
    message_kind text NOT NULL CHECK (message_kind IN ('incoming', 'outgoing')),
    message_id uuid NOT NULL,
    actor_kind text NOT NULL CHECK (actor_kind IN ('user', 'agent')),
    actor_id uuid NOT NULL,
    emoji text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (leta_id, message_kind, message_id, actor_kind, actor_id)
);
CREATE TABLE agent_sidebar_layouts (
    workspace_id uuid NOT NULL,
    user_id uuid NOT NULL,
    revision bigint NOT NULL DEFAULT 0,
    layout jsonb NOT NULL DEFAULT '{"folders":[],"assignments":{},"pins":[],"order":[],"collapsed":[]}',
    PRIMARY KEY (workspace_id, user_id)
);

-- +goose Down
DROP TABLE agent_sidebar_layouts, message_reactions;
DROP INDEX agent_messages_silent, agent_messages_wake;
ALTER TABLE agent_messages DROP COLUMN input_payload, DROP COLUMN input_type, DROP COLUMN silent;
