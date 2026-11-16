-- +goose Up
ALTER TABLE user_messages ADD COLUMN read_at timestamptz;
CREATE INDEX user_messages_unread ON user_messages (leta_id, recipient_user_id) WHERE read_at IS NULL;
CREATE INDEX agent_messages_sender_chat ON agent_messages (recipient_agent_id, source_id, created_at DESC, id DESC)
    WHERE source_kind='user' AND input_type='message';

-- +goose Down
DROP INDEX agent_messages_sender_chat, user_messages_unread;
ALTER TABLE user_messages DROP COLUMN read_at;
