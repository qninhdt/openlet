#!/usr/bin/env bash
set -euo pipefail

sha=${1:?Pass the commit that passed CI}
repo="repos/${GITHUB_REPOSITORY:?}"
vps_base=
web_base=

if [[ ${GITHUB_EVENT_NAME:?} != workflow_dispatch ]]; then
  deployments=$(gh api --paginate "$repo/deployments?environment=openlet&ref=main&per_page=100" \
    --jq '.[] | [.id, .sha] | @tsv')
  while IFS=$'\t' read -r id deployed_sha; do
    [[ -n $id ]] || continue
    job_url=$(gh api "$repo/deployments/$id/statuses" \
      --jq 'map(select(.state == "success")) | .[0].log_url // empty')
    [[ $job_url == */job/* ]] || continue
    job=$(gh api "$repo/actions/jobs/${job_url##*/}" --jq .name)
    case "$job" in
      deploy) vps_base=${vps_base:-$deployed_sha} ;;
      deploy-web) web_base=${web_base:-$deployed_sha} ;;
    esac
    if [[ -n $vps_base && -n $web_base ]]; then break; fi
  done <<< "$deployments"
fi

plan_target() {
  local target=$1 base=$2 files deploy=false
  shift 2
  if [[ -z $base ]]; then
    deploy=true
  else
    files=$(git diff --no-renames --name-only "$base" "$sha" -- "$@" ':(exclude,glob)**/*.md')
    if [[ -n $files ]]; then deploy=true; fi
  fi
  printf '%s=%s\n' "$target" "$deploy" >> "${GITHUB_OUTPUT:?}"
  printf '%s deploy=%s (baseline %s)\n' "$target" "$deploy" "${base:-none}"
}

plan_target vps "$vps_base" \
  apps/platform apps/letfs apps/letfs-ingest apps/leta packages infra \
  scripts/{backup.sh,bootstrap.py,configure.py,deploy.sh,restore.sh} \
  go.work go.work.sum pyproject.toml uv.lock .python-version .dockerignore \
  ':(exclude)infra/compose.test.yaml' ':(exclude,glob)apps/**/tests/**' \
  ':(exclude,glob)apps/**/*_test.go'

plan_target web "$web_base" \
  apps/web package.json pnpm-lock.yaml pnpm-workspace.yaml packages/contracts/proto \
  ':(exclude)apps/web/tests' ':(exclude)apps/web/worker.test.mjs' \
  ':(exclude)apps/web/playwright.unit.config.ts'
