#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_WORKER_ID="${USER:-worker}"
DEFAULT_RUN_ID="stoke_2015_isolated_$(date -u +%Y%m%dT%H%M%SZ)"

WORKER_ID="${DEFAULT_WORKER_ID}"
RUN_ID="${DEFAULT_RUN_ID}"
RUN_ROOT=""
TEAM_QUERY="Stoke C."
PRINT_JSON=0
SKIP_SQUAD=0
SKIP_METADATA=0
SKIP_FACES=0

usage() {
  cat <<EOF
Usage: ./scripts/build_stoke_2015_isolated_game.sh [options]

Create or reuse an isolated PM99 run root, apply the Stoke 2015 squad rewrite,
optionally apply metadata and player faces, and record each mutation in the run
manifest.

Options:
  --worker-id <id>      Worker label for a newly created run
  --run-id <id>         Run identifier for a newly created run
  --run-root <path>     Reuse an existing isolated run root instead of creating one
  --team-query <txt>    Team query for Stoke rewrites (default: Stoke C.)
  --skip-squad          Skip the Stoke 2015 squad rewrite/validate phase
  --skip-metadata       Skip the Stoke 2015 metadata phase
  --skip-faces          Skip the Stoke 2015 face patch phase
  --json                Print a JSON summary at the end
  -h, --help            Show this help
EOF
}

abs_path() {
  python3 - "$1" <<'PY'
from pathlib import Path
import sys

print(Path(sys.argv[1]).expanduser().resolve())
PY
}

append_mutation() {
  local manifest_path="$1"
  local game_root="$2"
  local step_name="$3"
  local summary_path="$4"

  PYTHONPATH="${ROOT_DIR}/scripts${PYTHONPATH:+:${PYTHONPATH}}" \
    python3 - "${manifest_path}" "${game_root}" "${step_name}" "${summary_path}" <<'PY'
from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sys

from assert_pm99_isolated_input import core_file_hashes

manifest_path = Path(sys.argv[1]).resolve()
game_root = Path(sys.argv[2]).resolve()
step_name = sys.argv[3]
summary_path = Path(sys.argv[4]).resolve()

payload = json.loads(manifest_path.read_text(encoding="utf-8"))
mutations = list(payload.get("mutations") or [])
mutations.append(
    {
        "step": step_name,
        "timestamp_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary_path": str(summary_path),
        "core_files": core_file_hashes(game_root),
    }
)
payload["mutations"] = mutations
manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --worker-id) WORKER_ID="$2"; shift 2 ;;
    --run-id) RUN_ID="$2"; shift 2 ;;
    --run-root) RUN_ROOT="$2"; shift 2 ;;
    --team-query) TEAM_QUERY="$2"; shift 2 ;;
    --skip-squad) SKIP_SQUAD=1; shift ;;
    --skip-metadata) SKIP_METADATA=1; shift ;;
    --skip-faces) SKIP_FACES=1; shift ;;
    --json) PRINT_JSON=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "${RUN_ROOT}" ]]; then
  create_payload="$("${ROOT_DIR}/scripts/create_pm99_isolated_run.sh" --worker-id "${WORKER_ID}" --run-id "${RUN_ID}" --json)"
  RUN_ROOT="$(python3 - "${create_payload}" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
print(payload["run_root"])
PY
)"
else
  RUN_ROOT="$(abs_path "${RUN_ROOT}")"
fi

GAME_ROOT="${RUN_ROOT}/game"
RUN_MANIFEST="${RUN_ROOT}/run_manifest.json"
python3 "${ROOT_DIR}/scripts/assert_pm99_isolated_input.py" --game-root "${GAME_ROOT}" --require-writable >/dev/null
if [[ ! -f "${RUN_MANIFEST}" ]]; then
  echo "Missing run manifest: ${RUN_MANIFEST}" >&2
  exit 2
fi

SQUAD_DIR="${RUN_ROOT}/patches/stoke_2015_squad"
METADATA_DIR="${RUN_ROOT}/patches/stoke_2015_metadata"
FACE_DIR="${RUN_ROOT}/patches/stoke_2015_faces"
mkdir -p "${SQUAD_DIR}" "${METADATA_DIR}" "${FACE_DIR}"

