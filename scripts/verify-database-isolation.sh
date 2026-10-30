#!/usr/bin/env bash
set -euo pipefail
project=${1:?Compose test project required}
[[ "$project" == openlet-test ]] || { echo 'only isolated test project allowed' >&2; exit 2; }
docker compose -p "$project" -f deploy/compose.yaml exec -T postgres sh -s <<'SH'
set -eu
for actor in user workspace letfs temporal temporal_visibility; do
  export PGUSER="openlet_$actor" PGHOST=127.0.0.1
  export PGPASSWORD=$(cat "/run/secrets/${actor}_db_password")
  for target in user workspace letfs temporal temporal_visibility; do
    if [ "$actor" = "$target" ]; then
      psql -d "openlet_$target" -v ON_ERROR_STOP=1 -c 'SELECT 1' >/dev/null
    elif psql -d "openlet_$target" -v ON_ERROR_STOP=1 -c 'SELECT 1' >/dev/null 2>&1; then
      echo "database isolation failed: $actor -> $target" >&2
      exit 1
    fi
  done
done
echo 'All 20 cross-database connections denied.'
SH
