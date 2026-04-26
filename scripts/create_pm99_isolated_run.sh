#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER_COMMON="${ROOT_DIR}/upstream/pm99-runner/scripts/pm99_runner/common.sh"
if [[ -f "${RUNNER_COMMON}" ]]; then
  # shellcheck source=/dev/null
  source "${RUNNER_COMMON}"
fi

DEFAULT_FIXTURE_ROOT="${ROOT_DIR}/work/fixtures/premier-manager-ninety-nine-pristine"
DEFAULT_WORKER_ID="${USER:-worker}"
DEFAULT_RUN_ID="pm99_$(date -u +%Y%m%dT%H%M%SZ)"
DEFAULT_SOURCE_ZIP="${PM99_RUNNER_LOCAL_ZIP:-/home/joe/Downloads/Premier-Manager-Ninety-Nine_Win_EN_Pre-Installed.zip}"
DEFAULT_MFC42_DLL="${PM99_RUNNER_LOCAL_MFC42:-${ROOT_DIR}/.local/iso/Mfc42.dll}"

FIXTURE_ROOT="${DEFAULT_FIXTURE_ROOT}"
WORKER_ID="${DEFAULT_WORKER_ID}"
RUN_ID="${DEFAULT_RUN_ID}"
RUN_ROOT=""
SOURCE_ZIP="${DEFAULT_SOURCE_ZIP}"
MFC42_DLL="${DEFAULT_MFC42_DLL}"
FORCE_FIXTURE_REFRESH=0
PRINT_JSON=0

usage() {
  cat <<EOF
Usage: ./scripts/create_pm99_isolated_run.sh [options]

Create or validate the local pristine PM99 fixture, then materialize a writable
isolated run root under work/pm99/.

Options:
  --worker-id <id>          Worker label (default: ${DEFAULT_WORKER_ID})
  --run-id <id>             Run identifier (default: ${DEFAULT_RUN_ID})
  --run-root <path>         Explicit run root (default: work/pm99/<worker-id>/<run-id>)
  --fixture-root <path>     Pristine fixture root (default: ${DEFAULT_FIXTURE_ROOT})
  --source-zip <path>       PM99 source ZIP (default: ${DEFAULT_SOURCE_ZIP})
  --mfc42-dll <path>        MFC42 runtime DLL (default: ${DEFAULT_MFC42_DLL})
  --force-fixture-refresh   Rebuild the pristine fixture from the ZIP
  --json                    Print a JSON summary after creation
  -h, --help                Show this help
EOF
}

abs_path() {
  python3 - "$1" <<'PY'
from pathlib import Path
import sys

print(Path(sys.argv[1]).expanduser().resolve())
PY
}

write_fixture_manifest() {
  local fixture_root="$1"
  local manifest_path="$2"
  local source_zip="$3"
  local mfc42_dll="$4"

  PYTHONPATH="${ROOT_DIR}/scripts${PYTHONPATH:+:${PYTHONPATH}}" \
    python3 - "${fixture_root}" "${manifest_path}" "${source_zip}" "${mfc42_dll}" <<'PY'
from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sys

from assert_pm99_isolated_input import core_file_hashes, sha256

fixture_root = Path(sys.argv[1]).resolve()
manifest_path = Path(sys.argv[2]).resolve()
source_zip = Path(sys.argv[3]).resolve()
mfc42_dll = Path(sys.argv[4]).resolve()

payload = {
    "scope": "pm99_pristine_fixture",
    "timestamp_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "fixture_root": str(fixture_root),
    "source_zip": {
        "path": str(source_zip),
        "sha256": sha256(source_zip),
        "size": int(source_zip.stat().st_size),
    },
    "mfc42_dll": {
        "path": str(mfc42_dll),
        "sha256": sha256(mfc42_dll),
        "size": int(mfc42_dll.stat().st_size),
    },
    "core_files": core_file_hashes(fixture_root),
}

manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

write_run_manifest() {
  local run_root="$1"
  local game_root="$2"
  local fixture_root="$3"
  local fixture_manifest="$4"
  local worker_id="$5"
  local run_id="$6"

  PYTHONPATH="${ROOT_DIR}/scripts${PYTHONPATH:+:${PYTHONPATH}}" \
    python3 - "${run_root}" "${game_root}" "${fixture_root}" "${fixture_manifest}" "${worker_id}" "${run_id}" <<'PY'
from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sys

from assert_pm99_isolated_input import core_file_hashes, load_manifest

run_root = Path(sys.argv[1]).resolve()
game_root = Path(sys.argv[2]).resolve()
fixture_root = Path(sys.argv[3]).resolve()
fixture_manifest_path = Path(sys.argv[4]).resolve()
worker_id = sys.argv[5]
run_id = sys.argv[6]

payload = {
    "scope": "pm99_isolated_run",
    "timestamp_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "run_id": run_id,
    "worker_id": worker_id,
    "run_root": str(run_root),
    "game_root": str(game_root),
    "artifacts_dir": str((run_root / "artifacts").resolve()),
    "patches_dir": str((run_root / "patches").resolve()),
    "fixture_root": str(fixture_root),
    "fixture_manifest_path": str(fixture_manifest_path),
    "fixture_manifest": load_manifest(fixture_manifest_path),
    "initial_core_files": core_file_hashes(game_root),
    "mutations": [],
}

(run_root / "run_manifest.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --worker-id) WORKER_ID="$2"; shift 2 ;;
    --run-id) RUN_ID="$2"; shift 2 ;;
    --run-root) RUN_ROOT="$2"; shift 2 ;;
    --fixture-root) FIXTURE_ROOT="$2"; shift 2 ;;
    --source-zip) SOURCE_ZIP="$2"; shift 2 ;;
    --mfc42-dll) MFC42_DLL="$2"; shift 2 ;;
    --force-fixture-refresh) FORCE_FIXTURE_REFRESH=1; shift ;;
    --json) PRINT_JSON=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

