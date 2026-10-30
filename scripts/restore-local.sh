#!/usr/bin/env bash
# Restore only to a fresh isolated project; existing volumes are never overwritten.
set -euo pipefail
cd "$(dirname "$0")/.."
[[ $# == 2 ]] || { echo 'Usage: scripts/restore-local.sh SNAPSHOT openlet-restore-NAME' >&2; exit 2; }
snapshot=$(realpath "$1")
project=$2
[[ "$snapshot" == "$PWD/.local/snapshots/"* && "$project" =~ ^openlet-restore-[a-z0-9-]+$ ]] || { echo 'Snapshot or isolated target guard rejected' >&2; exit 2; }
for volume in postgres-data storage-data; do
  ! docker volume inspect "${project}_$volume" >/dev/null 2>&1 || { echo 'Target volume already exists; use a new restore name' >&2; exit 2; }
done
python3 - "$snapshot" <<'PY'
from pathlib import Path
import hashlib,json,sys
def digest(path):
 checksum=hashlib.sha256()
 with path.open('rb') as stream:
  for chunk in iter(lambda:stream.read(1048576),b''):checksum.update(chunk)
 return checksum.hexdigest()

folder=Path(sys.argv[1]);manifest=json.loads((folder/'manifest.json').read_text())
assert manifest['format']==2 and manifest['provider']=='seaweedfs-4.19' and manifest['writers']=='stopped', 'Requires a stopped-writer format-2 snapshot with pinned application/model images'
for relative,expected_digest in manifest['files'].items():
 path=(folder/relative).resolve();assert path.is_relative_to(folder)
 assert digest(path)==expected_digest,relative
PY
state="$PWD/.local/$project"
[[ ! -e "$state" ]] || { echo 'Target state directory already exists' >&2; exit 2; }
umask 077
mkdir -m 700 "$state"
mkdir -m 700 "$state/backups" "$state/histories"
cp -a "$snapshot/config/." "$state/"
python3 - "$snapshot" "$state/isolation.yaml" <<'PY'
from pathlib import Path
import json,subprocess,sys
manifest=json.loads((Path(sys.argv[1])/'manifest.json').read_text())
with Path(sys.argv[2]).open('w') as output:
 output.write('services:\n')
 for service,image in manifest['images'].items():
  subprocess.run(['docker','image','inspect',image],stdout=subprocess.DEVNULL,check=True)
  output.write(f'  {service}:\n    image: {image}\n    pull_policy: never\n    build: !reset null\n')
  if service in {'envoy','issuer'}:
   output.write('    ports: !reset []\n')
PY
export OPENLET_STATE_DIR="$state"
export OPENLET_TEST_UID="$(id -u)" OPENLET_TEST_GID="$(id -g)"
dc=(docker compose -p "$project" -f deploy/compose.yaml -f deploy/compose.test.yaml -f "$state/isolation.yaml")
"${dc[@]}" create postgres
"${dc[@]}" up -d --wait postgres
for scope in user workspace letfs temporal temporal_visibility; do
  "${dc[@]}" exec -T postgres pg_restore --exit-on-error --no-owner -U "openlet_$scope" -d "openlet_$scope" < "$snapshot/databases/$scope.dump"
done
image=$("${dc[@]}" images -q postgres | head -1)
docker volume create --label "com.docker.compose.project=$project" --label com.docker.compose.volume=storage-data "${project}_storage-data" >/dev/null
docker run --rm --network none --user 0 --mount "type=volume,source=${project}_storage-data,target=/restore-data,volume-nocopy" -v "$snapshot:/snapshot:ro" --entrypoint sh "$image" -c 'test -z "$(ls -A /restore-data)" && tar -C /restore-data -xf /snapshot/objects.tar'
"${dc[@]}" up -d --wait storage
"${dc[@]}" up -d temporal
"${dc[@]}" run --rm --no-deps --entrypoint temporal temporal-init --address temporal:7233 operator namespace describe --namespace openlet > "$state/namespace.json"
printf '%s\n' "$project" > .local/test/last-restore
printf 'Isolated infrastructure restored: %s (application workers stopped, no published port; explicit resume required)\n' "$project"
