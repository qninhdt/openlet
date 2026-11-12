#!/usr/bin/env bash
set -Eeuo pipefail
: "${COMPOSE_FILE:?Set COMPOSE_FILE to the target Compose files}"
: "${COMPOSE_PROJECT_NAME:?Set the empty target Compose project explicitly}"
source_dir=${1:?Usage: scripts/restore.sh BACKUP_DIRECTORY}
(cd "$source_dir" && sha256sum --check SHA256SUMS)
docker compose stop envoy platform letfs ingest-cpu ingest-io temporal spicedb
while IFS=$'\t' read -r database owner; do
  [[ -n $database ]] || continue
  tables=$(docker compose exec -T postgres sh -ec 'psql -U "$POSTGRES_USER" -d "$1" -At -c "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('\''pg_catalog'\'','\''information_schema'\'')"' sh "$database" < /dev/null)
  if [[ $tables != 0 ]]; then echo "Target database $database is not empty; restore refused." >&2; exit 1; fi
done < "$source_dir/databases.tsv"
"$(dirname "$0")/backup.sh" "${OPENLET_BACKUPS:?required}/pre-restore-$(date -u +%Y%m%dT%H%M%SZ)"
while IFS=$'\t' read -r database owner; do
  [[ -n $database ]] || continue
  docker compose exec -T postgres sh -ec 'pg_restore -U "$POSTGRES_USER" -d "$1" --role="$2" --no-owner --exit-on-error' sh "$database" "$owner" < "$source_dir/$database.dump"
done < "$source_dir/databases.tsv"
docker compose run --rm --no-deps spicedb-migrate datastore repair transaction-ids --datastore-engine postgres
echo 'PostgreSQL restore finished. Keep writers stopped until matching S3 data and the image set have been verified.'
