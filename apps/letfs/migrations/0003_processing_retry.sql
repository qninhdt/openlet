-- +goose Up
ALTER TABLE processing ADD COLUMN attempt bigint NOT NULL DEFAULT 0 CHECK (attempt >= 0);
-- +goose Down
ALTER TABLE processing DROP COLUMN attempt;
