#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/tiny_m73_pm9x_common.sh"

remote_ghidra_dir="$(pm9x_remote_ghidra_dir)"
remote_project_file="${PM9X_REMOTE_ROOT}/ghidra-projects/PM9X.gpr"

pm9x_require_cmd ssh
pm9x_print_config

if [[ "${PM9X_REMOTE_PORT}" != "8080" ]]; then
  echo "GhidraMCP port automation currently expects the extension default port 8080." >&2
  exit 2
fi

pm9x_ssh "set -euo pipefail
mkdir -p ~/.config/systemd/user '${PM9X_REMOTE_ROOT}/logs'
test -x '${remote_ghidra_dir}/support/launch.sh'
test -f '${remote_project_file}'
python3 - <<'PY'
from pathlib import Path

display = '${PM9X_DISPLAY}'
root = '${PM9X_REMOTE_ROOT}'
ghidra_dir = '${remote_ghidra_dir}'
project_file = '${remote_project_file}'
remote_port = '${PM9X_REMOTE_PORT}'

user_dir = Path.home() / '.config' / 'systemd' / 'user'
preferences = Path.home() / '.config' / 'ghidra' / Path(ghidra_dir).name / 'preferences'
preferences.parent.mkdir(parents=True, exist_ok=True)
lines = preferences.read_text(encoding='utf-8').splitlines() if preferences.exists() else []
updated = False
for idx, line in enumerate(lines):
    if line.startswith('USER_AGREEMENT='):
        lines[idx] = 'USER_AGREEMENT=ACCEPT'
        updated = True
if not updated:
    lines.append('USER_AGREEMENT=ACCEPT')
preferences.write_text('\\n'.join(lines) + '\\n', encoding='utf-8')

(user_dir / 'pm9x-ghidra-xvfb.service').write_text(f'''[Unit]
Description=PM9X Ghidra virtual display

[Service]
ExecStart=/usr/bin/Xvfb :{display} -screen 0 1600x1000x24 -nolisten tcp
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
''', encoding='utf-8')

(user_dir / 'pm9x-ghidramcp.service').write_text(f'''[Unit]
Description=PM9X Ghidra with GhidraMCP
Requires=pm9x-ghidra-xvfb.service
After=pm9x-ghidra-xvfb.service

[Service]
Type=simple
WorkingDirectory={ghidra_dir}
Environment=DISPLAY=:{display}
Environment=JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
Environment=_JAVA_AWT_WM_NONREPARENTING=1
Environment=PM9X_REMOTE_ROOT={root}
ExecStart={ghidra_dir}/support/launch.sh fg jdk Ghidra 4G \"\" ghidra.GhidraRun {project_file}
Restart=on-failure
RestartSec=5
StandardOutput=append:{root}/logs/pm9x-ghidramcp-service.log
StandardError=append:{root}/logs/pm9x-ghidramcp-service.log

[Install]
WantedBy=default.target
''', encoding='utf-8')
print(f'Wrote systemd user services for display :{display} and MCP port {remote_port}')
PY
systemctl --user daemon-reload
systemctl --user enable --now pm9x-ghidra-xvfb.service
systemctl --user enable pm9x-ghidramcp.service
systemctl --user restart pm9x-ghidramcp.service
sleep 5
systemctl --user --no-pager --full status pm9x-ghidra-xvfb.service pm9x-ghidramcp.service | sed -n '1,80p'
ss -ltnp | grep ':${PM9X_REMOTE_PORT} ' || true"
