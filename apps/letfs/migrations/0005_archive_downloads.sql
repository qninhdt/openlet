-- +goose Up
CREATE TABLE archive_downloads (
 ticket_hash bytea PRIMARY KEY,
 actor text NOT NULL,
 request bytea NOT NULL,
 expires_at timestamptz NOT NULL
);
CREATE INDEX archive_downloads_expiry ON archive_downloads(expires_at);
-- +goose Down
DROP TABLE archive_downloads;
