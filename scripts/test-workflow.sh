#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export OPENLET_HISTORY_DIR="$PWD/.local/test/histories"
case "${1:-}" in
 '') pattern=Test; replay=true ;;
 export-archive)
  for name in ExportArchive ExportArchiveRetry; do
   [[ -s "$OPENLET_HISTORY_DIR/$name.bin" ]] || { echo 'Run make test-e2e TEST=zip-export first' >&2; exit 2; }
  done
  cargo test --manifest-path services/letfs/Cargo.toml --locked --test workflow-replay export_archive_history_replays -- --ignored
  exit ;;
 process-file)
  for name in ProcessFilePdf ProcessFileDocx ProcessFilePptx ProcessFileXlsx; do
   [[ -s "$OPENLET_HISTORY_DIR/$name.bin" ]] || { echo 'Run make test-e2e TEST=processing first' >&2; exit 2; }
  done
  cargo test --manifest-path services/letfs/Cargo.toml --locked --test workflow-replay process_file_history_replays -- --ignored
  exit ;;
 onboarding) pattern=TestOnboardUser; replay=false ;;
 provisioning) pattern=TestCreateWorkspace; replay=false ;;
 destructive-lifecycle) pattern=TestDeleteWorkspace; replay=true ;;
 copy-node|replay) pattern=TestRecorded; replay=true ;;
 *) echo "unknown workflow suite: $1" >&2; exit 2 ;;
esac
packages=(./services/user/internal/temporal ./services/workspace/internal/temporal)
if [[ "$replay" == true ]]; then
  for name in OnboardUser CreateWorkspace DeleteWorkspace CopyNode CopyNodeFailed CopyNodeRecovery PurgeTrash DeleteFilesystem StorageMaintenance ProcessFilePdf ProcessFileDocx ProcessFilePptx ProcessFileXlsx ProcessFileRecovery ProcessFileExhausted ExportArchive ExportArchiveRetry; do
    [[ -s "$OPENLET_HISTORY_DIR/$name.json" && -s "$OPENLET_HISTORY_DIR/$name.bin" ]] || { echo 'Run make test-e2e TEST=all first to generate real histories' >&2; exit 2; }
  done
  "${GO:-go}" test -tags workflow,replay -count=1 -run "$pattern" "${packages[@]}"
  cargo test --manifest-path services/letfs/Cargo.toml --locked --test workflow-replay -- --ignored
else
  "${GO:-go}" test -tags workflow -count=1 -run "$pattern" "${packages[@]}"
fi
