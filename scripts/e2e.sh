#!/usr/bin/env bash
# shellcheck disable=SC1091
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"
project=${COMPOSE_PROJECT_NAME:-openlet-$(basename "$root")-e2e}
suite=${1:-api}
case "$suite" in api|browser) ;; *) echo 'Usage: scripts/e2e.sh [api|browser]' >&2; exit 2 ;; esac
if [[ -n $(docker ps -aq --filter "label=com.docker.compose.project=$project") ]]; then
  echo "Compose project $project already exists; inspect and stop that run before starting another." >&2
  exit 1
fi
export COMPOSE_PROFILES=leta
export OPENLET_CONFIG="$root/e2e/openlet.test.yaml"
export OPENLET_GENERATED="$root/.local/e2e/generated"
export OPENLET_BACKUPS="$root/.local/e2e/backups"
export OPENLET_ARTIFACTS="$root/.local/e2e/results"
mkdir -p "$OPENLET_GENERATED" "$OPENLET_BACKUPS" "$OPENLET_ARTIFACTS"
chmod 700 "$OPENLET_GENERATED" "$OPENLET_BACKUPS"
uv run --no-env-file --locked python - <<'PY'
from pathlib import Path
import os
import secrets
os.umask(0o077)
keys = ('POSTGRES_ADMIN_PASSWORD', 'PLATFORM_DB_PASSWORD', 'LETFS_DB_PASSWORD', 'TEMPORAL_DB_PASSWORD', 'SPICEDB_DB_PASSWORD', 'SPICEDB_KEY', 'S3_ACCESS_KEY_ID', 'S3_SECRET_ACCESS_KEY', 'QDRANT_API_KEY', 'OPENAI_API_KEY', 'LITELLM_MASTER_KEY', 'CLERK_SECRET_KEY', 'LANGFUSE_PUBLIC_KEY', 'LANGFUSE_SECRET_KEY', 'LETA_DB_PASSWORD', 'REDIS_PASSWORD')
Path('.local/e2e/test.env').write_text(''.join(f'{key}={secrets.token_hex(16)}\n' for key in keys))
PY
set -a
source .local/e2e/test.env
export OPENAI_BASE_URL=http://wiremock:8080/v1
set +a
uv run --no-env-file --locked python scripts/configure.py --test --output "$OPENLET_GENERATED"
compose=(docker compose --project-name "$project" -f infra/compose.yaml -f "$OPENLET_GENERATED/compose.runtime.yaml" -f infra/compose.test.yaml -f "$OPENLET_GENERATED/compose.test.runtime.yaml")
if [[ -n ${OPENLET_IMAGE_LOCK:-} ]]; then compose+=(-f "$OPENLET_IMAGE_LOCK"); fi
cleanup() {
  status=$?
  trap - EXIT
  if ! "${compose[@]}" ps --all > "$OPENLET_ARTIFACTS/compose-ps.txt"; then echo 'Could not collect Compose status.' >&2; fi
  if ! "${compose[@]}" logs --no-color > "$OPENLET_ARTIFACTS/compose.log" 2>&1; then echo 'Could not collect Compose logs.' >&2; fi
  if ! "${compose[@]}" down --volumes --remove-orphans --timeout 30 > "$OPENLET_ARTIFACTS/cleanup.log" 2>&1; then
    echo "Cleanup failed; inspect project $project." >&2
    if [[ $status == 0 ]]; then status=1; fi
  fi
  rm -f .local/e2e/test.env
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
"${compose[@]}" config --quiet
if [[ -z ${OPENLET_IMAGE_LOCK:-} ]]; then
  if ! "${compose[@]}" build platform letfs ingest-cpu ingest-io leta-api > "$OPENLET_ARTIFACTS/build.log" 2>&1; then
    tail -n 50 "$OPENLET_ARTIFACTS/build.log" >&2
    exit 1
  fi
fi
if [[ $suite == browser ]]; then
  docker build --file e2e/Dockerfile --target browser --tag openlet/e2e:local .
else
  "${compose[@]}" build e2e
fi
"${compose[@]}" up --detach --wait --wait-timeout 180
"${compose[@]}" run --rm --no-deps e2e test --project="$suite"
