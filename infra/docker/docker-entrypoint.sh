#!/usr/bin/env bash
set -euo pipefail

wait_for_postgres() {
  python - <<'PY'
import os
import socket
import sys
import time
from urllib.parse import urlsplit

url = urlsplit(os.environ["ATLAS_DATABASE_URL"])
host, port = url.hostname, url.port or 5432

for _ in range(30):
    try:
        with socket.create_connection((host, port), timeout=2):
            sys.exit(0)
    except OSError:
        time.sleep(1)

sys.exit(1)
PY
}

wait_for_postgres
alembic upgrade head

exec "$@"
