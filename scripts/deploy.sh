#!/usr/bin/env bash
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"
OPENLET_CONFIG=$(realpath "${1:?Usage: scripts/deploy.sh CONFIG_YAML DOTENV IMAGE_LOCK}")
export OPENLET_CONFIG
dotenv=$(realpath "${2:?Dotenv path required}")
image_lock=$(realpath "${3:?Immutable image-lock Compose file required}")
registry_user=${4:-}
export COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-openlet}
export OPENLET_GENERATED="$root/.local/generated"
export OPENLET_BACKUPS=${OPENLET_BACKUPS:-"$root/.local/backups"}
umask 077
mkdir -p "$OPENLET_BACKUPS"
chmod 700 "$OPENLET_BACKUPS"
"${UV:-uv}" run --env-file "$dotenv" --locked --no-dev --package openlet-tooling python scripts/configure.py --output "$OPENLET_GENERATED"
export COMPOSE_FILE="$root/infra/compose.yaml:$OPENLET_GENERATED/compose.runtime.yaml:$image_lock"
if [[ -n $registry_user ]]; then
  export COMPOSE_FILE="$COMPOSE_FILE:$root/infra/compose.demo.yaml"
  export DOCKER_CONFIG
  DOCKER_CONFIG=$(mktemp -d)
  trap 'rm -rf -- "$DOCKER_CONFIG"' EXIT
  docker login ghcr.io --username "$registry_user" --password-stdin
fi
docker compose config --quiet
docker compose pull --ignore-buildable
if [[ -n $registry_user ]]; then
  docker compose pull platform platform-migrate letfs letfs-migrate ingest-cpu ingest-io leta-api leta-worker leta-migrate
fi
postgres=$(docker compose ps -aq postgres)
docker compose up --detach --wait postgres
if [[ -n $postgres ]]; then
  scripts/backup.sh "$OPENLET_BACKUPS/pre-deploy-$(date -u +%Y%m%dT%H%M%SZ)"
fi
docker compose up --detach --no-build --wait --wait-timeout 240
echo 'Deployment is running. Retain the previous image lock and backup for rollback.'
