#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/tiny_m73_pm9x_common.sh"

pm9x_require_cmd ssh
pm9x_require_cmd scp
pm9x_require_local_file "${PM9X_GHIDRA_ZIP}"
pm9x_require_local_file "${PM9X_GHIDRAMCP_ZIP}"

pm9x_print_config

remote_cache="${PM9X_REMOTE_ROOT}/cache"
remote_ghidra_zip="${remote_cache}/$(basename "${PM9X_GHIDRA_ZIP}")"
remote_ghidramcp_zip="${remote_cache}/$(basename "${PM9X_GHIDRAMCP_ZIP}")"
remote_ghidra_dir="$(pm9x_remote_ghidra_dir)"

pm9x_ssh "set -euo pipefail
missing=0
for pkg in openjdk-21-jdk xvfb unzip rsync python3; do
  dpkg -s \"\$pkg\" >/dev/null 2>&1 || missing=1
done
if [[ \$missing -eq 1 ]]; then
  sudo -n apt-get update
  sudo -n apt-get install -y openjdk-21-jdk xvfb unzip rsync python3
fi
mkdir -p '${remote_cache}' '${PM9X_REMOTE_ROOT}/ghidra' '${PM9X_REMOTE_ROOT}/logs'"

pm9x_scp_to_remote "${PM9X_GHIDRA_ZIP}" "${remote_ghidra_zip}"
pm9x_scp_to_remote "${PM9X_GHIDRAMCP_ZIP}" "${remote_ghidramcp_zip}"

pm9x_ssh "set -euo pipefail
systemctl --user stop pm9x-ghidramcp.service >/dev/null 2>&1 || true
if [[ ! -x '${remote_ghidra_dir}/ghidraRun' ]]; then
  rm -rf '${remote_ghidra_dir}'
  unzip -q '${remote_ghidra_zip}' -d '${PM9X_REMOTE_ROOT}/ghidra'
fi
rm -rf '${remote_ghidra_dir}/Ghidra/Extensions/GhidraMCP'
unzip -q '${remote_ghidramcp_zip}' -d '${remote_ghidra_dir}/Ghidra/Extensions'
JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 '${remote_ghidra_dir}/support/analyzeHeadless' 2>&1 | sed -n '1,8p' || true
java -version 2>&1 | sed -n '1,3p'
test -d '${remote_ghidra_dir}/Ghidra/Extensions/GhidraMCP'
echo 'Installed Ghidra at ${remote_ghidra_dir}'
echo 'Installed GhidraMCP extension at ${remote_ghidra_dir}/Ghidra/Extensions/GhidraMCP'"
