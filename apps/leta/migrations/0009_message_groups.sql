-- +goose Up
ALTER TABLE user_messages ADD COLUMN message_group_id uuid;

-- +goose Down
ALTER TABLE user_messages DROP COLUMN message_group_id;
