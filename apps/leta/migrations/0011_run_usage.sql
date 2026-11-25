-- +goose Up
ALTER TABLE runs
    ADD COLUMN input_tokens bigint NOT NULL DEFAULT 0,
    ADD COLUMN cached_input_tokens bigint NOT NULL DEFAULT 0,
    ADD COLUMN output_tokens bigint NOT NULL DEFAULT 0,
    ADD COLUMN reasoning_tokens bigint NOT NULL DEFAULT 0,
    ADD COLUMN cost_usd double precision NOT NULL DEFAULT 0,
    ADD COLUMN llm_calls integer NOT NULL DEFAULT 0;

-- +goose Down
ALTER TABLE runs
    DROP COLUMN llm_calls,
    DROP COLUMN cost_usd,
    DROP COLUMN reasoning_tokens,
    DROP COLUMN output_tokens,
    DROP COLUMN cached_input_tokens,
    DROP COLUMN input_tokens;
