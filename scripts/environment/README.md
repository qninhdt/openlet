# Openlet environment harness

Run from the repository root with a non-production Openlet config and its env
file. Use a Clerk development instance with a JWT template named `openlet`
(or set `OPENLET_SEED_CLERK_TEMPLATE`). The template needs an `aud` claim
matching `auth.clerk.audience` and a `public_metadata` claim populated from
`{{user.public_metadata}}`. Use a lifetime of at least 60 seconds. The harness
creates synthetic Clerk accounts with project-specific identities and reuses
them across seed calls. Clerk accounts persist when Compose volumes are removed.

```sh
environment() {
  uv run --env-file .env --locked --package openlet-tooling python -m scripts.environment "$@"
}
COMPOSE_PROFILES=leta environment up --project seed-workspace --build
environment prepare-cache --project seed-workspace --seeds /path/to/seeds
environment seed --project seed-workspace --seeds /path/to/seeds
environment token --project seed-workspace --user alex
environment down --project seed-workspace --volumes
```

`up` uses `.local/openlet.yaml` by default. Pass `--config` to choose
another config. Set `COMPOSE_PROFILES=leta` when first starting a project to
provision Leta agents and conversation storage. Each project gets separate
volumes, a local API port and a RustFS instance. Keep the same env file for
subsequent commands.

`seed` prints a JSON manifest with `api_url`, users, workspaces, agents,
conversations, storages, root node IDs and node IDs keyed by seed-relative
paths. Each call creates fresh workspaces. Repeat `--workspace` to select more
than one, or omit the flag to load all. Pass `--seeds` for an alternate seed
root. Consumers can delete a seeded workspace via Openlet's workspace DELETE
endpoint with its owner's token.

## Seed format

The system manifest maps user handles to `first_name` and `last_name`.
A workspace manifest has a `name` and `owner`, plus optional fields.

```json
{
  "name": "Operations",
  "owner": "alex",
  "members": ["sam"],
  "agents": {
    "triage": {"name": "Triage", "title": "Support", "operators": ["sam"]}
  },
  "conversations": {
    "triage-sam": {"agent": "triage", "user": "sam"}
  },
  "grants": [
    {"storage": "personal/alex", "actor": "triage", "role": "viewer"}
  ]
}
```

Agent properties follow the Leta creation API. Add `owner` to use a
workspace member as the agent owner. Put files and folders under
`storages/shared/`, `storages/personal/<handle>/`, or
`storages/conversation/<agent>-<user>/`. Empty storages can be omitted.

## Blob caches

For searchable blobs, run `prepare-cache` with the same project and seed root.
This executes the normal LetFS ingest workflow for files with a missing or
stale cache. The harness writes the resulting artifact files, metadata and
uncompressed `embeddings.npz` beside each source under `.letfs-cache/<filename>/`.
It uses a temporary workspace and removes its resources after capture.

`seed` uses PostgreSQL COPY for workspace and file records, batched SpiceDB
relationships and Qdrant points, and concurrent RustFS object writes. It
allocates fresh IDs and rebinds the cached metadata and vectors to those IDs.
Run `prepare-cache` again when the seed or model configuration changes. If
an unchanged prompt label or model alias is repointed, delete the affected
cache entry to regenerate it.

The direct loader targets the Compose project's loopback ports and follows
the schemas in this repository. Clerk account creation and metadata sync
use Clerk's backend API. Pass the returned `zed_token` in the
`x-openlet-zed-token` header for immediate reads with the new permissions.

Python callers using a signed RustFS URL can connect to `object_store_url`
while preserving the URL's original `Host` header. The same signed URL works
as-is inside the Compose network.
