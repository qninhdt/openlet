#!/usr/bin/env bash
# Coordinated backup for the test-only SeaweedFS deployment.
set -euo pipefail
cd "$(dirname "$0")/.."
[[ $# == 1 && $1 =~ ^openlet-test(-backup-[0-9]+-[0-9]+)?$ ]] || { echo 'Usage: scripts/backup-local.sh openlet-test[-backup-TIMESTAMP-PID] (external S3 requires its provider procedure)' >&2; exit 2; }
source_project=$1
export OPENLET_STATE_DIR=../.local/test
export OPENLET_TEST_UID="$(id -u)" OPENLET_TEST_GID="$(id -g)"
dc=(docker compose -p "$source_project" -f deploy/compose.yaml -f deploy/compose.test.yaml)
[[ -n $("${dc[@]}" ps -q postgres) && -n $("${dc[@]}" ps -q storage) ]] || { echo 'Source PostgreSQL and SeaweedFS must be running' >&2; exit 2; }
stamp=$(date -u +%Y%m%dT%H%M%S)-$$
backup="$PWD/.local/snapshots/$stamp"
umask 077
mkdir -m 700 -p "$backup/databases" "$backup/config"
"${dc[@]}" stop envoy issuer
"${dc[@]}" run --rm --no-deps --entrypoint temporal temporal-init --address temporal:7233 schedule toggle --pause --namespace openlet --schedule-id openlet-storage-maintenance --reason coordinated-backup
"${dc[@]}" stop processor
"${dc[@]}" stop user workspace letfs
"${dc[@]}" stop temporal
"${dc[@]}" exec -T postgres psql -U openlet_admin -d openlet_letfs -v ON_ERROR_STOP=1 <<'SQL'
DO $$ BEGIN
  IF EXISTS(SELECT 1 FROM uploads WHERE state IN ('created','transferring','uploaded') OR (state!='finalized' AND multipart_id IS NOT NULL))
     OR EXISTS(SELECT 1 FROM operations WHERE state IN ('running','discarding'))
     OR EXISTS(SELECT 1 FROM export_attempts WHERE multipart_id IS NOT NULL) THEN
    RAISE EXCEPTION 'Unfinished storage work: resume, finalize/abort and drain maintenance before backup';
  END IF;
END $$;
SQL
"${dc[@]}" stop storage
if "${dc[@]}" ps --status running --services | rg -q '^(user|workspace|letfs|processor|temporal|storage|envoy|issuer)$'; then echo 'Writers still running; backup refused' >&2; exit 1; fi
"${dc[@]}" ps -a --format json > "$backup/config/container-images.jsonl"
for scope in user workspace letfs temporal temporal_visibility; do
  "${dc[@]}" exec -T postgres pg_dump -U openlet_admin -d "openlet_$scope" --exclude-extension=pg_stat_statements -Fc > "$backup/databases/$scope.dump"
  "${dc[@]}" exec -T postgres pg_restore --list < "$backup/databases/$scope.dump" > /dev/null
done
storage_volume=$(docker inspect "$("${dc[@]}" ps -aq storage)" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}')
[[ "$storage_volume" == "${source_project}_storage-data" ]] || { echo 'Unexpected storage volume' >&2; exit 1; }
image=$("${dc[@]}" images -q postgres | head -1)
docker run --rm --network none --user 0 -v "$storage_volume:/source:ro" --entrypoint sh "$image" -c 'tar -C /source -cf - .' > "$backup/objects.tar"
cp -a .local/test/secrets .local/test/seaweedfs.json .local/test/envoy.json .local/test/temporal.yaml "$backup/config/"
[[ ! -f .local/test/backup-fixture.json ]] || cp .local/test/backup-fixture.json "$backup/fixture.json"
python3 - "$backup" "$source_project" <<'PY'
from pathlib import Path
import datetime,hashlib,json,sys
def digest(path):
 checksum=hashlib.sha256()
 with path.open('rb') as stream:
  for chunk in iter(lambda:stream.read(1048576),b''):checksum.update(chunk)
 return checksum.hexdigest()

folder=Path(sys.argv[1])
files={str(p.relative_to(folder)):digest(p) for p in folder.rglob('*') if p.is_file()}
import subprocess
images={}
for line in (folder/'config/container-images.jsonl').read_text().splitlines():
 container=json.loads(line)
 if container['Service'] in {'user','workspace','letfs','processor','issuer','envoy','postgres','storage','temporal','temporal-init','temporal-schema','temporal-backup','qdrant'}:
  images[container['Service']]=subprocess.check_output(['docker','inspect',container['ID'],'--format','{{.Image}}'],text=True).strip()
assert {'user','workspace','letfs','processor','envoy','issuer','postgres','storage','temporal','qdrant'} <= images.keys(), 'Missing application/model/index image identity'
(folder/'manifest.json').write_text(json.dumps({'format':2,'provider':'seaweedfs-4.19','source':sys.argv[2],'captured_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'writers':'stopped','images':images,'files':files},indent=2)+'\n')
PY
printf '%s\n' "$backup" > .local/test/last-snapshot
printf 'Coordinated snapshot: %s\nSource writers remain stopped; use the documented resume command.\n' "$backup"
