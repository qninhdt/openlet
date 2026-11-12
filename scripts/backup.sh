#!/usr/bin/env bash
set -Eeuo pipefail
: "${COMPOSE_FILE:?Set COMPOSE_FILE to the deployment Compose files}"
: "${COMPOSE_PROJECT_NAME:?Set the target Compose project explicitly}"
output=${1:?Usage: scripts/backup.sh OUTPUT_DIRECTORY}
if [[ -e $output ]]; then echo 'Backup output must be a new directory.' >&2; exit 1; fi
umask 077
mkdir -p "$output"
docker compose stop envoy platform letfs ingest-cpu ingest-io temporal spicedb
inventory=$(docker compose exec -T postgres sh -ec 'psql -U "$POSTGRES_USER" -d postgres -At -F "$(printf "\t")" -c "SELECT datname,pg_get_userbyid(datdba) FROM pg_database WHERE NOT datistemplate AND datname <> '\''postgres'\'' ORDER BY datname"')
printf '%s\n' "$inventory" > "$output/databases.tsv"
while IFS=$'\t' read -r database _owner; do
  [[ -n $database ]] || continue
  docker compose exec -T postgres sh -ec 'pg_dump -U "$POSTGRES_USER" -d "$1" -Fc' sh "$database" < /dev/null > "$output/$database.dump"
done <<< "$inventory"
(cd "$output" && { printf '%s\0' databases.tsv; find . -maxdepth 1 -name '*.dump' -print0; } | sort -z | xargs -0 sha256sum > SHA256SUMS)
echo "PostgreSQL backup written to $output. Writers remain stopped; S3 retention/backup is managed by its provider."
