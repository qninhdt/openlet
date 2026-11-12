#!/usr/bin/env bash
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"
OPENLET_CONFIG=$(realpath "${1:?Usage: scripts/deploy.sh CONFIG_YAML DOTENV IMAGE_LOCK}")
export OPENLET_CONFIG
dotenv=$(realpath "${2:?Dotenv path required}")
image_lock=$(realpath "${3:?Immutable image-lock Compose file required}")
export COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-openlet}
export OPENLET_GENERATED="$root/.local/generated"
export OPENLET_BACKUPS=${OPENLET_BACKUPS:-"$root/.local/backups"}
mkdir -p "$OPENLET_BACKUPS"
chmod 700 "$OPENLET_BACKUPS"
uv run --env-file "$dotenv" --locked python scripts/configure.py --output "$OPENLET_GENERATED"
export COMPOSE_FILE="$root/infra/compose.yaml:$OPENLET_GENERATED/compose.runtime.yaml:$image_lock"
docker compose config --quiet
docker compose pull
docker compose stop envoy platform letfs ingest-cpu ingest-io temporal spicedb
docker compose up --detach --wait postgres
scripts/backup.sh "$OPENLET_BACKUPS/pre-deploy-$(date -u +%Y%m%dT%H%M%SZ)"
docker compose up --detach --wait --wait-timeout 180
echo 'Deployment is running. Retain the previous image lock and backup for rollback.'
