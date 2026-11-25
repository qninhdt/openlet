#!/usr/bin/env bash
set -Eeuo pipefail

# Online MVCC PostgreSQL backup by default (zero downtime).
# Usage: scripts/backup.sh [--stop-writers] [--upload-r2] [OUTPUT_DIR]

stop_writers=0
upload_r2=0
output=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --stop-writers) stop_writers=1 ;;
    --upload-r2) upload_r2=1 ;;
    -h|--help)
      echo "Usage: scripts/backup.sh [--stop-writers] [--upload-r2] [OUTPUT_DIR]"
      exit 0
      ;;
    -*)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
    *)
      output=$1
      ;;
  esac
  shift
done

: "${COMPOSE_FILE:?Set COMPOSE_FILE to the deployment Compose files}"
: "${COMPOSE_PROJECT_NAME:?Set the target Compose project explicitly}"

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
day=$(date -u +%Y-%m-%d)
output=${output:-"${OPENLET_BACKUPS:-/opt/openlet/backups}/$timestamp"}
if [[ -e $output ]]; then
  echo "Backup output must be a new directory: $output" >&2
  exit 1
fi

umask 077
mkdir -p "$output"

if (( stop_writers )); then
  mapfile -t writers < <(docker compose config --services | grep -E '^(envoy|platform|letfs|ingest-cpu|ingest-io|leta-api|leta-worker|temporal|spicedb)$' || true)
  if (( ${#writers[@]} > 0 )); then
    docker compose stop "${writers[@]}"
  fi
fi

inventory=$(docker compose exec -T postgres sh -ec 'psql -U "$POSTGRES_USER" -d postgres -At -F "$(printf "\t")" -c "SELECT datname,pg_get_userbyid(datdba) FROM pg_database WHERE NOT datistemplate AND datname <> '\''postgres'\'' ORDER BY datname"')
printf '%s\n' "$inventory" > "$output/databases.tsv"

while IFS=$'\t' read -r database _owner; do
  [[ -n $database ]] || continue
  docker compose exec -T postgres sh -ec 'pg_dump -U "$POSTGRES_USER" -d "$1" -Fc' sh "$database" < /dev/null > "$output/$database.dump"
done <<< "$inventory"

(
  cd "$output"
  { printf '%s\0' databases.tsv; find . -maxdepth 1 -name '*.dump' -print0; } | sort -z | xargs -0 sha256sum > SHA256SUMS
)

if (( upload_r2 )); then
  : "${OPENLET_CONFIG:?OPENLET_CONFIG is required for --upload-r2}"
  dotenv=${OPENLET_DOTENV:-/opt/openlet/.env}
  root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
  "${UV:-uv}" run --project "$root" --env-file "$dotenv" --locked --no-dev --package openlet-tooling python - "$output" "$day" "$timestamp" <<'PY'
import datetime as dt
import os
import sys
from pathlib import Path

import boto3
from openlet_sdk.config import load, secret

backup_dir = Path(sys.argv[1])
day = sys.argv[2]
stamp = sys.argv[3]
cfg = load()["dependencies"]["s3"]
s3 = boto3.client(
    "s3",
    endpoint_url=cfg["endpoint"],
    region_name=cfg["region"],
    aws_access_key_id=secret(cfg["access_key_id"]),
    aws_secret_access_key=secret(cfg["secret_access_key"]),
)
bucket = cfg["bucket"]
prefix = f"backups/postgres/{day}/{stamp}"
for path in sorted(backup_dir.iterdir()):
    if path.is_file():
        s3.upload_file(str(path), bucket, f"{prefix}/{path.name}")

cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=14)
paginator = s3.get_paginator("list_objects_v2")
stale: list[dict[str, str]] = []
for page in paginator.paginate(Bucket=bucket, Prefix="backups/postgres/"):
    for item in page.get("Contents", []):
        modified = item.get("LastModified")
        if modified is not None and modified < cutoff:
            stale.append({"Key": item["Key"]})
for start in range(0, len(stale), 1000):
    s3.delete_objects(Bucket=bucket, Delete={"Objects": stale[start : start + 1000]})
print(f"Uploaded backup to s3://{bucket}/{prefix} (pruned {len(stale)} expired objects)")
PY
fi

echo "PostgreSQL backup written to $output"
