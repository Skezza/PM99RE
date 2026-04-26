#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dashboard_screen="tiny-m73-sys-dashboard"
temp_screen="tiny-m73-temp-print"
dashboard_log="$repo_root/.local/tiny-m73-sys-dashboard.log"
temp_log="$repo_root/.local/tiny-m73-temp-print.log"

restart_screen() {
  local name="$1"
  local command="$2"
  local logfile="$3"

  screen -S "$name" -X quit >/dev/null 2>&1 || true
  screen -dmS "$name" bash -lc "cd '$repo_root' && $command >> '$logfile' 2>&1"
}

restart_screen "$dashboard_screen" "python3 scripts/tiny_m73_sys_dashboard.py" "$dashboard_log"
restart_screen "$temp_screen" ".local/tiny-m73-temp-printer.sh 192.168.1.175 900" "$temp_log"

cat <<EOF
Restarted:
- dashboard: screen -r $dashboard_screen
- temp print: screen -r $temp_screen
- dashboard URL: http://127.0.0.1:8766/
EOF
