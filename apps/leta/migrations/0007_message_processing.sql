-- +goose Up
ALTER TABLE agent_messages ADD COLUMN processing_run_id uuid REFERENCES runs(id) ON DELETE SET NULL;
CREATE INDEX agent_messages_processing ON agent_messages(processing_run_id) WHERE processing_run_id IS NOT NULL;

-- +goose Down
DROP INDEX agent_messages_processing;
ALTER TABLE agent_messages DROP COLUMN processing_run_id;
