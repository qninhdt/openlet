-- +goose Up
CREATE TABLE users (
    id UUID PRIMARY KEY,
    clerk_id TEXT NOT NULL UNIQUE CHECK (length(clerk_id) BETWEEN 1 AND 200),
    display_name TEXT NOT NULL DEFAULT '' CHECK (length(display_name) <= 100),
    avatar_url TEXT NOT NULL DEFAULT '' CHECK (length(avatar_url) <= 2048),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