FIXTURE_ROOT="$(abs_path "${FIXTURE_ROOT}")"
SOURCE_ZIP="$(abs_path "${SOURCE_ZIP}")"
MFC42_DLL="$(abs_path "${MFC42_DLL}")"
if [[ -z "${RUN_ROOT}" ]]; then
  RUN_ROOT="${ROOT_DIR}/work/pm99/${WORKER_ID}/${RUN_ID}"
fi
RUN_ROOT="$(abs_path "${RUN_ROOT}")"
GAME_ROOT="${RUN_ROOT}/game"
FIXTURE_MANIFEST="$(dirname "${FIXTURE_ROOT}")/$(basename "${FIXTURE_ROOT}").manifest.json"

if [[ ! -f "${SOURCE_ZIP}" ]]; then
  echo "Missing PM99 source ZIP: ${SOURCE_ZIP}" >&2
  exit 2
fi
if [[ ! -f "${MFC42_DLL}" ]]; then
  echo "Missing MFC42 runtime DLL: ${MFC42_DLL}" >&2
  exit 2
fi

mkdir -p "$(dirname "${FIXTURE_ROOT}")"

if [[ ${FORCE_FIXTURE_REFRESH} -eq 1 || ! -f "${FIXTURE_ROOT}/MANAGPRE.EXE" ]]; then
  tmp_root="$(mktemp -d "$(dirname "${FIXTURE_ROOT}")/.pm99_fixture_XXXXXX")"
  trap 'rm -rf "${tmp_root}"' EXIT

  unpack_root="${tmp_root}/unpack"
  mkdir -p "${unpack_root}"
  unzip -q "${SOURCE_ZIP}" -d "${unpack_root}"

  inner_dir="$(find "${unpack_root}" -mindepth 1 -maxdepth 1 -type d | head -n 1 || true)"
  if [[ -n "${inner_dir}" && -f "${inner_dir}/MANAGPRE.EXE" ]]; then
    prepared_root="${inner_dir}"
  elif [[ -f "${unpack_root}/MANAGPRE.EXE" ]]; then
    prepared_root="${unpack_root}"
  else
    echo "Could not locate extracted PM99 game root under ${unpack_root}" >&2
    exit 1
  fi

  cp -f "${MFC42_DLL}" "${prepared_root}/MFC42.DLL"

  if [[ -d "${FIXTURE_ROOT}" ]]; then
    chmod -R u+w "${FIXTURE_ROOT}" || true
    rm -rf "${FIXTURE_ROOT}"
  fi
  rm -f "${FIXTURE_MANIFEST}"
  mkdir -p "$(dirname "${FIXTURE_ROOT}")"
  mv "${prepared_root}" "${FIXTURE_ROOT}"
  chmod -R a-w "${FIXTURE_ROOT}"
  write_fixture_manifest "${FIXTURE_ROOT}" "${FIXTURE_MANIFEST}" "${SOURCE_ZIP}" "${MFC42_DLL}"
  chmod a-w "${FIXTURE_MANIFEST}"
fi

python3 "${ROOT_DIR}/scripts/assert_pm99_isolated_input.py" --fixture-root "${FIXTURE_ROOT}" >/dev/null

if [[ -e "${RUN_ROOT}" ]]; then
  echo "Refusing to overwrite existing isolated run root: ${RUN_ROOT}" >&2
  exit 2
fi

mkdir -p "${GAME_ROOT}" "${RUN_ROOT}/artifacts" "${RUN_ROOT}/patches"
if cp -a --reflink=auto "${FIXTURE_ROOT}/." "${GAME_ROOT}/" 2>/dev/null; then
  :
else
  cp -a "${FIXTURE_ROOT}/." "${GAME_ROOT}/"
fi
chmod -R u+w "${GAME_ROOT}"

python3 "${ROOT_DIR}/scripts/assert_pm99_isolated_input.py" --game-root "${GAME_ROOT}" --require-writable >/dev/null
write_run_manifest "${RUN_ROOT}" "${GAME_ROOT}" "${FIXTURE_ROOT}" "${FIXTURE_MANIFEST}" "${WORKER_ID}" "${RUN_ID}"

if [[ ${PRINT_JSON} -eq 1 ]]; then
  python3 - "${RUN_ROOT}" "${GAME_ROOT}" "${FIXTURE_ROOT}" "${FIXTURE_MANIFEST}" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import sys

run_root = Path(sys.argv[1]).resolve()
game_root = Path(sys.argv[2]).resolve()
fixture_root = Path(sys.argv[3]).resolve()
fixture_manifest = Path(sys.argv[4]).resolve()

print(
    json.dumps(
        {
            "success": True,
            "run_root": str(run_root),
            "game_root": str(game_root),
            "fixture_root": str(fixture_root),
            "fixture_manifest_path": str(fixture_manifest),
            "run_manifest_path": str((run_root / "run_manifest.json").resolve()),
        },
        indent=2,
        sort_keys=True,
    )
)
PY
else
  echo "Created isolated PM99 run:"
  echo "  fixture_root: ${FIXTURE_ROOT}"
  echo "  fixture_manifest: ${FIXTURE_MANIFEST}"
  echo "  run_root: ${RUN_ROOT}"
  echo "  game_root: ${GAME_ROOT}"
  echo "  run_manifest: ${RUN_ROOT}/run_manifest.json"
fi
