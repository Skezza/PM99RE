#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/tiny_m73_pm9x_common.sh"

pm9x_require_cmd ssh

remote_probe="${PM9X_REMOTE_ROOT}/tools/tiny_m73_pm9x_ghidramcp_probe.py"
remote_report="${PM9X_REMOTE_ROOT}/logs/ghidramcp-probe-$(date -u +%Y%m%dT%H%M%SZ).json"

pm9x_ssh "mkdir -p '${PM9X_REMOTE_ROOT}/tools' '${PM9X_REMOTE_ROOT}/logs'"
scp -q "${SCRIPT_DIR}/tiny_m73_pm9x_ghidramcp_probe.py" "${PM9X_REMOTE}:${remote_probe}"
pm9x_ssh "python3 '${remote_probe}' --url 'http://127.0.0.1:${PM9X_REMOTE_PORT}/mcp' --report '${remote_report}'"

echo "Remote probe report: ${PM9X_REMOTE}:${remote_report}"
