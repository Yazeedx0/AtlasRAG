#!/usr/bin/env bash
set -Eeuo pipefail

: "${ATLAS_KEYCLOAK_DB:?ATLAS_KEYCLOAK_DB is required}"
: "${ATLAS_KEYCLOAK_DB_USER:?ATLAS_KEYCLOAK_DB_USER is required}"
: "${ATLAS_KEYCLOAK_DB_PASSWORD:?ATLAS_KEYCLOAK_DB_PASSWORD is required}"

psql \
  --dbname "$POSTGRES_DB" \
  --username "$POSTGRES_USER" \
  --set=keycloak_user="$ATLAS_KEYCLOAK_DB_USER" \
  --set=keycloak_password="$ATLAS_KEYCLOAK_DB_PASSWORD" <<'SQL'
SELECT format(
  'CREATE ROLE %I LOGIN PASSWORD %L',
  :'keycloak_user',
  :'keycloak_password'
)
WHERE NOT EXISTS (
  SELECT 1 FROM pg_roles WHERE rolname = :'keycloak_user'
)
\gexec
SQL

psql \
  --dbname "$POSTGRES_DB" \
  --username "$POSTGRES_USER" \
  --set=keycloak_db="$ATLAS_KEYCLOAK_DB" \
  --set=keycloak_user="$ATLAS_KEYCLOAK_DB_USER" <<'SQL'
SELECT format(
  'CREATE DATABASE %I OWNER %I',
  :'keycloak_db',
  :'keycloak_user'
)
WHERE NOT EXISTS (
  SELECT 1 FROM pg_database WHERE datname = :'keycloak_db'
)
\gexec
SQL
