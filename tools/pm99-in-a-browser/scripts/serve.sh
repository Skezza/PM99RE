#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
HOST="${PM99_BROWSER_HOST:-127.0.0.1}"
PORT="${PM99_BROWSER_PORT:-8099}"

cd "${ROOT}"
echo "Serving PM99 browser harness at http://${HOST}:${PORT}/"
python3 -m http.server "${PORT}" --bind "${HOST}"
