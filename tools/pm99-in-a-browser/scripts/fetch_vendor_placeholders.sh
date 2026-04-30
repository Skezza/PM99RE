#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

mkdir -p "${ROOT}/vendor/v86" "${ROOT}/vendor/boxedwine"

cat <<'MSG'
Created local vendor directories:

  vendor/v86/
  vendor/boxedwine/

Add your local emulator builds there. This script intentionally does not
download vendor code because v86 and BoxedWine build artifacts should be
chosen, licensed, and pinned explicitly for the experiment.

Expected:
  vendor/v86/libv86.js
  vendor/v86/v86.wasm
  vendor/boxedwine/boxedwine.js
  vendor/boxedwine/boxedwine.wasm
MSG
