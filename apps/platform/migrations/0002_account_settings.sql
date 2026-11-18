-- +goose Up
ALTER TABLE users ADD COLUMN appearance jsonb;
ALTER TABLE users ADD COLUMN preferences jsonb;

-- +goose Down
ALTER TABLE users DROP COLUMN preferences;
ALTER TABLE users DROP COLUMN appearance;
