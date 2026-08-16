#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/tiny_m73_pm9x_common.sh"

pm9x_require_cmd rsync
pm9x_require_cmd ssh
pm9x_require_local_dir "${PM9X_PM97_SOURCE}"
pm9x_require_local_dir "${PM9X_PM98_SOURCE}"
pm9x_require_local_dir "${PM9X_PM99_SOURCE}"

pm9x_print_config

pm9x_ssh "mkdir -p '${PM9X_REMOTE_ROOT}/assets/pristine/pm97' '${PM9X_REMOTE_ROOT}/assets/pristine/pm98' '${PM9X_REMOTE_ROOT}/assets/pristine/pm99' '${PM9X_REMOTE_ROOT}/manifests' '${PM9X_REMOTE_ROOT}/logs'"

rsync -a --delete \
  --exclude='*.gpr' --exclude='*.rep' --exclude='*.lock' --exclude='*.lock~' \
  "${PM9X_PM97_SOURCE}/" "${PM9X_REMOTE}:${PM9X_REMOTE_ROOT}/assets/pristine/pm97/"

rsync -a --delete \
  --exclude='*.gpr' --exclude='*.rep' --exclude='*.lock' --exclude='*.lock~' \
  "${PM9X_PM98_SOURCE}/" "${PM9X_REMOTE}:${PM9X_REMOTE_ROOT}/assets/pristine/pm98/"

rsync -a --delete \
  --exclude='*.gpr' --exclude='*.rep' --exclude='*.lock' --exclude='*.lock~' \
  "${PM9X_PM99_SOURCE}/" "${PM9X_REMOTE}:${PM9X_REMOTE_ROOT}/assets/pristine/pm99/"

pm9x_ssh "PM9X_REMOTE_ROOT='${PM9X_REMOTE_ROOT}' python3 - <<'PY'
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

root = Path(os.environ['PM9X_REMOTE_ROOT'])
primary = {
    'pm97': ['PM97.EXE', 'MANAGER.EXE', 'DBASEWIN.EXE'],
    'pm98': ['PM98.EXE', 'MANAGER.EXE', 'Dbasewin.exe'],
    'pm99': ['PM99.EXE', 'MANAGPRE.EXE', 'DBASEPRE.EXE', 'MIDAS11.DLL'],
}

def file_entry(path: Path) -> dict:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return {
        'path': str(path),
        'size': path.stat().st_size,
        'sha256': h.hexdigest(),
    }

manifest = {
    'generated_at': datetime.now(timezone.utc).isoformat(),
    'root': str(root),
    'games': {},
}
for game, names in primary.items():
    game_root = root / 'assets' / 'pristine' / game
    rows = {}
    missing = []
    for name in names:
        path = game_root / name
        if path.is_file():
            rows[name] = file_entry(path)
        else:
            missing.append(name)
    manifest['games'][game] = {
        'asset_root': str(game_root),
        'primary_files': rows,
        'missing_optional_or_required': missing,
    }

out = root / 'manifests' / 'pm9x-assets.json'
out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\\n', encoding='utf-8')
print(out)
PY"
