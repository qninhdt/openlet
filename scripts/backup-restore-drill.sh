#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export OPENLET_STATE_DIR=../.local/test
export OPENLET_TEST_UID="$(id -u)" OPENLET_TEST_GID="$(id -g)"
dc=(docker compose -p openlet-test -f deploy/compose.yaml -f deploy/compose.test.yaml)
[[ -z $("${dc[@]}" ps -q) ]] || { echo 'Stop the existing test suite before the restore drill' >&2; exit 2; }
stamp="$(date -u +%Y%m%d%H%M%S)-$$"
source_project="openlet-test-backup-$stamp"
project="openlet-restore-$stamp"
dc=(docker compose -p "$source_project" -f deploy/compose.yaml -f deploy/compose.test.yaml)
cleanup(){
  "${dc[@]}" logs --no-color > .local/test/drill-last.log 2>&1 || true
  "${dc[@]}" down --remove-orphans
  if [[ -f "$PWD/.local/$project/isolation.yaml" ]]; then
    OPENLET_STATE_DIR="$PWD/.local/$project" docker compose -p "$project" -f deploy/compose.yaml -f deploy/compose.test.yaml -f "$PWD/.local/$project/isolation.yaml" down --remove-orphans
  fi
}
trap cleanup EXIT
python3 scripts/configure.py --test
mkdir -m 700 -p .local/test/histories
"${dc[@]}" up -d --wait postgres storage
for scope in user workspace letfs; do "${dc[@]}" exec -T postgres sh /migrate.sh "$scope"; done
"${dc[@]}" exec -T storage sh -c "echo 's3.bucket.create -name openlet-test' | timeout 30 weed shell -master=storage:9333 -filer=storage:8888" > .local/test/s3-init.log 2>&1
rg -q '^created bucket openlet-test$' .local/test/s3-init.log
"${dc[@]}" up -d --build issuer user workspace letfs envoy
"${dc[@]}" up -d --build processor
"${dc[@]}" --profile test build tester
"${dc[@]}" --profile test run --rm tester -test.v -test.run TestReadiness
"${dc[@]}" --profile test run --rm -e OPENLET_BACKUP_FIXTURE=/histories/backup-fixture.json tester -test.v -test.run '^TestBackupSeed$'
cp .local/test/histories/backup-fixture.json .local/test/backup-fixture.json
bash scripts/backup-local.sh "$source_project"
snapshot=$(cat .local/test/last-snapshot)
bash scripts/restore-local.sh "$snapshot" "$project"
cp "$snapshot/fixture.json" ".local/$project/histories/backup-fixture.json"
export OPENLET_STATE_DIR="$PWD/.local/$project"
restored=(docker compose -p "$project" -f deploy/compose.yaml -f deploy/compose.test.yaml -f "$PWD/.local/$project/isolation.yaml")
"${restored[@]}" run --rm --no-deps --entrypoint temporal temporal-init --address temporal:7233 schedule describe --namespace openlet --schedule-id openlet-storage-maintenance -o json > ".local/$project/schedule.json"
python3 - ".local/$project/schedule.json" <<'PYTHON'
import json,sys
schedule=json.load(open(sys.argv[1]))['schedule']
assert schedule['state']['paused'] is True, 'Restored maintenance must remain paused'
assert schedule['policies']['overlapPolicy']=='SCHEDULE_OVERLAP_POLICY_SKIP'
PYTHON
"${restored[@]}" ps --format json | python3 -c 'import json,sys; rows=[json.loads(line) for line in sys.stdin if line.strip()]; assert not [p for r in rows for p in (r.get("Publishers") or []) if p["PublishedPort"]]'
if "${restored[@]}" ps --status running --services | rg -q '^(user|workspace|letfs|processor|envoy|issuer)$'; then echo 'Restore started application execution before explicit resume' >&2; exit 1; fi
echo 'Paused isolated infrastructure verified; explicitly resuming application workers for read verification'
"${restored[@]}" up -d issuer user workspace letfs processor envoy
"${restored[@]}" --profile test run --rm tester -test.v -test.run TestReadiness
"${restored[@]}" --profile test run --rm -e OPENLET_BACKUP_FIXTURE=/histories/backup-fixture.json tester -test.v -test.run '^TestBackupRestore$'
echo "Isolated metadata/object/Temporal restore passed: $project"