if [[ ${SKIP_SQUAD} -eq 0 ]]; then
  PM99_EDITOR_ROOT="${ROOT_DIR}/upstream/pm99-skezmod-db-editor" \
    python3 "${ROOT_DIR}/upstream/pm99-runner/scripts/pm99_runner/apply_stoke_2015_strategy.py" \
      --game-dir "${GAME_ROOT}" \
      --artifacts-dir "${SQUAD_DIR}" \
      --team-query "${TEAM_QUERY}" \
      --skip-validate
  append_mutation "${RUN_MANIFEST}" "${GAME_ROOT}" "apply_stoke_2015_strategy" "${SQUAD_DIR}/summary.json"

  "${ROOT_DIR}/scripts/dev_editor.sh" python3 -m app.cli validate-database \
    --players "${GAME_ROOT}/DBDAT/JUG98030.FDI" \
    --teams "${GAME_ROOT}/DBDAT/EQ98030.FDI" \
    --coaches "${GAME_ROOT}/DBDAT/ENT98030.FDI" \
    --json > "${SQUAD_DIR}/validate_database.json"
  append_mutation "${RUN_MANIFEST}" "${GAME_ROOT}" "validate_stoke_2015_strategy" "${SQUAD_DIR}/validate_database.json"
fi

if [[ ${SKIP_METADATA} -eq 0 ]]; then
  python3 "${ROOT_DIR}/scripts/stoke_2015_apply_metadata.py" \
    --game-root "${GAME_ROOT}" \
    --output-dir "${METADATA_DIR}"
  append_mutation "${RUN_MANIFEST}" "${GAME_ROOT}" "apply_stoke_2015_metadata" "${METADATA_DIR}/stoke_2015_metadata_apply_result.json"
fi

if [[ ${SKIP_FACES} -eq 0 ]]; then
  python3 "${ROOT_DIR}/scripts/prepare_stoke_2015_face_dbdat.py" \
    --game-root "${GAME_ROOT}" \
    --output-dir "${FACE_DIR}" \
    --apply-to-game-root "${GAME_ROOT}"
  append_mutation "${RUN_MANIFEST}" "${GAME_ROOT}" "apply_stoke_2015_faces" "${FACE_DIR}/prepare_manifest.json"
fi

BUILD_MANIFEST="${RUN_ROOT}/patches/stoke_2015_build_manifest.json"
python3 - "${BUILD_MANIFEST}" "${RUN_ROOT}" "${GAME_ROOT}" "${RUN_MANIFEST}" "${SQUAD_DIR}" "${METADATA_DIR}" "${FACE_DIR}" "${SKIP_SQUAD}" "${SKIP_METADATA}" "${SKIP_FACES}" <<'PY'
from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sys

build_manifest = Path(sys.argv[1]).resolve()
run_root = Path(sys.argv[2]).resolve()
game_root = Path(sys.argv[3]).resolve()
run_manifest = Path(sys.argv[4]).resolve()
squad_dir = Path(sys.argv[5]).resolve()
metadata_dir = Path(sys.argv[6]).resolve()
face_dir = Path(sys.argv[7]).resolve()

payload = {
    "scope": "stoke_2015_isolated_build",
    "timestamp_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "run_root": str(run_root),
    "game_root": str(game_root),
    "run_manifest_path": str(run_manifest),
    "steps": {
        "squad_apply_summary": str(squad_dir / "summary.json"),
        "squad_validate_summary": str(squad_dir / "validate_database.json"),
        "metadata_apply_result": str(metadata_dir / "stoke_2015_metadata_apply_result.json"),
        "face_prepare_manifest": str(face_dir / "prepare_manifest.json"),
    },
    "skip_flags": {
        "squad": bool(int(sys.argv[8])),
        "metadata": bool(int(sys.argv[9])),
        "faces": bool(int(sys.argv[10])),
    },
}
build_manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(payload, indent=2, sort_keys=True))
PY

if [[ ${PRINT_JSON} -eq 1 ]]; then
  python3 - "${RUN_ROOT}" "${GAME_ROOT}" "${RUN_MANIFEST}" "${BUILD_MANIFEST}" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import sys

print(
    json.dumps(
        {
            "success": True,
            "run_root": str(Path(sys.argv[1]).resolve()),
            "game_root": str(Path(sys.argv[2]).resolve()),
            "run_manifest_path": str(Path(sys.argv[3]).resolve()),
            "build_manifest_path": str(Path(sys.argv[4]).resolve()),
        },
        indent=2,
        sort_keys=True,
    )
)
PY
else
  echo "Built Stoke 2015 isolated game:"
  echo "  run_root: ${RUN_ROOT}"
  echo "  game_root: ${GAME_ROOT}"
  echo "  run_manifest: ${RUN_MANIFEST}"
  echo "  build_manifest: ${BUILD_MANIFEST}"
fi
