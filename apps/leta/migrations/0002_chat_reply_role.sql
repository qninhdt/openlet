-- +goose Up
ALTER TABLE agent_messages ADD COLUMN in_reply_to_role text
    CHECK (in_reply_to_role IN ('user', 'assistant'));
ALTER TABLE agent_messages ADD COLUMN schedule_title text;
CREATE INDEX user_messages_recipient_chat
    ON user_messages (leta_id, recipient_user_id, created_at, id);

-- +goose Down
DROP INDEX user_messages_recipient_chat;
ALTER TABLE agent_messages DROP COLUMN schedule_title;
ALTER TABLE agent_messages DROP COLUMN in_reply_to_role;
