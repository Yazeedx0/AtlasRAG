#!/usr/bin/env bash
set -Eeuo pipefail

: "${ATLAS_MINIO_ROOT_USER:?ATLAS_MINIO_ROOT_USER is required}"
: "${ATLAS_MINIO_ROOT_PASSWORD:?ATLAS_MINIO_ROOT_PASSWORD is required}"
: "${ATLAS_MINIO_BUCKET:?ATLAS_MINIO_BUCKET is required}"

mc alias set local http://minio:9000 "$ATLAS_MINIO_ROOT_USER" "$ATLAS_MINIO_ROOT_PASSWORD"
mc mb --ignore-existing "local/$ATLAS_MINIO_BUCKET"
