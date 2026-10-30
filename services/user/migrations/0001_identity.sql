CREATE TABLE users (
    id uuid PRIMARY KEY,
    clerk_id text UNIQUE NOT NULL CHECK (length(clerk_id) BETWEEN 1 AND 200),
    display_name text NOT NULL DEFAULT '' CHECK (length(display_name) <= 100),
    avatar_url text NOT NULL DEFAULT '' CHECK (length(avatar_url) <= 2048),
    onboarding_state text NOT NULL DEFAULT 'provisioning' CHECK (onboarding_state IN ('provisioning','active')),
    initial_workspace_id uuid NOT NULL UNIQUE,
    initial_workspace_key uuid NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE operations (
    id uuid PRIMARY KEY,
    subject text UNIQUE NOT NULL REFERENCES users(clerk_id),
    state text NOT NULL DEFAULT 'running' CHECK (state IN ('running','succeeded','failed')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
