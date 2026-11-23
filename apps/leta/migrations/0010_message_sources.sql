-- +goose Up
ALTER TABLE agent_messages ADD COLUMN sources jsonb NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE user_messages ADD COLUMN sources jsonb NOT NULL DEFAULT '[]'::jsonb;

-- +goose Down
ALTER TABLE user_messages DROP COLUMN sources;
ALTER TABLE agent_messages DROP COLUMN sources;
