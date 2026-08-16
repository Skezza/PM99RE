#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/tiny_m73_pm9x_common.sh"

pm9x_require_cmd ssh

echo "Forwarding http://127.0.0.1:${PM9X_LOCAL_PORT}/mcp to ${PM9X_REMOTE}:127.0.0.1:${PM9X_REMOTE_PORT}/mcp"
exec ssh -N -L "127.0.0.1:${PM9X_LOCAL_PORT}:127.0.0.1:${PM9X_REMOTE_PORT}" "${PM9X_REMOTE}"
