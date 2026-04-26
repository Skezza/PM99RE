#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EDITOR_DIR="${ROOT_DIR}/upstream/pm99-skezmod-db-editor"

resolve_input() {
  local file_name="$1"
  local preferred="${ROOT_DIR}/DBDAT/${file_name}"
  local fallback="${ROOT_DIR}/FDI-PKF/DBDAT/${file_name}"

  if [[ -f "${preferred}" ]]; then
    printf '%s\n' "${preferred}"
    return 0
  fi
  if [[ -f "${fallback}" ]]; then
    printf '%s\n' "${fallback}"
    return 0
  fi

  echo "Required input not found: ${file_name}" >&2
  echo "Checked:" >&2
  echo "  - ${preferred}" >&2
  echo "  - ${fallback}" >&2
  exit 1
}

if [[ ! -d "${EDITOR_DIR}" ]]; then
  echo "Editor submodule not found at ${EDITOR_DIR}" >&2
  exit 1
fi

if [[ $# -ge 1 && ( "$1" == "-h" || "$1" == "--help" ) ]]; then
  cat <<'EOF'
Usage: ./scripts/export_stadium_metadata.sh [artifact_root]

Runs the upstream full stadium metadata export against frozen local EQ/JUG copies,
then writes:
  - stadium_metadata_full.json
  - summary.json
  - metadata.json

If artifact_root is omitted, a timestamped path under artifacts/research/ is used.
EOF
  exit 0
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
artifact_root="${ROOT_DIR}/artifacts/research/stadium_metadata_${timestamp}"
if [[ $# -ge 1 && "${1#-}" == "$1" ]]; then
  artifact_root="$1"
  shift
fi

eq_source="$(resolve_input "EQ98030.FDI")"
jug_source="$(resolve_input "JUG98030.FDI")"

snapshot_root="${ROOT_DIR}/work/stadium_metadata_inputs_${timestamp}"
mkdir -p "${snapshot_root}" "${artifact_root}"

eq_snapshot="${snapshot_root}/EQ98030.FDI"
jug_snapshot="${snapshot_root}/JUG98030.FDI"
cp -f "${eq_source}" "${eq_snapshot}"
cp -f "${jug_source}" "${jug_snapshot}"

export_json="${artifact_root}/stadium_metadata_full.json"

echo "Exporting full stadium metadata into ${artifact_root}" >&2
python3 \
  "${EDITOR_DIR}/scripts/export_stadium_metadata_full.py" \
  --eq-file "${eq_snapshot}" \
  --jug-file "${jug_snapshot}" \
  --output "${export_json}"

python3 - "${ROOT_DIR}" "${EDITOR_DIR}" "${timestamp}" "${eq_source}" "${jug_source}" "${eq_snapshot}" "${jug_snapshot}" "${export_json}" "${artifact_root}" <<'PY'
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_short_head(repo: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=repo,
        text=True,
    ).strip()


def git_dirty(repo: Path) -> bool:
    return bool(
        subprocess.check_output(
            ["git", "status", "--short"],
            cwd=repo,
            text=True,
        ).strip()
    )


root_dir = Path(sys.argv[1])
editor_dir = Path(sys.argv[2])
timestamp = sys.argv[3]
eq_source = Path(sys.argv[4])
jug_source = Path(sys.argv[5])
eq_snapshot = Path(sys.argv[6])
jug_snapshot = Path(sys.argv[7])
export_json = Path(sys.argv[8])
artifact_root = Path(sys.argv[9])

payload = json.loads(export_json.read_text(encoding="utf-8"))
rows = [row for league in payload.get("leagues", []) for row in league.get("teams", [])]

focus_names = {
    "Manchester Utd.",
    "Stoke C.",
    "F.C. Barcelona",
    "Real Madrid C.F.",
    "Juventus",
}
focus_rows = []
for row in rows:
    name = str(row.get("team_name") or "")
    if name in focus_names:
        focus_rows.append(
            {
                "team_name": name,
                "stadium": row.get("stadium"),
                "seated_capacity": row.get("seated_capacity"),
                "standing_capacity": row.get("standing_capacity"),
                "total_capacity": row.get("total_capacity"),
                "car_park_spaces_default": row.get("car_park_spaces_default"),
                "pitch_quality_default": row.get("pitch_quality_default"),
                "facility_seed_proxy": row.get("facility_seed_proxy"),
            }
        )
focus_rows.sort(key=lambda item: str(item["team_name"]))

summary = {
    "scope": "stadium_metadata_discovery",
    "status": "full_stadium_export_generated",
    "direct_extraction": {
        "team_count": payload.get("team_count"),
        "league_count": payload.get("league_count"),
        "unique_stadium_count": payload.get("unique_stadium_count"),
        "seated_capacity_present_count": payload.get("seated_capacity_present_count"),
        "standing_capacity_present_count": payload.get("standing_capacity_present_count"),
        "standing_capacity_nonzero_count": payload.get("standing_capacity_nonzero_count"),
        "zero_seated_capacity_count": payload.get("zero_seated_capacity_count"),
        "zero_seated_capacity_teams": [
            row.get("team_name") for row in payload.get("zero_seated_capacity_teams", [])
        ],
    },
    "derived_facility_defaults": {
        "facility_seed_present_count": payload.get("facility_seed_present_count"),
        "facility_seed_missing_count": payload.get("facility_seed_missing_count"),
        "car_park_spaces_nonzero_count": payload.get("car_park_spaces_nonzero_count"),
        "pitch_optimum_count": payload.get("pitch_optimum_count"),
        "pitch_normal_count": payload.get("pitch_normal_count"),
    },
    "focus_validation": focus_rows,
    "local_outputs": {
        "artifact_root": str(artifact_root),
        "full_export_json": str(export_json),
    },
    "upstream_implementation": {
        "full_export_script": "upstream/pm99-skezmod-db-editor/scripts/export_stadium_metadata_full.py",
        "capacity_only_export_script": "upstream/pm99-skezmod-db-editor/scripts/export_league_stadium_capacities.py",
        "coverage_tests": "upstream/pm99-skezmod-db-editor/tests/test_export_stadium_metadata_full.py",
    },
}
artifact_root.joinpath("summary.json").write_text(
    json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

metadata = {
    "timestamp_utc": timestamp,
    "pm99re_head": git_short_head(root_dir),
    "upstream_editor_head": git_short_head(editor_dir),
    "upstream_editor_worktree_dirty": git_dirty(editor_dir),
    "inputs": {
        "eq_source_file": {"path": str(eq_source), "sha256": sha256(eq_source)},
        "jug_source_file": {"path": str(jug_source), "sha256": sha256(jug_source)},
        "eq_snapshot_file": {"path": str(eq_snapshot), "sha256": sha256(eq_snapshot)},
        "jug_snapshot_file": {"path": str(jug_snapshot), "sha256": sha256(jug_snapshot)},
    },
    "commands": [
        f"python3 {editor_dir / 'scripts/export_stadium_metadata_full.py'} --eq-file {eq_snapshot} --jug-file {jug_snapshot} --output {export_json}",
        f"{root_dir / 'scripts/export_stadium_metadata.sh'} {artifact_root}",
    ],
    "reviewed_local_outputs": [
        str(export_json),
        str(artifact_root / "summary.json"),
    ],
    "pm99re_wrapper": "scripts/export_stadium_metadata.sh",
}
artifact_root.joinpath("metadata.json").write_text(
    json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
PY

echo "Artifact root: ${artifact_root}" >&2
echo "Full export:   ${export_json}" >&2
