-- +goose Up
CREATE TABLE accounts (
    id UUID PRIMARY KEY,
    type TEXT NOT NULL CHECK (type IN ('user', 'agent')),
    clerk_id TEXT UNIQUE CHECK (length(clerk_id) BETWEEN 1 AND 200),
    owner_id UUID REFERENCES accounts(id),
    display_name TEXT NOT NULL DEFAULT '' CHECK (length(display_name) <= 100),
    avatar_url TEXT NOT NULL DEFAULT '' CHECK (length(avatar_url) <= 2048),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((type = 'user' AND clerk_id IS NOT NULL AND owner_id IS NULL)
        OR (type = 'agent' AND clerk_id IS NULL AND owner_id IS NOT NULL)),
    CHECK (owner_id <> id)
);
CREATE INDEX accounts_by_owner ON accounts(owner_id) WHERE owner_id IS NOT NULL;
