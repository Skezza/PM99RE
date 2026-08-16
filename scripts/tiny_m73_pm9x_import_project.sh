#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/tiny_m73_pm9x_common.sh"

remote_ghidra_dir="$(pm9x_remote_ghidra_dir)"
remote_project_dir="${PM9X_REMOTE_ROOT}/ghidra-projects"
remote_log_dir="${PM9X_REMOTE_ROOT}/logs"

pm9x_require_cmd ssh
pm9x_print_config

pm9x_ssh "set -euo pipefail
systemctl --user stop pm9x-ghidramcp.service >/dev/null 2>&1 || true
mkdir -p '${remote_project_dir}' '${remote_log_dir}'
test -x '${remote_ghidra_dir}/support/analyzeHeadless'
for f in \
  '${PM9X_REMOTE_ROOT}/assets/pristine/pm97/PM97.EXE' \
  '${PM9X_REMOTE_ROOT}/assets/pristine/pm97/MANAGER.EXE' \
  '${PM9X_REMOTE_ROOT}/assets/pristine/pm97/DBASEWIN.EXE' \
  '${PM9X_REMOTE_ROOT}/assets/pristine/pm98/PM98.EXE' \
  '${PM9X_REMOTE_ROOT}/assets/pristine/pm98/MANAGER.EXE' \
  '${PM9X_REMOTE_ROOT}/assets/pristine/pm98/Dbasewin.exe' \
  '${PM9X_REMOTE_ROOT}/assets/pristine/pm99/PM99.EXE' \
  '${PM9X_REMOTE_ROOT}/assets/pristine/pm99/MANAGPRE.EXE' \
  '${PM9X_REMOTE_ROOT}/assets/pristine/pm99/DBASEPRE.EXE'; do
  test -f \"\$f\" || { echo \"Missing remote binary: \$f\" >&2; exit 1; }
done

JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 '${remote_ghidra_dir}/support/analyzeHeadless' '${remote_project_dir}' PM9X/PM97 \
  -import '${PM9X_REMOTE_ROOT}/assets/pristine/pm97/PM97.EXE' \
  -import '${PM9X_REMOTE_ROOT}/assets/pristine/pm97/MANAGER.EXE' \
  -import '${PM9X_REMOTE_ROOT}/assets/pristine/pm97/DBASEWIN.EXE' \
  -overwrite -analysisTimeoutPerFile '${PM9X_ANALYSIS_TIMEOUT_PER_FILE}' -max-cpu '${PM9X_ANALYSIS_MAX_CPU}' \
  -log '${remote_log_dir}/analyzeHeadless-pm97.log'

JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 '${remote_ghidra_dir}/support/analyzeHeadless' '${remote_project_dir}' PM9X/PM98 \
  -import '${PM9X_REMOTE_ROOT}/assets/pristine/pm98/PM98.EXE' \
  -import '${PM9X_REMOTE_ROOT}/assets/pristine/pm98/MANAGER.EXE' \
  -import '${PM9X_REMOTE_ROOT}/assets/pristine/pm98/Dbasewin.exe' \
  -overwrite -analysisTimeoutPerFile '${PM9X_ANALYSIS_TIMEOUT_PER_FILE}' -max-cpu '${PM9X_ANALYSIS_MAX_CPU}' \
  -log '${remote_log_dir}/analyzeHeadless-pm98.log'

pm99_imports=(
  -import '${PM9X_REMOTE_ROOT}/assets/pristine/pm99/PM99.EXE'
  -import '${PM9X_REMOTE_ROOT}/assets/pristine/pm99/MANAGPRE.EXE'
  -import '${PM9X_REMOTE_ROOT}/assets/pristine/pm99/DBASEPRE.EXE'
)
if [[ -f '${PM9X_REMOTE_ROOT}/assets/pristine/pm99/MIDAS11.DLL' ]]; then
  pm99_imports+=( -import '${PM9X_REMOTE_ROOT}/assets/pristine/pm99/MIDAS11.DLL' )
fi

JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 '${remote_ghidra_dir}/support/analyzeHeadless' '${remote_project_dir}' PM9X/PM99 \
  \"\${pm99_imports[@]}\" \
  -overwrite -analysisTimeoutPerFile '${PM9X_ANALYSIS_TIMEOUT_PER_FILE}' -max-cpu '${PM9X_ANALYSIS_MAX_CPU}' \
  -log '${remote_log_dir}/analyzeHeadless-pm99.log'

test -f '${remote_project_dir}/PM9X.gpr'
echo 'Imported PM9X project at ${remote_project_dir}/PM9X.gpr'"
