#!/bin/sh
set -eu
mkdir -p /backups
for scope in temporal temporal_visibility; do
  export PGHOST=postgres PGUSER="openlet_$scope" PGDATABASE="openlet_$scope"
  export PGPASSWORD=$(cat "/run/secrets/${scope}_db_password")
  path="/backups/$scope-before-schema-$(date -u +%Y%m%dT%H%M%S)-$$.dump"
  pg_dump -Fc -f "$path"
  pg_restore --list "$path" >/dev/null
done
