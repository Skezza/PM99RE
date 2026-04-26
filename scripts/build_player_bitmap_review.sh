#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EDITOR_DIR="${ROOT_DIR}/upstream/pm99-skezmod-db-editor"
ARCHIVE_FILE="${ROOT_DIR}/FDI-PKF/DBDAT/MINIFOTO.PKF"
PLAYER_FILE="${ROOT_DIR}/FDI-PKF/DBDAT/JUG98030.FDI"

if [[ ! -d "${EDITOR_DIR}" ]]; then
  echo "Editor submodule not found at ${EDITOR_DIR}" >&2
  exit 1
fi

if [[ ! -f "${ARCHIVE_FILE}" ]]; then
  echo "Archive not found at ${ARCHIVE_FILE}" >&2
  exit 1
fi

if [[ ! -f "${PLAYER_FILE}" ]]; then
  echo "Player file not found at ${PLAYER_FILE}" >&2
  exit 1
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
output_dir="${ROOT_DIR}/work/player_bitmap_review_${timestamp}"

if [[ $# -ge 1 && ( "$1" == "-h" || "$1" == "--help" ) ]]; then
  exec python3 "${EDITOR_DIR}/scripts/build_player_bitmap_review.py" --help
fi

if [[ $# -ge 1 && "${1#-}" == "$1" ]]; then
  output_dir="$1"
  shift
fi

mkdir -p "${output_dir}"

echo "Building player bitmap review into ${output_dir}" >&2

exec python3 \
  "${EDITOR_DIR}/scripts/build_player_bitmap_review.py" \
  "${ARCHIVE_FILE}" \
  "${PLAYER_FILE}" \
  "${output_dir}" \
  "$@"
