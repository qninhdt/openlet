#!/bin/sh
set -eu
for scope in temporal temporal_visibility; do
  export SQL_PASSWORD=$(cat "/run/secrets/${scope}_db_password")
  export SQL_USER="openlet_$scope" SQL_DATABASE="openlet_$scope" SQL_HOST=postgres SQL_PORT=5432 SQL_PLUGIN=postgres12_pgx
  kind=temporal
  [ "$scope" != temporal_visibility ] || kind=visibility
  temporal-sql-tool setup-schema -v 0.0
  temporal-sql-tool update-schema -d "/etc/temporal/schema/postgresql/v12/$kind/versioned"
done
