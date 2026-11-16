-- +goose Up
CREATE TABLE conversations (
    id uuid PRIMARY KEY,
    leta_id uuid NOT NULL REFERENCES letas(id) ON DELETE CASCADE,
    user_id uuid NOT NULL,
    storage_id uuid NOT NULL UNIQUE,
    ready boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(leta_id,user_id)
);
ALTER TABLE agent_messages ADD COLUMN file_refs jsonb NOT NULL DEFAULT '[]';
ALTER TABLE user_messages ADD COLUMN file_refs jsonb NOT NULL DEFAULT '[]';

-- +goose Down
ALTER TABLE user_messages DROP COLUMN file_refs;
ALTER TABLE agent_messages DROP COLUMN file_refs;
DROP TABLE conversations;
