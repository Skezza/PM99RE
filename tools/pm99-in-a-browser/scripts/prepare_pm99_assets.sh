#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${ROOT}/../.." && pwd)"

SOURCE="${REPO_ROOT}/work/fixtures/premier-manager-ninety-nine-pristine"
MODE="symlink"
MAKE_ZIP=1
MAKE_ISO=1

usage() {
  cat <<'USAGE'
Usage: scripts/prepare_pm99_assets.sh [options]

Stage local PM99 files into ignored pm99-in-a-browser/assets/.

Options:
  --source <path>    PM99 source fixture/root
  --mode <mode>      symlink or copy (default: symlink)
  --no-zip           Skip assets/pm99.zip
  --no-iso           Skip assets/pm99.iso
  -h, --help         Show help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source) SOURCE="$2"; shift 2 ;;
    --mode) MODE="$2"; shift 2 ;;
    --no-zip) MAKE_ZIP=0; shift ;;
    --no-iso) MAKE_ISO=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

SOURCE="$(cd "${SOURCE}" && pwd)"
ASSETS="${ROOT}/assets"
PM99_ASSET="${ASSETS}/pm99"

for rel in MANAGPRE.EXE MIDAS11.DLL DBDAT/JUG98030.FDI DBDAT/EQ98030.FDI DBDAT/ENT98030.FDI DBDAT/MINIFOTO.PKF; do
  if [[ ! -f "${SOURCE}/${rel}" ]]; then
    echo "Missing required PM99 file: ${SOURCE}/${rel}" >&2
    exit 1
  fi
done

mkdir -p "${ASSETS}"

case "${MODE}" in
  symlink)
    rm -rf "${PM99_ASSET}"
    ln -s "${SOURCE}" "${PM99_ASSET}"
    ;;
  copy)
    mkdir -p "${PM99_ASSET}"
    if command -v rsync >/dev/null 2>&1; then
      rsync -a --delete "${SOURCE}/" "${PM99_ASSET}/"
    else
      rm -rf "${PM99_ASSET}"
      cp -a "${SOURCE}" "${PM99_ASSET}"
    fi
    ;;
  *)
    echo "--mode must be symlink or copy" >&2
    exit 2
    ;;
esac

python3 "${SCRIPT_DIR}/validate_assets.py" \
  --pm99-root "${PM99_ASSET}" \
  --write-manifest "${ASSETS}/pm99-manifest.json" >/dev/null

if [[ "${MAKE_ZIP}" -eq 1 ]]; then
  if command -v zip >/dev/null 2>&1; then
    rm -f "${ASSETS}/pm99.zip"
    (
      cd "${SOURCE}"
      zip -qr "${ASSETS}/pm99.zip" .
    )
    mkdir -p "${ROOT}/boxedwine/assets/apps"
    ln -sf "../../../assets/pm99.zip" "${ROOT}/boxedwine/assets/apps/pm99-app.zip"
    echo "Wrote ${ASSETS}/pm99.zip"
  else
    echo "zip not installed; skipped ${ASSETS}/pm99.zip" >&2
  fi
fi

if [[ "${MAKE_ISO}" -eq 1 ]]; then
  rm -f "${ASSETS}/pm99.iso"
  if command -v genisoimage >/dev/null 2>&1; then
    genisoimage -quiet -J -r -o "${ASSETS}/pm99.iso" "${SOURCE}"
    mkdir -p "${ROOT}/v86/assets/media"
    ln -sf "../../../assets/pm99.iso" "${ROOT}/v86/assets/media/pm99.iso"
    echo "Wrote ${ASSETS}/pm99.iso"
  elif command -v mkisofs >/dev/null 2>&1; then
    mkisofs -quiet -J -r -o "${ASSETS}/pm99.iso" "${SOURCE}"
    mkdir -p "${ROOT}/v86/assets/media"
    ln -sf "../../../assets/pm99.iso" "${ROOT}/v86/assets/media/pm99.iso"
    echo "Wrote ${ASSETS}/pm99.iso"
  elif command -v xorriso >/dev/null 2>&1; then
    xorriso -as mkisofs -quiet -J -r -o "${ASSETS}/pm99.iso" "${SOURCE}"
    mkdir -p "${ROOT}/v86/assets/media"
    ln -sf "../../../assets/pm99.iso" "${ROOT}/v86/assets/media/pm99.iso"
    echo "Wrote ${ASSETS}/pm99.iso"
  else
    echo "No genisoimage, mkisofs, or xorriso found; skipped ${ASSETS}/pm99.iso" >&2
  fi
fi

echo "Wrote ${ASSETS}/pm99-manifest.json"
echo "PM99 asset root: ${PM99_ASSET}"
