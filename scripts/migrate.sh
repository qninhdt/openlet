#!/bin/sh
# Run inside PostgreSQL. Back up each database before schema changes.
set -eu
service=${1:?user, workspace or letfs required}
case "$service" in user|workspace|letfs) ;; *) exit 2 ;; esac
export PGUSER="openlet_$service" PGDATABASE="openlet_$service" PGHOST=127.0.0.1
export PGPASSWORD=$(cat "/run/secrets/${service}_db_password")
mkdir -p /backups
backup="/backups/${service}-$(date -u +%Y%m%dT%H%M%S)-$$.dump"
pg_dump -Fc -f "$backup"
pg_restore --list "$backup" >/dev/null
psql -v ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE IF NOT EXISTS schema_migrations(name text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now());
SQL
for file in /migrations/"$service"/migrations/*.sql; do
  [ -f "$file" ] || continue
  name=$(basename "$file")
  checksum=$(sha256sum "$file" | cut -d ' ' -f 1)
  existing=$(psql -At -v ON_ERROR_STOP=1 -v name="$name" <<'SQL'
SELECT sha256 FROM schema_migrations WHERE name=:'name';
SQL
)
  if [ -n "$existing" ]; then
    [ "$existing" = "$checksum" ] || { echo "changed applied migration: $name" >&2; exit 1; }
    continue
  fi
  { printf 'BEGIN;\n'; cat "$file"; printf '\nINSERT INTO schema_migrations(name,sha256) VALUES (:%s,:%s);\nCOMMIT;\n' "'name'" "'checksum'"; } | psql -v ON_ERROR_STOP=1 -v name="$name" -v checksum="$checksum"
done
