#!/usr/bin/env python3
"""Build a PM99 runtime-safe copy of a 2025 slot assignment.

The editor/parser can round-trip longer display names than MANAGPRE.EXE accepts
when starting a new game. This helper keeps the source identity fields intact and
adds PM99-safe display aliases to the assignment rows used for DB writes.
"""

from __future__ import annotations

import argparse
import json
import unicodedata
from pathlib import Path
from typing import Any


MONONYM_ALIASES = {
    "Andre Player": "Andre Trindade",
    "Beto Player": "Beto Betuncal",
    "Casemiro Player": "Carlos Casemiro",
    "Evanilson Player": "Evanilson Lima",
    "Joelinton Player": "Joelinton Cassio",
    "Kevin Player": "Kevin Santos",
    "Morato Player": "Felipe Morato",
    "Murillo Player": "Murillo Costa",
    "Pablo Player": "Pablo Fornals",
    "Raphael Player": "Raphael Borges",
    "Reinildo Player": "Reinildo Mandava",
    "Richarlison Player": "Richarlison Andrade",
    "Rodri Player": "Rodri Hernandez",
}


def _ascii(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _fit_bytes(value: str, limit: int) -> str:
    out = ""
    for ch in str(value or ""):
        trial = out + ch
        if len(trial.encode("cp1252", errors="replace")) > limit:
            break
        out = trial
    return out.strip(" -'") or "X"


def runtime_safe_name(name: str) -> str:
    original = " ".join(_ascii(name).replace(".", "").split()).strip()
    if not original:
        return "Unknown Player"
    if original in MONONYM_ALIASES:
        original = MONONYM_ALIASES[original]

    parts = original.split()
    if len(parts) == 1:
        given, surname = parts[0], "Player"
    elif len(parts) == 2:
        given, surname = parts
    else:
        # MANAGPRE stores two display parts. Keep the first and last tokens as
        # the stable in-game identity and drop middle particles/secondary names.
        given, surname = parts[0], parts[-1]
        if "-" in surname:
            surname = surname.split("-")[-1]

    given = given.replace("-", "")
    if len(given.encode("cp1252", errors="replace")) > 12:
        # Preserve recognisable prefixes for common hyphenated long given names.
        given = _fit_bytes(given, 12)
    if len(surname.encode("cp1252", errors="replace")) > 12:
        if "-" in surname:
            last_hyphen_part = surname.split("-")[-1].strip()
            if last_hyphen_part and len(last_hyphen_part.encode("cp1252", errors="replace")) <= 12:
                surname = last_hyphen_part
            else:
                surname = surname.replace("-", "")
        surname = _fit_bytes(surname, 12)
    given = _fit_bytes(given, 12)
    display = f"{given} {surname}".strip()
    if len(display.encode("cp1252", errors="replace")) <= 12:
        return display

    # MANAGPRE's Current Squad table filters otherwise parser-valid linked
    # players when the full display token is too wide. Use an initial plus the
    # stable surname so the table still shows the recognisable player identity.
    initial = _fit_bytes(given[:1], 1)
    initial_display = f"{initial} {surname}".strip()
    if len(initial_display.encode("cp1252", errors="replace")) <= 12:
        return initial_display
    surname = _fit_bytes(surname.replace("-", ""), 10)
    return f"{initial} {surname}".strip()


def _patch_name_row(row: dict[str, Any], changes: list[dict[str, Any]], *, club_key: str, source: str) -> None:
    old_name = str(row.get("applied_name") or row.get("target_name") or "").strip()
    if not old_name:
        return
    safe = runtime_safe_name(old_name)
    if safe != old_name:
        row["source_target_name"] = old_name
        row["target_name"] = safe
        row["applied_name"] = safe
        changes.append(
            {
                "club_key": club_key,
                "source": source,
                "slot": int(row.get("slot") or 0),
                "record_id": int(row.get("record_id") or 0),
                "old_name": old_name,
                "runtime_safe_name": safe,
            }
        )


def build_runtime_safe_assignment(input_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{input_path} must contain a JSON object")
    changes: list[dict[str, Any]] = []
    for assignment in list(payload.get("assignments") or []):
        if not isinstance(assignment, dict):
            continue
        club_key = str(assignment.get("target_club_key") or assignment.get("club_key") or "")
        for row in list(assignment.get("roster") or []):
            if isinstance(row, dict):
                _patch_name_row(row, changes, club_key=club_key, source="assigned")
        safe_skipped: list[str] = []
        source_skipped: list[str] = []
        for name in list(assignment.get("skipped_target_names") or []):
            old_name = str(name or "").strip()
            if not old_name:
                continue
            safe = runtime_safe_name(old_name)
            safe_skipped.append(safe)
            source_skipped.append(old_name)
            if safe != old_name:
                changes.append(
                    {
                        "club_key": club_key,
                        "source": "skipped",
                        "slot": 0,
                        "record_id": 0,
                        "old_name": old_name,
                        "runtime_safe_name": safe,
                    }
                )
        if source_skipped:
            assignment["source_skipped_target_names"] = source_skipped
            assignment["skipped_target_names"] = safe_skipped
    payload["runtime_safe_name_policy"] = {
        "schema": "pm99-runtime-safe-name-policy-v1",
        "given_max_bytes": 12,
        "surname_max_bytes": 12,
        "current_squad_display_max_bytes": 12,
        "middle_tokens": "dropped",
        "mononym_alias_count": len(MONONYM_ALIASES),
    }
    return payload, changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    output, changes = build_runtime_safe_assignment(Path(args.input).expanduser().resolve())
    output_path = Path(args.output).expanduser().resolve()
    report_path = Path(args.report).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = {
        "schema": "pm99-runtime-safe-assignment-report-v1",
        "input": str(Path(args.input).expanduser().resolve()),
        "output": str(output_path),
        "change_count": len(changes),
        "changes": changes,
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"change_count": len(changes), "output": str(output_path)}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
