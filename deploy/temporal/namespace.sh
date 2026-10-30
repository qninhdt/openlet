#!/bin/sh
set -eu
export TEMPORAL_ADDRESS=temporal:7233
i=0
until temporal operator cluster health >/dev/null 2>&1; do
  i=$((i+1))
  [ "$i" -lt 60 ] || { echo 'Temporal did not become healthy' >&2; exit 1; }
  sleep 1
done
if ! temporal operator namespace describe --namespace openlet >/dev/null 2>&1; then
  temporal operator namespace create --namespace openlet --retention 168h
fi
temporal operator namespace describe --namespace openlet
