#!/usr/bin/env bash
set -euo pipefail

PM9X_REMOTE="${PM9X_REMOTE:-192.168.1.175}"
PM9X_REMOTE_ROOT="${PM9X_REMOTE_ROOT:-/home/joe/pm9x-lab}"
PM9X_REMOTE_PORT="${PM9X_REMOTE_PORT:-8080}"
PM9X_LOCAL_PORT="${PM9X_LOCAL_PORT:-18080}"
PM9X_GHIDRA_VERSION="${PM9X_GHIDRA_VERSION:-12.0.3}"
PM9X_GHIDRA_RELEASE_DATE="${PM9X_GHIDRA_RELEASE_DATE:-20260210}"
PM9X_GHIDRAMCP_VERSION="${PM9X_GHIDRAMCP_VERSION:-0.6.2}"
PM9X_DISPLAY="${PM9X_DISPLAY:-73}"
PM9X_ANALYSIS_TIMEOUT_PER_FILE="${PM9X_ANALYSIS_TIMEOUT_PER_FILE:-900}"
PM9X_ANALYSIS_MAX_CPU="${PM9X_ANALYSIS_MAX_CPU:-4}"

PM9X_PM97_SOURCE="${PM9X_PM97_SOURCE:-/home/joe/pm9x-research/extracted/Premier-Manager-97_Win_EN_RIP-Version/Premier_Manager_97}"
PM9X_PM98_SOURCE="${PM9X_PM98_SOURCE:-/home/joe/pm9x-research/extracted/Premier-Manager-98_Win_EN/iso_contents}"
PM9X_PM99_SOURCE="${PM9X_PM99_SOURCE:-/home/joe/Downloads/Premier-Manager-Ninety-Nine_Win_EN_Pre-Installed/premier-manager-ninety-nine}"
PM9X_GHIDRA_ZIP="${PM9X_GHIDRA_ZIP:-/home/joe/GhidraMCP/.cache/ghidra_${PM9X_GHIDRA_VERSION}_PUBLIC_${PM9X_GHIDRA_RELEASE_DATE}.zip}"
PM9X_GHIDRAMCP_ZIP="${PM9X_GHIDRAMCP_ZIP:-/home/joe/GhidraMCP/target/GhidraMCP-${PM9X_GHIDRAMCP_VERSION}.zip}"

pm9x_remote_ghidra_dir() {
  printf '%s/ghidra/ghidra_%s_PUBLIC' "${PM9X_REMOTE_ROOT}" "${PM9X_GHIDRA_VERSION}"
}

pm9x_ssh() {
  ssh -o BatchMode=yes "${PM9X_REMOTE}" "$@"
}

pm9x_scp_to_remote() {
  scp -q "$1" "${PM9X_REMOTE}:$2"
}

pm9x_require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 127
  }
}

pm9x_require_local_dir() {
  [[ -d "$1" ]] || {
    echo "Missing local directory: $1" >&2
    exit 1
  }
}

pm9x_require_local_file() {
  [[ -f "$1" ]] || {
    echo "Missing local file: $1" >&2
    exit 1
  }
}

pm9x_print_config() {
  cat <<EOF
PM9X tiny-m73 configuration:
  remote: ${PM9X_REMOTE}
  remote root: ${PM9X_REMOTE_ROOT}
  Ghidra: ${PM9X_GHIDRA_VERSION} (${PM9X_GHIDRA_RELEASE_DATE})
  GhidraMCP: ${PM9X_GHIDRAMCP_VERSION}
  remote MCP: 127.0.0.1:${PM9X_REMOTE_PORT}
  local tunnel: 127.0.0.1:${PM9X_LOCAL_PORT}
  PM97 source: ${PM9X_PM97_SOURCE}
  PM98 source: ${PM9X_PM98_SOURCE}
  PM99 source: ${PM9X_PM99_SOURCE}
EOF
}
