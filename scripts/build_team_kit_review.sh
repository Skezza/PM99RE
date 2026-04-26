#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_FILE="${ROOT_DIR}/scripts/build_team_kit_review.py"
MANIFEST_FILE="${ROOT_DIR}/work/parallel_recheck/team_kits/kit_manifest.json"
KIT_ARCHIVE="${ROOT_DIR}/DBDAT/MINIESC.PKF"
DAT_ARCHIVE_A="${ROOT_DIR}/FDI-PKF/DAT.PKF"
DAT_ARCHIVE_B="${ROOT_DIR}/DBDAT/DAT.PKF"

if [[ ! -f "${SCRIPT_FILE}" ]]; then
  echo "Script not found at ${SCRIPT_FILE}" >&2
  exit 1
fi

if [[ ! -f "${MANIFEST_FILE}" ]]; then
  echo "Manifest not found at ${MANIFEST_FILE}" >&2
  exit 1
fi

if [[ ! -f "${KIT_ARCHIVE}" ]]; then
  echo "Kit archive not found at ${KIT_ARCHIVE}" >&2
  exit 1
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
output_dir="${ROOT_DIR}/work/team_kit_review_${timestamp}"

if [[ $# -ge 1 && ( "$1" == "-h" || "$1" == "--help" ) ]]; then
  exec python3 "${SCRIPT_FILE}" --help
fi

if [[ $# -ge 1 && "${1#-}" == "$1" ]]; then
  output_dir="$1"
  shift
fi

mkdir -p "${output_dir}"

args=(
  "--manifest-path" "${MANIFEST_FILE}"
  "--kit-archive" "${KIT_ARCHIVE}"
  "--output-dir" "${output_dir}"
)

if [[ -f "${DAT_ARCHIVE_A}" ]]; then
  args+=("--dat-archive" "${DAT_ARCHIVE_A}")
fi
if [[ -f "${DAT_ARCHIVE_B}" ]]; then
  args+=("--dat-archive" "${DAT_ARCHIVE_B}")
fi

echo "Building team kit review into ${output_dir}" >&2

exec python3 "${SCRIPT_FILE}" "${args[@]}" "$@"

