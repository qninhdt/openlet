#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
suite=${1:-all}
case "$suite" in ''|all|foundation|compose-smoke|identity-workspace|filesystem-core|files|filesystem-scope|identity-files|object-storage|uploads|storage-copy|direct-storage|lifecycle|lifecycle-races|destructive-authorization|worker-restarts|copy-races|processing|processing-recovery|zip-export) ;; *) echo "unknown suite: $1" >&2; exit 2 ;; esac
export OPENLET_STATE_DIR=../.local/test
export OPENLET_TEST_UID="$(id -u)" OPENLET_TEST_GID="$(id -g)"
mkdir -p .local/test/histories
rm -f .local/test/histories/contracts/responses.jsonl
dc=(docker compose -p openlet-test -f deploy/compose.yaml -f deploy/compose.test.yaml)
cleanup() { "${dc[@]}" down --remove-orphans; }
trap cleanup EXIT
python3 scripts/configure.py --test
"${dc[@]}" up -d --wait postgres
for service in user workspace letfs; do
 "${dc[@]}" exec -T postgres sh /migrate.sh "$service"
 "${dc[@]}" exec -T postgres psql -U openlet_admin -d "openlet_$service" -v ON_ERROR_STOP=1 -c 'CREATE EXTENSION IF NOT EXISTS pg_stat_statements'
done
"${dc[@]}" up -d --wait storage
"${dc[@]}" exec -T storage sh -c "echo 's3.bucket.create -name openlet-test' | timeout 30 weed shell -master=storage:9333 -filer=storage:8888" > .local/test/s3-init.log 2>&1
if ! rg -q '^created bucket openlet-test$' .local/test/s3-init.log; then echo 'S3 test bucket initialization failed' >&2; exit 1; fi
"${dc[@]}" up -d --build issuer user workspace letfs envoy
if [[ "$suite" == all || "$suite" == processing || "$suite" == processing-recovery || "$suite" == zip-export ]]; then
 "${dc[@]}" up -d --build processor
fi
"${dc[@]}" --profile test build tester
"${dc[@]}" --profile test run --rm tester -test.v -test.run TestReadiness
"${dc[@]}" --profile test run --rm tester -test.v -test.run 'TestGateway|TestProvisioning'
if [[ "$suite" == all || "$suite" == identity-workspace || "$suite" == identity-files ]]; then
  "${dc[@]}" --profile test run --rm tester -test.v -test.run 'TestIdentityWorkspace|TestAdmissionReplacement|TestOwnershipLockRechecks|TestLetfsAdmissionReplacement'
fi
if [[ "$suite" == all || "$suite" == identity-files || "$suite" == filesystem-core || "$suite" == files || "$suite" == filesystem-scope ]]; then
 "${dc[@]}" --profile test run --rm tester -test.v -test.run TestFilesystem
fi
if [[ "$suite" == all || "$suite" == object-storage || "$suite" == uploads || "$suite" == storage-copy || "$suite" == direct-storage || "$suite" == copy-races ]]; then
 "${dc[@]}" --profile test run --rm tester -test.v -test.run TestStorage
fi
if [[ "$suite" == all || "$suite" == zip-export ]]; then
 "${dc[@]}" --profile test run --rm tester -test.v -test.run '^TestZipExport'
fi
if [[ "$suite" == all || "$suite" == processing ]]; then
 "${dc[@]}" --profile test run --rm tester -test.v -test.run '^TestProcessing$'
fi
if [[ "$suite" == all || "$suite" == processing-recovery ]]; then
 rm -f .local/test/histories/processing-recovery-ready .local/test/histories/processing-recovery-resume
 "${dc[@]}" --profile test run --rm tester -test.v -test.run '^TestProcessing(Recovery|Exhausted)$' &
 processing_pid=$!
 for ((attempt=0;attempt<600;attempt++)); do
   [[ ! -f .local/test/histories/processing-recovery-ready ]] || break
   kill -0 "$processing_pid" 2>/dev/null || { wait "$processing_pid"; exit 1; }
   sleep 0.1
 done
 [[ -f .local/test/histories/processing-recovery-ready ]] || { echo 'Processing source GET barrier timed out' >&2; exit 1; }
 "${dc[@]}" kill -s SIGKILL processor
 "${dc[@]}" up -d processor
 touch .local/test/histories/processing-recovery-resume
 wait "$processing_pid"
fi
if [[ "$suite" == all || "$suite" == lifecycle || "$suite" == lifecycle-races || "$suite" == destructive-authorization ]]; then
 "${dc[@]}" --profile test run --rm tester -test.v -test.run 'TestDurableLifecycle|TestStorageMaintenancePolicy|TestRestorePurgeBarrier'
fi
if [[ "$suite" == all || "$suite" == worker-restarts ]]; then
 rm -f .local/test/histories/recovery-ready .local/test/histories/recovery-resume
 "${dc[@]}" --profile test run --rm tester -test.v -test.run '^TestWorkerRecovery$' &
 recovery_pid=$!
 for ((attempt=0;attempt<600;attempt++)); do
   [[ ! -f .local/test/histories/recovery-ready ]] || break
   kill -0 "$recovery_pid" 2>/dev/null || { wait "$recovery_pid"; exit 1; }
   sleep 0.1
 done
 [[ -f .local/test/histories/recovery-ready ]] || { echo 'Recovery barrier timed out' >&2; exit 1; }
 "${dc[@]}" kill -s SIGKILL letfs temporal
 "${dc[@]}" restart postgres
 "${dc[@]}" up -d temporal letfs
 "${dc[@]}" --profile test run --rm tester -test.v -test.run TestReadiness
 touch .local/test/histories/recovery-resume
 wait "$recovery_pid"
fi
"${dc[@]}" --profile test run --rm tester -test.v -test.run TestRateLimit
"${dc[@]}" ps --format json | python3 -c 'import json,sys; rows=[json.loads(line) for line in sys.stdin if line.strip()]; exposed=[(r["Service"],p["PublishedPort"]) for r in rows for p in (r.get("Publishers") or []) if p["PublishedPort"]]; assert sorted(exposed)==sorted([("envoy",8080),("issuer",int(__import__("os").environ.get("OPENLET_TEST_S3_PORT","8333")))]), exposed'
bash scripts/verify-database-isolation.sh openlet-test
"${dc[@]}" exec -T postgres psql -U openlet_admin -d openlet_letfs -v ON_ERROR_STOP=1 -c "DO \$\$ BEGIN IF EXISTS (SELECT 1 FROM filesystems f WHERE node_count <> (SELECT count(*) FROM nodes n WHERE n.filesystem_id=f.id)) THEN RAISE EXCEPTION 'node count drift'; END IF; END \$\$;"
"${dc[@]}" restart postgres temporal user workspace letfs
"${dc[@]}" --profile test run --rm tester -test.v -test.run TestReadiness
"${dc[@]}" exec -T postgres psql -U openlet_admin -d openlet_letfs -v ON_ERROR_STOP=1 -c "DO \$\$ BEGIN IF NOT EXISTS(SELECT 1 FROM filesystems f JOIN nodes n ON n.id=f.root_id) THEN RAISE EXCEPTION 'restart lost provisioning'; END IF; END \$\$;"
"${dc[@]}" run --rm --no-deps temporal-init
