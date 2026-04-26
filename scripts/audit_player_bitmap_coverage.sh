#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EDITOR_DIR="${ROOT_DIR}/upstream/pm99-skezmod-db-editor"

resolve_jug_input() {
  local preferred="${ROOT_DIR}/work/fixtures/premier-manager-ninety-nine-pristine/DBDAT/JUG98030.FDI"
  local repo_local="${ROOT_DIR}/DBDAT/JUG98030.FDI"
  local fallback="${ROOT_DIR}/FDI-PKF/DBDAT/JUG98030.FDI"

  if [[ -f "${preferred}" ]]; then
    printf '%s\n' "${preferred}"
    return 0
  fi
  if [[ -f "${repo_local}" ]]; then
    printf '%s\n' "${repo_local}"
    return 0
  fi
  if [[ -f "${fallback}" ]]; then
    printf '%s\n' "${fallback}"
    return 0
  fi

  echo "Required input not found: JUG98030.FDI" >&2
  echo "Checked:" >&2
  echo "  - ${preferred}" >&2
  echo "  - ${fallback}" >&2
  exit 1
}

resolve_dbasepre_input() {
  local candidates=(
    "${ROOT_DIR}/work/fixtures/premier-manager-ninety-nine-pristine/DBASEPRE.EXE"
    "${ROOT_DIR}/.local/iso/Dbasepre.exe"
    "${ROOT_DIR}/.local/iso/DBASEPRE.EXE"
  )
  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -f "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  printf '\n'
}

if [[ ! -d "${EDITOR_DIR}" ]]; then
  echo "Editor submodule not found at ${EDITOR_DIR}" >&2
  exit 1
fi

if [[ $# -ge 1 && ( "$1" == "-h" || "$1" == "--help" ) ]]; then
  cat <<'EOF'
Usage: ./scripts/audit_player_bitmap_coverage.sh [artifact_root]

Runs a deterministic player-photo coverage audit and writes:
  - summary.json
  - metadata.json
  - DECISION_MEMO.md

If artifact_root is omitted, a timestamped path under artifacts/research/ is used.
EOF
  exit 0
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
artifact_root="${ROOT_DIR}/artifacts/research/player_bitmap_coverage_${timestamp}"
if [[ $# -ge 1 && "${1#-}" == "$1" ]]; then
  artifact_root="$1"
  shift
fi

mkdir -p "${artifact_root}"

jug_source="$(resolve_jug_input)"
dbasepre_source="$(resolve_dbasepre_input)"
summary_json="${artifact_root}/summary.json"

echo "Running player bitmap coverage audit into ${artifact_root}" >&2
if [[ -n "${dbasepre_source}" ]]; then
  python3 \
    "${ROOT_DIR}/scripts/audit_player_bitmap_coverage.py" \
    --jug-file "${jug_source}" \
    --dbasepre-exe "${dbasepre_source}" \
    --include-payload-scan \
    --output "${summary_json}"
else
  python3 \
    "${ROOT_DIR}/scripts/audit_player_bitmap_coverage.py" \
    --jug-file "${jug_source}" \
    --include-payload-scan \
    --output "${summary_json}"
fi

python3 - "${ROOT_DIR}" "${EDITOR_DIR}" "${artifact_root}" "${timestamp}" "${jug_source}" "${dbasepre_source}" "${summary_json}" <<'PY'
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
artifact_root = Path(sys.argv[3])
timestamp = sys.argv[4]
jug_source = Path(sys.argv[5])
dbasepre_source = Path(sys.argv[6]) if sys.argv[6] else None
summary_json = Path(sys.argv[7])

summary = json.loads(summary_json.read_text(encoding="utf-8"))
coverage = dict(summary.get("coverage", {}) or {})
archive_scan = dict((summary.get("archive_provenance", {}) or {}).get("j96_archive_scan", {}))
payload_scan = dict(summary.get("payload_embedded_image_scan", {}) or {})

metadata = {
    "timestamp_utc": timestamp,
    "pm99re_head": git_short_head(root_dir),
    "upstream_editor_head": git_short_head(editor_dir),
    "upstream_editor_worktree_dirty": git_dirty(editor_dir),
    "inputs": {
        "jug_source_file": {"path": str(jug_source), "sha256": sha256(jug_source)},
        "dbasepre_source_file": (
            {"path": str(dbasepre_source), "sha256": sha256(dbasepre_source)}
            if dbasepre_source is not None and dbasepre_source.exists()
            else None
        ),
    },
    "commands": [
        (
            f"python3 {root_dir / 'scripts/audit_player_bitmap_coverage.py'} "
            f"--jug-file {jug_source} "
            f"{('--dbasepre-exe ' + str(dbasepre_source) + ' ') if dbasepre_source else ''}"
            f"--include-payload-scan --output {summary_json}"
        ),
        f"{root_dir / 'scripts/audit_player_bitmap_coverage.sh'} {artifact_root}",
    ],
    "reviewed_outputs": [str(summary_json)],
    "wrapper_script": "scripts/audit_player_bitmap_coverage.sh",
    "core_result": {
        "jug_players": coverage.get("jug_players"),
        "combined_unique_photo_ids": coverage.get("combined_unique_photo_ids"),
        "players_without_any_photo_in_jug": coverage.get("players_without_any_photo_in_jug"),
        "coverage_combined_pct": coverage.get("coverage_combined_pct"),
        "source_family_counts": archive_scan.get("source_family_counts"),
        "payload_total_validated_images": payload_scan.get("total_validated_images", 0),
    },
}
artifact_root.joinpath("metadata.json").write_text(
    json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

memo = f"""# Player Bitmap Coverage Decision Memo ({timestamp})

## Scope

Audit and freeze evidence for player bitmap coverage in the local PM99 corpus.

Artifact root:
`{artifact_root}`

## Decision

- Treat missing player portraits in the current corpus as absent source data, not extraction failure.
- Keep this as a reproducible audit in PM99RE and promote the logic to upstream editor tooling when needed.

## Core Findings

- Indexed player records in JUG: `{coverage.get('jug_players')}`
- Unique player IDs in `MINIFOTO`: `{coverage.get('minifoto_unique_ids')}`
- Unique player IDs in `BIGFOTO`: `{coverage.get('bigfoto_unique_ids')}`
- Combined unique player IDs with any static photo: `{coverage.get('combined_unique_photo_ids')}`
- Players without any static photo in JUG: `{coverage.get('players_without_any_photo_in_jug')}`
- Combined static photo coverage: `{coverage.get('coverage_combined_pct')}%`
- J96 archive source families detected: `{archive_scan.get('source_family_counts')}`
- Embedded validated images in JUG payload scan: `{payload_scan.get('total_validated_images', 0)}`

## Repro

```bash
./scripts/audit_player_bitmap_coverage.sh
```

## Upstream Promotion Targets

- `upstream/pm99-skezmod-db-editor/app/minifoto_bitmap_archive.py`
- `upstream/pm99-skezmod-db-editor/app/fdi_indexed.py`
- `upstream/pm99-skezmod-db-editor/app/player_bitmap_discovery.py`

## Commit Policy

Keep outputs as compact JSON/memo evidence only. Do not commit extracted image binaries.
"""
artifact_root.joinpath("DECISION_MEMO.md").write_text(memo, encoding="utf-8")
PY

echo "Artifact root: ${artifact_root}" >&2
echo "Summary:       ${summary_json}" >&2
