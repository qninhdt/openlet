#!/usr/bin/env bash
# Native service integration suites; system journeys remain in test-e2e.
set -euo pipefail
cd "$(dirname "$0")/.."
service=${1:-all}
case "$service" in all|user|workspace|letfs) ;; *) echo 'SERVICE must be user, workspace, letfs or all' >&2; exit 2 ;; esac
case "${2:-}" in ''|all) filter= ;; direct-storage|artifacts|zip-export|search) [[ $service == letfs ]] || { echo 'storage selectors require SERVICE=letfs' >&2; exit 2; }; filter=${2//-/_} ;;  *) echo 'Use SERVICE=user|workspace|letfs for integration; use make test-e2e TEST=... for full-stack scenarios' >&2; exit 2 ;; esac
export CARGO_INCREMENTAL=0
# Each Rust case owns PostgreSQL, S3 and Temporal; bound fixture processes independently of CPU count.
export RUST_TEST_THREADS=${RUST_TEST_THREADS:-2}
for selected in user workspace letfs; do
  [[ "$service" == all || "$service" == "$selected" ]] || continue
  if [[ "$selected" == letfs ]]; then
    cases=$(cargo test --manifest-path services/letfs/Cargo.toml --locked --test integration "${filter:-}" -- --list --ignored)
    rg -q ': test$' <<< "$cases" || { echo 'No letfs integration tests selected' >&2; exit 1; }
    cargo test --manifest-path services/letfs/Cargo.toml --locked --test integration "${filter:-}" -- --ignored --nocapture
  else
    cases=$("${GO:-go}" test -tags integration -list '^TestIntegration' "./services/$selected/internal/$selected")
    rg -q '^TestIntegration' <<< "$cases" || { echo "No $selected integration tests selected" >&2; exit 1; }
    "${GO:-go}" test -tags integration -count=1 -run '^TestIntegration' -v "./services/$selected/internal/$selected"
  fi
done
