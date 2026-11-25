#!/usr/bin/env bash
set -Eeuo pipefail

# Deploy Openlet with pre-pull, online backup, healthcheck, auto-rollback, and Openlet-scoped retention.
# Usage: scripts/deploy.sh CONFIG_YAML DOTENV IMAGE_LOCK [REGISTRY_USER]

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"

OPENLET_CONFIG=$(realpath "${1:?Usage: scripts/deploy.sh CONFIG_YAML DOTENV IMAGE_LOCK [REGISTRY_USER]}")
dotenv=$(realpath "${2:?Dotenv path required}")
image_lock=$(realpath "${3:?Immutable image-lock Compose file required}")
registry_user=${4:-}

export OPENLET_CONFIG
export OPENLET_DOTENV="$dotenv"
export COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-openlet}
export OPENLET_GENERATED="$root/.local/generated"
export OPENLET_BACKUPS=${OPENLET_BACKUPS:-"$root/.local/backups"}
state_dir=${OPENLET_STATE_DIR:-}

umask 077
mkdir -p "$OPENLET_BACKUPS"
chmod 700 "$OPENLET_BACKUPS"

"${UV:-uv}" run --env-file "$dotenv" --locked --no-dev --package openlet-tooling \
  python scripts/configure.py --output "$OPENLET_GENERATED"

compose_files="$root/infra/compose.yaml:$OPENLET_GENERATED/compose.runtime.yaml:$image_lock"
if [[ -n $registry_user ]]; then
  compose_files="$compose_files:$root/infra/compose.vps.yaml"
fi
export COMPOSE_FILE="$compose_files"

if [[ -n $registry_user ]]; then
  export DOCKER_CONFIG
  DOCKER_CONFIG=$(mktemp -d)
  trap 'rm -rf -- "$DOCKER_CONFIG"' EXIT
  docker login ghcr.io --username "$registry_user" --password-stdin
fi

docker compose config --quiet
docker compose pull --ignore-buildable
if [[ -n $registry_user ]]; then
  docker compose pull platform platform-migrate letfs letfs-migrate ingest-cpu ingest-io leta-api leta-worker leta-migrate
fi

if [[ -n $(docker compose ps -q --status running postgres) ]]; then
  scripts/backup.sh "$OPENLET_BACKUPS/pre-deploy-$(date -u +%Y%m%dT%H%M%SZ)"
fi

rollback() {
  if [[ -z $state_dir || ! -L "$state_dir/current" ]]; then
    echo "Deploy failed and no previous release symlink is available for rollback." >&2
    return 1
  fi
  prev_dir=$(readlink -f "$state_dir/current")
  if [[ "$prev_dir" == "$root" || ! -f "$prev_dir/image-lock.yaml" ]]; then
    echo "Deploy failed; previous release ($prev_dir) cannot be rolled back." >&2
    return 1
  fi
  echo "Healthcheck failed — rolling back to $prev_dir" >&2
  OPENLET_STATE_DIR="" "$prev_dir/scripts/deploy.sh" "$OPENLET_CONFIG" "$dotenv" "$prev_dir/image-lock.yaml"
}

healthcheck() {
  local code _
  for _ in $(seq 1 15); do
    code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8080/v1/workspaces || true)
    if [[ "$code" == "401" ]]; then
      return 0
    fi
    sleep 2
  done
  echo "Gateway healthcheck failed after 15 attempts (last HTTP status: ${code:-none})" >&2
  return 1
}

if ! docker compose up --detach --no-build --remove-orphans --wait --wait-timeout 180 || ! healthcheck; then
  rollback || true
  exit 1
fi

if [[ -n $state_dir ]]; then
  if [[ -L "$state_dir/current" ]]; then
    old_current=$(readlink -f "$state_dir/current")
    if [[ "$old_current" != "$root" ]]; then
      ln -sfn "$old_current" "$state_dir/previous"
    fi
  fi
  ln -sfn "$root" "$state_dir/current"

  if [[ -d "$state_dir/releases" ]]; then
    mapfile -t old_releases < <(find "$state_dir/releases" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -rn | awk 'NR>5 {print $2}')
    for rel in "${old_releases[@]}"; do
      [[ "$rel" == "$root" ]] && continue
      [[ -L "$state_dir/previous" && "$rel" == "$(readlink -f "$state_dir/previous")" ]] && continue
      rm -rf -- "$rel"
    done
  fi
fi

mapfile -t old_backups < <(find "$OPENLET_BACKUPS" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -rn | awk 'NR>7 {print $2}')
for bak in "${old_backups[@]}"; do
  rm -rf -- "$bak"
done

# Openlet-scoped image cleanup: never prune images belonging to co-hosted apps.
mapfile -t active_images < <(docker ps -a --format '{{.Image}}')
mapfile -t openlet_images < <(docker images --format '{{.Repository}}@{{.Digest}} {{.ID}}' | awk '$1 ~ /^ghcr\.io\/qninhdt\/openlet-/ {print $2}' | sort -u)
for img_id in "${openlet_images[@]}"; do
  in_use=0
  for active in "${active_images[@]}"; do
    active_id=$(docker image inspect --format '{{.Id}}' "$active" 2>/dev/null || true)
    if [[ "$active_id" == *"$img_id"* ]]; then
      in_use=1
      break
    fi
  done
  if (( ! in_use )); then
    docker rmi "$img_id" >/dev/null 2>&1 || true
  fi
done

echo "Deployment healthy at $root"
