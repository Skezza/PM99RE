#!/usr/bin/env python3
"""Apply calibrated Stoke 2015 player metadata (DOB/nationality/height/weight).

This script builds a parser-backed batch-edit CSV for the active Stoke roster slots,
applies it through the upstream editor CLI, and writes evidence artifacts.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
EDITOR_ROOT = REPO_ROOT / "upstream" / "pm99-skezmod-db-editor"
if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from assert_pm99_isolated_input import resolve_game_root, sha256  # noqa: E402
from app.fdi_indexed import IndexedFDIFile  # noqa: E402
from app.models import PlayerRecord  # noqa: E402
from app.eq_jug_linked import load_eq_linked_team_rosters  # noqa: E402


STOKE_SLOT_NAMES: list[str] = [
    "Jack Butland",
    "Phil Bardsley",
    "Erik Pieters",
    "Marc Muniesa",
    "Glenn Whelan",
    "Stephen Ireland",
    "Glen Johnson",
    "Peter Odemwingie",
    "Marko Arnautovic",
    "Joselu Mato",
    "Marc Wilson",
    "Ibrahim Afellay",
    "Marco van Ginkel",
    "Charlie Adam",
    "Ryan Shawcross",
    "Mame Diouf",
    "Jonathan Walters",
    "Geoff Cameron",
    "Giannelli Imbula",
    "Steve Sidwell",
]


@dataclass(frozen=True)
class PlayerSource:
    name: str
    qid: str
    nationality_label: str
    sidwell_archive_weight_kg: int | None = None


PLAYER_SOURCES: list[PlayerSource] = [
    PlayerSource("Jack Butland", "Q313089", "ENGLAND"),
    PlayerSource("Phil Bardsley", "Q69965", "SCOTLAND"),
    PlayerSource("Erik Pieters", "Q258730", "HOLLAND"),
    PlayerSource("Marc Muniesa", "Q313111", "SPAIN"),
    PlayerSource("Glenn Whelan", "Q316698", "IRELAND"),
    PlayerSource("Stephen Ireland", "Q113916", "IRELAND"),
    PlayerSource("Glen Johnson", "Q185208", "ENGLAND"),
    PlayerSource("Peter Odemwingie", "Q311329", "NIGERIA"),
    PlayerSource("Marko Arnautovic", "Q313575", "AUSTRIA"),
    PlayerSource("Joselu Mato", "Q134729", "SPAIN"),
    PlayerSource("Marc Wilson", "Q772917", "IRELAND"),
    PlayerSource("Ibrahim Afellay", "Q165014", "HOLLAND"),
    PlayerSource("Marco van Ginkel", "Q648671", "HOLLAND"),
    PlayerSource("Charlie Adam", "Q311353", "SCOTLAND"),
    PlayerSource("Ryan Shawcross", "Q247462", "ENGLAND"),
    PlayerSource("Mame Diouf", "Q19051", "SENEGAL"),
    PlayerSource("Jonathan Walters", "Q319810", "IRELAND"),
    PlayerSource("Geoff Cameron", "Q1362010", "UNITED STATES"),
    PlayerSource("Giannelli Imbula", "Q14565887", "FRANCE"),
    PlayerSource("Steve Sidwell", "Q275710", "ENGLAND", sidwell_archive_weight_kg=70),
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply calibrated Stoke 2015 metadata via player-batch-edit")
    parser.add_argument(
        "--game-root",
        "--game-dir",
        dest="game_root",
        default="",
        help="Writable isolated PM99 game root containing DBDAT/. Dry runs may omit this to read from the pristine fixture.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "artifacts" / f"stoke_2015_metadata_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"),
        help="Artifact output directory",
    )
    parser.add_argument(
        "--team-query",
        default="Stoke",
        help="Team lookup query used for EQ->JUG linked roster resolution",
    )
    parser.add_argument(
        "--year-shift",
        type=int,
        default=17,
        help="Calibration shift: calibrated_birth_year = real_birth_year - year_shift (default: 17)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate artifacts and CSV only (do not apply writes)",
    )
    return parser.parse_args()


def _api_get(session: requests.Session, *, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    response = session.get(endpoint, params=params, timeout=45)
    response.raise_for_status()
    return response.json()


def _extract_nationality_codes(textos_pkf: Path) -> dict[str, int]:
    xor_bytes = bytes(b ^ 0x61 for b in textos_pkf.read_bytes())
    pos = xor_bytes.find(b"GERMANY")
    if pos < 0:
        raise RuntimeError("Could not find English country table anchor (GERMANY) in XOR-decoded TEXTOS.PKF")

    probe = xor_bytes[max(0, pos - 200) : pos + 12000]
    printable = "".join(chr(c) if 32 <= c < 127 else " " for c in probe)
    printable = re.sub(r"\s+", " ", printable)
    raw_tokens = re.findall(r"[A-Z][A-Z .'\-/]{1,}", printable)
    tokens: list[str] = []
    for token in raw_tokens:
        cleaned = token.strip(" .-")
        if len(cleaned) < 2:
            continue
        if tokens and tokens[-1] == cleaned:
            continue
        tokens.append(cleaned)

    start_index = None
    for i, token in enumerate(tokens):
        if token in {"XXX", "XXXX"} and i + 1 < len(tokens) and tokens[i + 1] == "ALBANIA":
            start_index = i
            break
    if start_index is None:
        raise RuntimeError("Could not isolate start of English country table in TEXTOS.PKF")

    end_index = None
    for i in range(start_index, len(tokens)):
        if tokens[i] == "VANUATU":
            end_index = i
            break
    if end_index is None:
        raise RuntimeError("Could not isolate end of English country table in TEXTOS.PKF")

    country_tokens = tokens[start_index : end_index + 1]
    return {country: index for index, country in enumerate(country_tokens)}


def _parse_wikidata_time(iso_time: str) -> tuple[int, int, int]:
    # Example: +1993-03-10T00:00:00Z
    match = re.match(r"^[+](\d{4})-(\d{2})-(\d{2})T", iso_time or "")
    if not match:
        raise ValueError(f"Unsupported Wikidata date format: {iso_time!r}")
    year, month, day = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return year, month, day


def _wikidata_height_to_cm(value: dict[str, Any], *, player_name: str, qid: str) -> int:
    amount = value.get("amount")
    unit = value.get("unit")
    if not isinstance(amount, str):
        raise RuntimeError(f"Invalid P2048 amount payload for {player_name} ({qid})")

    numeric = float(amount)
    if not isinstance(unit, str):
        unit = ""

    # Q174728 = centimetre, Q11573 = metre.
    if unit.endswith("/Q174728"):
        height_cm = int(round(numeric))
    elif unit.endswith("/Q11573"):
        height_cm = int(round(numeric * 100.0))
    elif unit == "1":
        # Unitless values are interpreted by magnitude.
        height_cm = int(round(numeric * 100.0 if abs(numeric) <= 3.0 else numeric))
    else:
        # Fallback for unknown units: infer by magnitude to keep pipeline resilient.
        height_cm = int(round(numeric * 100.0 if abs(numeric) <= 3.0 else numeric))

    if height_cm <= 0 or height_cm > 260:
        raise RuntimeError(f"Parsed height out of range for {player_name} ({qid}): {height_cm} cm")
    return height_cm


def _fetch_sidwell_archive_weight(session: requests.Session) -> int:
    url = (
        "https://web.archive.org/web/20140822121738/"
        "http://www.premierleague.com/en-gb/players/profile.html/steve-sidwell"
    )
    response = session.get(url, timeout=45)
    response.raise_for_status()
    html = response.text
    match = re.search(r"Weight</td>\s*<td class=\"normal\">(\d+)\s*kg</td>", html, re.IGNORECASE)
    if not match:
        raise RuntimeError("Could not parse Steve Sidwell weight from archived Premier League profile")
    return int(match.group(1))


def _fetch_player_metadata_from_wikidata(
    session: requests.Session,
    player_sources: list[PlayerSource],
) -> dict[str, dict[str, Any]]:
    qids = [item.qid for item in player_sources]
    payload = _api_get(
        session,
        endpoint="https://www.wikidata.org/w/api.php",
        params={
            "action": "wbgetentities",
            "ids": "|".join(qids),
            "props": "claims",
            "format": "json",
        },
    )
    entities = dict(payload.get("entities") or {})
    out: dict[str, dict[str, Any]] = {}
    sidwell_weight_cache: int | None = None

    for item in player_sources:
        entity = entities.get(item.qid)
        if entity is None:
            raise RuntimeError(f"Wikidata entity missing for {item.name} ({item.qid})")

        claims = dict(entity.get("claims") or {})
        birth_claims = list(claims.get("P569") or [])
        height_claims = list(claims.get("P2048") or [])
        weight_claims = list(claims.get("P2067") or [])

        if not birth_claims:
            raise RuntimeError(f"Missing P569 (date of birth) for {item.name} ({item.qid})")
        if not height_claims:
            raise RuntimeError(f"Missing P2048 (height) for {item.name} ({item.qid})")

        birth_value = (
            birth_claims[0]
            .get("mainsnak", {})
            .get("datavalue", {})
            .get("value", {})
            .get("time")
        )
        if not isinstance(birth_value, str):
            raise RuntimeError(f"Invalid P569 payload for {item.name} ({item.qid})")
        birth_year, birth_month, birth_day = _parse_wikidata_time(birth_value)

        height_value = (
            height_claims[0]
            .get("mainsnak", {})
            .get("datavalue", {})
            .get("value", {})
        )
        if not isinstance(height_value, dict):
            raise RuntimeError(f"Invalid P2048 payload for {item.name} ({item.qid})")
        height_cm = _wikidata_height_to_cm(height_value, player_name=item.name, qid=item.qid)

        weight_kg: int | None = None
        if weight_claims:
            weight_amount = (
                weight_claims[0]
                .get("mainsnak", {})
                .get("datavalue", {})
                .get("value", {})
                .get("amount")
            )
            if isinstance(weight_amount, str):
                weight_kg = int(round(float(weight_amount)))

        if weight_kg is None and item.sidwell_archive_weight_kg is not None:
            if sidwell_weight_cache is None:
                sidwell_weight_cache = _fetch_sidwell_archive_weight(session)
            weight_kg = int(sidwell_weight_cache)

        if weight_kg is None:
            raise RuntimeError(
                f"Missing weight for {item.name} ({item.qid}) and no fallback source was configured"
            )

        out[item.name] = {
            "qid": item.qid,
            "birth_day": int(birth_day),
            "birth_month": int(birth_month),
            "birth_year_real": int(birth_year),
            "height_cm": int(height_cm),
            "weight_kg": int(weight_kg),
            "nationality_label": item.nationality_label,
        }
    return out


def _resolve_stoke_slot_rows(team_file: Path, player_file: Path, team_query: str) -> list[dict[str, Any]]:
    rosters = load_eq_linked_team_rosters(team_file=str(team_file), player_file=str(player_file))
    chosen = None
    needle = team_query.strip().lower()
    for roster in rosters:
        short_name = str(getattr(roster, "short_name", "") or "").lower()
        full_name = str(getattr(roster, "full_club_name", "") or "").lower()
        if needle in short_name or needle in full_name:
            chosen = roster
            break
    if chosen is None:
        raise RuntimeError(f"Could not resolve team roster for query {team_query!r}")

    slot_rows = sorted(list(getattr(chosen, "rows", []) or []), key=lambda row: int(getattr(row, "slot_index", 0)))
    if len(slot_rows) < len(STOKE_SLOT_NAMES):
        raise RuntimeError(
            f"Resolved roster has {len(slot_rows)} rows; expected at least {len(STOKE_SLOT_NAMES)} for Stoke slots"
        )
    return [
        {
            "slot": int(getattr(row, "slot_index", 0)) + 1,
            "pid": int(getattr(row, "player_record_id", 0) or 0),
            "player_name": str(getattr(row, "player_name", "") or ""),
        }
        for row in slot_rows[: len(STOKE_SLOT_NAMES)]
    ]


def _map_record_ids_to_offsets(player_file: Path) -> dict[int, int]:
    indexed = IndexedFDIFile.from_path(player_file)
    return {int(entry.record_id): int(entry.payload_offset) for entry in indexed.entries}


def _build_batch_rows(
    *,
    slot_rows: list[dict[str, Any]],
    record_offset_by_id: dict[int, int],
    source_metadata: dict[str, dict[str, Any]],
    nationality_codes: dict[str, int],
    year_shift: int,
) -> list[dict[str, Any]]:
    if len(slot_rows) != len(STOKE_SLOT_NAMES):
        raise RuntimeError("Slot row count mismatch while building batch rows")

    out: list[dict[str, Any]] = []
    for slot_index, expected_name in enumerate(STOKE_SLOT_NAMES, start=1):
        row = slot_rows[slot_index - 1]
        record_id = int(row["pid"])
        if record_id <= 0:
            raise RuntimeError(f"Slot {slot_index} has invalid player record id: {record_id}")
        if record_id not in record_offset_by_id:
            raise RuntimeError(f"Record id {record_id} (slot {slot_index}) missing from indexed player map")
        if expected_name not in source_metadata:
            raise RuntimeError(f"Source metadata missing for {expected_name}")

        meta = source_metadata[expected_name]
        nationality_label = str(meta["nationality_label"])
        if nationality_label not in nationality_codes:
            raise RuntimeError(
                f"Nationality label {nationality_label!r} for {expected_name} is not present in TEXTOS.PKF table"
            )

        calibrated_birth_year = int(meta["birth_year_real"]) - int(year_shift)
        if calibrated_birth_year < 1900 or calibrated_birth_year > 1999:
            raise RuntimeError(
                f"Calibrated birth year out of supported range for {expected_name}: {calibrated_birth_year}"
            )

        out.append(
            {
                "slot": slot_index,
                "pid": record_id,
                "name": expected_name,
                "offset": int(record_offset_by_id[record_id]),
                "nationality_label": nationality_label,
                "nationality_code": int(nationality_codes[nationality_label]),
                "birth_day": int(meta["birth_day"]),
                "birth_month": int(meta["birth_month"]),
                "birth_year_real": int(meta["birth_year_real"]),
                "birth_year_calibrated": int(calibrated_birth_year),
                "height_cm": int(meta["height_cm"]),
                "weight_kg": int(meta["weight_kg"]),
                "source_qid": str(meta["qid"]),
            }
        )
    return out


def _write_batch_csv(csv_path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "name",
        "offset",
        "new_name",
        "team_id",
        "squad_number",
        "position",
        "nationality",
        "dob_day",
        "dob_month",
        "dob_year",
        "age",
        "age_year",
        "height",
        "weight",
    ]
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "name": row["name"],
                    "offset": row["offset"],
                    "new_name": "",
                    "team_id": "",
                    "squad_number": "",
                    "position": "",
                    "nationality": row["nationality_code"],
                    "dob_day": row["birth_day"],
                    "dob_month": row["birth_month"],
                    "dob_year": row["birth_year_calibrated"],
                    "age": "",
                    "age_year": "",
                    "height": row["height_cm"],
                    "weight": row["weight_kg"],
                }
            )


def _parse_player_at_offset(player_file: Path, offset: int, record_id: int) -> PlayerRecord:
    indexed = IndexedFDIFile.from_path(player_file)
    entry = next((item for item in indexed.entries if int(item.record_id) == int(record_id)), None)
    if entry is None:
        raise RuntimeError(f"Record id {record_id} not found while verifying offset {offset}")
    if int(entry.payload_offset) != int(offset):
        raise RuntimeError(
            f"Offset mismatch for record id {record_id}: expected {offset}, indexed has {entry.payload_offset}"
        )
    decoded = entry.decode_payload(player_file.read_bytes())
    return PlayerRecord.from_bytes(decoded, int(entry.payload_offset))


def _verify_rows(player_file: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    verification: list[dict[str, Any]] = []
    player_bytes = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(player_bytes)
    entry_by_id = {int(entry.record_id): entry for entry in indexed.entries}
    for row in rows:
        record_id = int(row["pid"])
        entry = entry_by_id.get(record_id)
        if entry is None:
            raise RuntimeError(f"Verification missing indexed record id {record_id}")
        decoded = entry.decode_payload(player_bytes)
        parsed = PlayerRecord.from_bytes(decoded, int(entry.payload_offset))
        actual = {
            "nationality": int(getattr(parsed, "nationality", 0) or 0),
            "birth_day": int(getattr(parsed, "birth_day", 0) or 0),
            "birth_month": int(getattr(parsed, "birth_month", 0) or 0),
            "birth_year": int(getattr(parsed, "birth_year", 0) or 0),
            "height": int(getattr(parsed, "height", 0) or 0),
            "weight": int(getattr(parsed, "weight", 0) or 0),
        }
        expected = {
            "nationality": int(row["nationality_code"]),
            "birth_day": int(row["birth_day"]),
            "birth_month": int(row["birth_month"]),
            "birth_year": int(row["birth_year_calibrated"]),
            "height": int(row["height_cm"]),
            "weight": int(row["weight_kg"]),
        }
        verification.append(
            {
                "slot": int(row["slot"]),
                "name": row["name"],
                "pid": record_id,
                "offset": int(row["offset"]),
                "expected": expected,
                "actual": actual,
                "matches": expected == actual,
            }
        )
    return verification


def _run_cli(command: list[str], cwd: Path) -> dict[str, Any]:
    completed = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True, check=False)
    return {
        "command": command,
        "returncode": int(completed.returncode),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def main() -> int:
    args = _parse_args()
    game_dir = resolve_game_root(
        args.game_root,
        require_writable=not bool(args.dry_run),
        default_to_fixture=bool(args.dry_run),
    )
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    team_file = game_dir / "DBDAT" / "EQ98030.FDI"
    player_file = game_dir / "DBDAT" / "JUG98030.FDI"
    coach_file = game_dir / "DBDAT" / "ENT98030.FDI"
    textos_pkf = game_dir / "DBDAT" / "TEXTOS.PKF"
    for path in (team_file, player_file, coach_file, textos_pkf):
        if not path.is_file():
            raise SystemExit(f"Required file missing: {path}")

    session = requests.Session()
    session.headers.update({"User-Agent": "pm99-research/1.0 (stoke metadata pipeline)"})

    nationality_codes = _extract_nationality_codes(textos_pkf)
    source_metadata = _fetch_player_metadata_from_wikidata(session, PLAYER_SOURCES)
    slot_rows = _resolve_stoke_slot_rows(team_file, player_file, args.team_query)
    record_offset_by_id = _map_record_ids_to_offsets(player_file)

    batch_rows = _build_batch_rows(
        slot_rows=slot_rows,
        record_offset_by_id=record_offset_by_id,
        source_metadata=source_metadata,
        nationality_codes=nationality_codes,
        year_shift=int(args.year_shift),
    )

    csv_path = output_dir / "stoke_2015_metadata_batch.csv"
    _write_batch_csv(csv_path, batch_rows)

    manifest = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "game_dir": str(game_dir),
        "team_file": str(team_file),
        "player_file": str(player_file),
        "coach_file": str(coach_file),
        "textos_pkf": str(textos_pkf),
        "input_hashes": {
            "EQ98030.FDI": sha256(team_file),
            "JUG98030.FDI": sha256(player_file),
            "ENT98030.FDI": sha256(coach_file),
            "TEXTOS.PKF": sha256(textos_pkf),
        },
        "team_query": args.team_query,
        "year_shift": int(args.year_shift),
        "nationality_code_subset": {
            label: int(code)
            for label, code in nationality_codes.items()
            if label
            in {
                "ENGLAND",
                "SCOTLAND",
                "HOLLAND",
                "SPAIN",
                "IRELAND",
                "AUSTRIA",
                "NIGERIA",
                "SENEGAL",
                "UNITED STATES",
                "FRANCE",
            }
        },
        "batch_rows": batch_rows,
        "csv_path": str(csv_path),
        "dry_run": bool(args.dry_run),
        "sources": {
            "wikidata_api": "https://www.wikidata.org/w/api.php",
            "sidwell_weight_archive": (
                "https://web.archive.org/web/20140822121738/"
                "http://www.premierleague.com/en-gb/players/profile.html/steve-sidwell"
            ),
        },
    }
    manifest_path = output_dir / "stoke_2015_metadata_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    result: dict[str, Any] = {
        "manifest_path": str(manifest_path),
        "csv_path": str(csv_path),
        "dry_run": bool(args.dry_run),
        "initial_hashes": manifest["input_hashes"],
    }

    if not args.dry_run:
        batch_cmd = [
            "./scripts/dev_editor.sh",
            "python3",
            "-m",
            "app.cli",
            "player-batch-edit",
            str(player_file),
            "--csv",
            str(csv_path),
            "--json",
        ]
        batch_result = _run_cli(batch_cmd, cwd=REPO_ROOT)
        result["player_batch_edit"] = batch_result
        if batch_result["returncode"] != 0:
            result_path = output_dir / "stoke_2015_metadata_apply_result.json"
            result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
            raise SystemExit(
                f"player-batch-edit failed (exit {batch_result['returncode']}), see {result_path}"
            )

        validate_cmd = [
            "./scripts/dev_editor.sh",
            "python3",
            "-m",
            "app.cli",
            "validate-database",
            "--players",
            str(player_file),
            "--teams",
            str(team_file),
            "--coaches",
            str(coach_file),
            "--json",
        ]
        validate_result = _run_cli(validate_cmd, cwd=REPO_ROOT)
        result["validate_database"] = validate_result

        verification_rows = _verify_rows(player_file, batch_rows)
        verification_path = output_dir / "stoke_2015_metadata_verification.json"
        verification_path.write_text(json.dumps(verification_rows, indent=2), encoding="utf-8")
        result["verification_path"] = str(verification_path)
        result["verification_ok"] = all(bool(item.get("matches")) for item in verification_rows)

    result_path = output_dir / "stoke_2015_metadata_apply_result.json"
    result["final_hashes"] = {
        "EQ98030.FDI": sha256(team_file),
        "JUG98030.FDI": sha256(player_file),
        "ENT98030.FDI": sha256(coach_file),
        "TEXTOS.PKF": sha256(textos_pkf),
    }
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"result_path": str(result_path), "manifest_path": str(manifest_path), "csv_path": str(csv_path)}, indent=2))
    if not args.dry_run and not result.get("verification_ok", False):
        raise SystemExit(f"Verification failed, see {result_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
