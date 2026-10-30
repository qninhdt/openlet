#!/bin/sh
set -eu
for name in user workspace letfs temporal temporal_visibility; do
  password=$(cat "/run/secrets/${name}_db_password")
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres --set=role="openlet_$name" --set=db="openlet_$name" --set=password="$password" <<'SQL'
CREATE ROLE :"role" LOGIN PASSWORD :'password';
ALTER ROLE :"role" SET statement_timeout = '15s';
ALTER ROLE :"role" SET lock_timeout = '5s';
CREATE DATABASE :"db" OWNER :"role";
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db" TO :"role";
SQL
done
