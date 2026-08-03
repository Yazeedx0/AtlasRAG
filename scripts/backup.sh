#!/usr/bin/env bash
# Dump the Postgres database (documents, chunks, embeddings, users, conversations,
# feedback) to a compressed archive and prune backups older than RETENTION_DAYS.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TARGET="${BACKUP_DIR}/atlas-${STAMP}.dump"

: "${ATLAS_DATABASE_URL:?set ATLAS_DATABASE_URL (postgresql://... — no +asyncpg driver suffix)}"

mkdir -p "${BACKUP_DIR}"

echo "==> dumping to ${TARGET}"
pg_dump --format=custom --no-owner --no-privileges \
  --dbname="${ATLAS_DATABASE_URL}" --file="${TARGET}"

echo "==> pruning dumps older than ${RETENTION_DAYS} days"
find "${BACKUP_DIR}" -name 'atlas-*.dump' -type f -mtime "+${RETENTION_DAYS}" -print -delete

echo "==> done: $(du -h "${TARGET}" | cut -f1)"
