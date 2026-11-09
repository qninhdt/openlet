-- +goose Up
CREATE TABLE idempotency_keys (
    actor_id uuid NOT NULL,
    request_key uuid NOT NULL,
    request_hash text NOT NULL,
    resource_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    expires_at timestamptz,
    PRIMARY KEY (actor_id, request_key)
);
CREATE INDEX idempotency_keys_expiry ON idempotency_keys(expires_at);

-- +goose Down
DROP TABLE idempotency_keys;
