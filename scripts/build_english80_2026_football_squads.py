#!/usr/bin/env python3
"""Build a source-backed modern English 80-club PM99 candidate.

The script uses FootballSquads 2025/2026 pages for current club membership and
player bio fields, then feeds those names into the proven repointed-roster
builder. A second pass patches the compact runtime-safe clone records with
position, nationality, DOB, height, weight and transparent derived attributes.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import shutil
import struct
import sys
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
EDITOR_ROOT = REPO_ROOT / "upstream" / "pm99-skezmod-db-editor"
if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from app.fdi_indexed import IndexedFDIFile  # noqa: E402
from app.models import PlayerRecord  # noqa: E402
from app.xor import xor_encode  # noqa: E402
from assert_pm99_isolated_input import sha256  # noqa: E402
from build_pm99_repointed_roster_candidate import build_repointed_candidate  # noqa: E402
from build_pm99_runtime_safe_assignment import runtime_safe_name  # noqa: E402
from repair_full_db_world_runtime_payloads import _linked_roster_layout, _write_raw_indexed_payloads  # noqa: E402
from stoke_2015_apply_metadata import _extract_nationality_codes  # noqa: E402


BASE_URL = "https://www.footballsquads.co.uk/eng/2025-2026/"
SOURCE_SNAPSHOT_DATE = datetime.now(UTC).date().isoformat()
DEFAULT_BASE_ASSIGNMENT = (
    REPO_ROOT
    / "work"
    / "pm99"
    / "codex_2025_runtime_safe_assignment_v2_20260426T142142Z"
    / "slot_assignment_2025_top80_runtime_safe.json"
)
DEFAULT_BASE_WORLD = (
    REPO_ROOT
    / "work"
    / "pm99"
    / "codex_2025_repointed"
    / "repointed_runtime_safe_fulltoken_20260426T142200Z"
    / "world_2025_top80_runtime_selectors_from_assignment.json"
)
DEFAULT_BASE_GAME = REPO_ROOT / "work" / "fixtures" / "premier-manager-ninety-nine-pristine"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "work" / "pm99" / "english80_2026_football_squads"

LEAGUES = [
    ("premier_league", "Premier League", "engprem.htm", 20),
    ("championship", "EFL Championship", "flcham.htm", 24),
    ("league_one", "EFL League One", "flone.htm", 24),
    ("league_two", "EFL League Two", "fltwo.htm", 12),
]

POSITION_CODE = {"G": 0, "D": 1, "M": 2, "F": 3}
POSITION_LABEL = {0: "Goalkeeper", 1: "Defender", 2: "Midfielder", 3: "Forward"}
SKILL_LABELS = [
    "speed",
    "stamina",
    "aggression",
    "quality",
    "heading",
    "dribbling",
    "passing",
    "shooting",
    "tackling",
]

LINK_NAME_OVERRIDES = {
    "flone/bradford.htm": "Bradford City",
}

SOURCE_MONONYM_ALIASES = {
    "Andre": "Andre Trindade",
    "Beto": "Beto Betuncal",
    "Casemiro": "Carlos Casemiro",
    "Evanilson": "Evanilson Lima",
    "Gabriel": "Gabriel Magalhaes",
    "Igor": "Igor Julio",
    "Joelinton": "Joelinton Cassio",
    "John": "John Victor",
    "Kevin": "Kevin Santos",
    "Morato": "Felipe Morato",
    "Murillo": "Murillo Costa",
    "Pablo": "Pablo Fornals",
    "Richarlison": "Richarlison Andrade",
    "Rodri": "Rodri Hernandez",
    "Savinho": "Savio Moreira",
    "Vivaldo": "Vivaldo Semedo",
}

NAT_ABBR_TO_PM99_LABEL = {
    "AFG": "AFGHANISTAN",
    "ALB": "ALBANIA",
    "ALG": "ALGIERS",
    "AND": "ANDORRA",
    "ANG": "ANGOLA",
    "ANT": "ANTIGUA Y BARBUDA",
    "ATG": "ANTIGUA Y BARBUDA",
    "ARG": "ARGENTINA",
    "ARM": "ARMENIA",
    "AUS": "AUSTRALIA",
    "AUT": "AUSTRIA",
    "AZE": "AZERBAIJAN",
    "BAH": "THE BAHAMAS",
    "BAN": "BANGLADESH",
    "BDI": "BURUNDI",
    "BEL": "BELGIUM",
    "BEN": "BENIN",
    "BER": "BERMUDA",
    "BFA": "BURKINA FASO",
    "BHR": "BAHRAIN",
    "BIH": "BOSNIA HERZEGOVINA",
    "BLR": "BELARUS",
    "BOL": "BOLIVIA",
    "BRA": "BRAZIL",
    "BRB": "BARBADOS",
    "BUL": "BULGARIA",
    "CAN": "CANADA",
    "CGO": "CONGO",
    "CHI": "CHILE",
    "CHN": "CHINA",
    "CIV": "IVORY COAST",
    "CMR": "CAMEROON",
    "COD": "ZAIRE",
    "COL": "COLOMBIA",
    "COM": "COMORO",
    "CPV": "CAPE VERDE",
    "CRC": "COSTA RICA",
    "CRO": "CROATIA",
    "CUB": "CUBA",
    "CUW": "HOLLAND",
    "CYP": "CYPRUS",
    "CZE": "CZECH REPUBLIC",
    "DEN": "DENMARK",
    "DJI": "DJIBOUTI",
    "ECU": "ECUADOR",
    "EGY": "EGYPT",
    "ENG": "ENGLAND",
    "EQG": "EQUATORIAL GUINEA",
    "ERI": "ERITREA",
    "ESP": "SPAIN",
    "EST": "ESTONIA",
    "FIN": "FINLAND",
    "FRA": "FRANCE",
    "GAB": "GABON",
    "GAM": "GAMBIA",
    "GEO": "GEORGIA",
    "GER": "GERMANY",
    "GHA": "GHANA",
    "GRE": "GREECE",
    "GRN": "GRANADA",
    "GUA": "GUATEMALA",
    "GUI": "GUINEA",
    "GNB": "GUINEA BISSAU",
    "GUY": "FRENCH GUYANA",
    "HAI": "HAITI",
    "HON": "HONDURAS",
    "HUN": "HUNGARY",
    "ICE": "ICELAND",
    "IDN": "INDONESIA",
    "IND": "INDIA",
    "IRL": "IRELAND",
    "IRN": "IRAN",
    "IRQ": "IRAQ",
    "ISL": "ICELAND",
    "ISR": "ISRAEL",
    "ITA": "ITALY",
    "JAM": "JAMAICA",
    "JPN": "JAPAN",
    "KEN": "KENYA",
    "KOR": "SOUTH KOREA",
    "KSA": "SAUDI ARABIA",
    "KSV": "ALBANIA",
    "KVX": "YUGOSLAVIA",
    "KWT": "KUWAIT",
    "LAT": "LATVIA",
    "LBR": "LIBERIA",
    "LCA": "SAINT LUCIA",
    "LIB": "LIBERIA",
    "LBY": "LIBYA",
    "LIE": "LIECHTENSTEIN",
    "LTU": "LITHUANIA",
    "LUX": "LUXEMBOURG",
    "LVA": "LATVIA",
    "MAD": "MADAGASCAR",
    "MAL": "MALI",
    "MAR": "MOROCCO",
    "MDA": "MOLDOVA",
    "MEX": "MEXICO",
    "MKD": "MACEDONIA",
    "MLT": "MALTA",
    "MLI": "MALI",
    "MNE": "YUGOSLAVIA",
    "MOZ": "MOZAMBIQUE",
    "MSR": "UNITED KINGDOM",
    "MTQ": "MARTINIQUE",
    "NED": "HOLLAND",
    "NGA": "NIGERIA",
    "NIR": "NORTHERN IRELAND",
    "NOR": "NORWAY",
    "NZL": "NEW ZEALAND",
    "PAN": "PANAMA",
    "PAR": "PARAGUAY",
    "PER": "PERU",
    "POL": "POLAND",
    "POR": "PORTUGAL",
    "PRK": "NORTH KOREA",
    "QAT": "QATAR",
    "ROU": "ROMANIA",
    "RSA": "SOUTH AFRICA",
    "RUS": "RUSSIA",
    "SCO": "SCOTLAND",
    "SEN": "SENEGAL",
    "SEY": "SEYCHELLES",
    "SLE": "SIERRA LEONE",
    "SIN": "SINGAPORE",
    "SLO": "SLOVENIA",
    "SMR": "SAN MARINO",
    "SKN": "SAN KITTS Y NEVIS",
    "SRB": "SERBIA",
    "STP": "SAINT TOME AND PRINCE",
    "SUI": "SWITZERLAND",
    "SVK": "SLOVAKIA",
    "SVN": "SLOVENIA",
    "SWE": "SWEDEN",
    "TAN": "TANZANIA",
    "THA": "THAILAND",
    "TOG": "TOGO",
    "TRI": "TRINIDAD AND TOBAGO",
    "TUN": "TUNISIA",
    "TUR": "TURKEY",
    "UGA": "UGANDA",
    "UKR": "UKRAINE",
    "URU": "URUGUAY",
    "USA": "UNITED STATES",
    "UZB": "UZBEKISTHAN",
    "VEN": "VENEZUELA",
    "VIE": "VIETNAM",
    "WAL": "WALES",
    "ZAM": "ZAMBIA",
    "ZIM": "ZIMBABWE",
}


@dataclass(frozen=True)
class ClubSource:
    club_key: str
    display_name: str
    league_key: str
    league_name: str
    league_index: int
    source_url: str
    players: list[dict[str, Any]]


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _make_tree_user_writable(path: Path) -> None:
    for item in [path, *path.rglob("*")]:
        try:
            mode = item.stat().st_mode
        except FileNotFoundError:
            continue
        if item.is_dir():
            item.chmod(mode | 0o700)
        else:
            item.chmod(mode | 0o600)


def _ascii(value: str) -> str:
    replacements = {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u00a0": " ",
        "\u00d8": "O",
        "\u00f8": "o",
        "\u0110": "D",
        "\u0111": "d",
        "\u00de": "Th",
        "\u00fe": "th",
        "\u0141": "L",
        "\u0142": "l",
        "\u00d0": "D",
        "\u00f0": "d",
        "&amp;": "&",
    }
    text = str(value or "")
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.encode("ascii", errors="ignore").decode("ascii").split())


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _ascii(value).casefold()).strip("_") or "unknown"


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _ascii(value).casefold())


def _fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "pm99-research/english80-source-build"})
    with urlopen(request, timeout=30) as response:
        data = response.read()
    return data.decode("utf-8", errors="replace")


def _cell_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value, flags=re.S)
    return " ".join(html.unescape(text).split()).strip()


def _table_rows(document: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", document, flags=re.S | re.I):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, flags=re.S | re.I)
        if cells:
            rows.append([_cell_text(cell) for cell in cells])
    return rows


def _league_links(index_url: str, limit: int) -> list[tuple[str, str]]:
    document = _fetch_text(index_url)
    links: list[tuple[str, str]] = []
    for href, text in re.findall(r'href="([^"]+\.htm)"[^>]*>(.*?)</a>', document, flags=re.S | re.I):
        if href.startswith(("../", "../../")):
            continue
        href = href.strip()
        display_name = LINK_NAME_OVERRIDES.get(href, _cell_text(text))
        if not display_name or display_name.lower() in {"search", "contact", "privacy policy", "terms of use", "squads"}:
            continue
        links.append((display_name, urljoin(index_url, href)))
    if len(links) < limit:
        raise RuntimeError(f"{index_url} yielded only {len(links)} club links; need {limit}")
    return links[:limit]


def _parse_position(value: str) -> str:
    text = str(value or "").strip().upper()
    for char in text:
        if char in POSITION_CODE:
            return char
    return "M"


def _runtime_safe_source_name(name: str) -> str:
    ascii_name = _ascii(name)
    expanded = SOURCE_MONONYM_ALIASES.get(ascii_name, ascii_name)
    return runtime_safe_name(expanded)


def _parse_dob(value: str) -> tuple[int, int, int] | None:
    text = str(value or "").strip()
    if not text or text == "-":
        return None
    match = re.match(r"^(\d{1,2})-(\d{1,2})-(\d{2}|\d{4})$", text)
    if not match:
        return None
    day = int(match.group(1))
    month = int(match.group(2))
    year_value = int(match.group(3))
    if year_value < 100:
        year = 1900 + year_value if year_value >= 40 else 2000 + year_value
    else:
        year = year_value
    return day, month, year


def _height_cm(value: str, position: str) -> int:
    text = str(value or "").strip()
    if text and text != "-":
        try:
            return max(150, min(215, int(round(float(text) * 100.0))))
        except ValueError:
            pass
    return {"G": 188, "D": 184, "M": 178, "F": 181}.get(position, 178)


def _weight_kg(value: str, position: str) -> int:
    text = str(value or "").strip()
    if text and text != "-":
        try:
            return max(55, min(115, int(round(float(text)))))
        except ValueError:
            pass
    return {"G": 82, "D": 78, "M": 73, "F": 76}.get(position, 74)


def _pm99_birth_year(real_year: int | None) -> int:
    if real_year is None:
        return 1976
    return max(1900, min(1999, int(real_year) - 27))


def _age_2026(real_year: int | None) -> int:
    if real_year is None:
        return 26
    return max(16, min(45, 2026 - int(real_year)))


def _clamp_attr(value: int) -> int:
    return max(30, min(95, int(value)))


def _attributes(position: str, league_key: str, squad_number: int | None, height: int, weight: int, real_year: int | None) -> tuple[dict[str, int], str]:
    tier_base = {
        "premier_league": 76,
        "championship": 68,
        "league_one": 61,
        "league_two": 55,
    }[league_key]
    if squad_number is not None and 1 <= squad_number <= 11:
        tier_base += 3
    elif squad_number is not None and squad_number >= 40:
        tier_base -= 5
    age = _age_2026(real_year)
    prime = 4 - min(abs(age - 27), 10) // 3
    tall = (height - 180) // 4
    heavy = (weight - 75) // 5
    if position == "G":
        values = {
            "speed": 54 + prime,
            "stamina": 62 + prime,
            "aggression": 55 + heavy,
            "quality": tier_base + 1,
            "heading": 42 + tall,
            "dribbling": 36,
            "passing": 55 + prime,
            "shooting": 32,
            "tackling": 42,
        }
    elif position == "D":
        values = {
            "speed": 63 + prime - max(0, heavy),
            "stamina": 69 + prime,
            "aggression": 70 + heavy,
            "quality": tier_base,
            "heading": 69 + tall,
            "dribbling": 58 + prime,
            "passing": 62 + prime,
            "shooting": 45 + prime,
            "tackling": 73 + prime + heavy,
        }
    elif position == "M":
        values = {
            "speed": 65 + prime,
            "stamina": 72 + prime,
            "aggression": 63 + heavy,
            "quality": tier_base,
            "heading": 58 + tall,
            "dribbling": 70 + prime,
            "passing": 73 + prime,
            "shooting": 62 + prime,
            "tackling": 63 + prime,
        }
    else:
        values = {
            "speed": 69 + prime - max(0, heavy // 2),
            "stamina": 67 + prime,
            "aggression": 64 + heavy,
            "quality": tier_base,
            "heading": 67 + tall,
            "dribbling": 70 + prime,
            "passing": 62 + prime,
            "shooting": 75 + prime,
            "tackling": 43 + prime,
        }
    return {label: _clamp_attr(values[label]) for label in SKILL_LABELS}, (
        "Derived from FootballSquads bio fields using league tier, position, "
        "squad number, age, height and weight."
    )


def _fine_roles(position: str, squad_number: int | None, height: int) -> list[int]:
    if position == "G":
        return [0]
    if position == "D":
        if squad_number in {2, 12, 22}:
            return [1]
        if squad_number in {3, 13, 23}:
            return [2]
        return [4]
    if position == "M":
        return [14 if squad_number in {4, 5, 6} else 9]
    return [12 if height >= 186 else 15]


def _parse_team_players(url: str, league_key: str, country_codes: dict[str, int]) -> list[dict[str, Any]]:
    rows = _table_rows(_fetch_text(url))
    players: list[dict[str, Any]] = []
    in_current = False
    for cells in rows:
        if len(cells) == 1 and "players no longer" in cells[0].lower():
            break
        if len(cells) >= 8 and cells[0].lower() == "number" and cells[1].lower() == "name":
            in_current = True
            continue
        if not in_current or len(cells) < 8:
            continue
        number_text, name, nat_abbr, position_text, height_text, weight_text, dob_text, birth_place = cells[:8]
        if not name or not number_text.strip().isdigit():
            continue
        position = _parse_position(position_text)
        squad_number = int(number_text)
        real_dob = _parse_dob(dob_text)
        real_year = real_dob[2] if real_dob else None
        height = _height_cm(height_text, position)
        weight = _weight_kg(weight_text, position)
        nat_abbr = nat_abbr.strip().upper()
        pm99_label = NAT_ABBR_TO_PM99_LABEL.get(nat_abbr)
        if not pm99_label:
            pm99_label = "XXX"
        pm99_nat_code = country_codes.get(pm99_label, country_codes["XXX"])
        skills, attribute_basis = _attributes(position, league_key, squad_number, height, weight, real_year)
        players.append(
            {
                "source_number": squad_number,
                "source_name": name,
                "runtime_safe_name": _runtime_safe_source_name(name),
                "source_nat_abbr": nat_abbr,
                "pm99_nat_label": pm99_label,
                "pm99_nat_code": int(pm99_nat_code),
                "source_position": position,
                "pm99_position_code": POSITION_CODE[position],
                "pm99_position_label": POSITION_LABEL[POSITION_CODE[position]],
                "source_height": height_text,
                "height_cm": height,
                "source_weight": weight_text,
                "weight_kg": weight,
                "dob_source": dob_text,
                "real_birth_day": real_dob[0] if real_dob else None,
                "real_birth_month": real_dob[1] if real_dob else None,
                "real_birth_year": real_dob[2] if real_dob else None,
                "birth_day": real_dob[0] if real_dob else 1,
                "birth_month": real_dob[1] if real_dob else 7,
                "birth_year": _pm99_birth_year(real_year),
                "birth_place": birth_place,
                "previous_club": cells[8] if len(cells) > 8 else "",
                "skills": skills,
                "attribute_basis": attribute_basis,
                "fine_role_codes": _fine_roles(position, squad_number, height),
                "source_url": url,
                "source_section": "current squad",
            }
        )
    if len(players) < 20:
        raise RuntimeError(f"{url} yielded only {len(players)} current players; need 20")
    return players


def _select_twenty(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets = {position: [row for row in players if row["source_position"] == position] for position in POSITION_CODE}
    required = [("G", 1), ("D", 4), ("M", 4), ("F", 2)]
    selected: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()

    def add(row: dict[str, Any]) -> None:
        key = (int(row["source_number"]), str(row["source_name"]))
        if key not in seen:
            selected.append(row)
            seen.add(key)

    lineup: list[dict[str, Any]] = []
    for position, count in required:
        chosen = buckets[position][:count]
        if len(chosen) < count:
            chosen.extend(row for row in players if row not in chosen)
            chosen = chosen[:count]
        for row in chosen:
            add(row)
            lineup.append(row)
    for row in players:
        if len(selected) >= 20:
            break
        add(row)
    ordered = lineup + [row for row in selected if row not in lineup]
    return [dict(row, slot=index) for index, row in enumerate(ordered[:20], start=1)]


def scrape_sources(country_codes: dict[str, int], *, base_assignment: dict[str, Any]) -> tuple[list[ClubSource], list[dict[str, Any]]]:
    by_name: dict[str, tuple[str, str, str, int]] = {}
    all_links: list[dict[str, Any]] = []
    for league_key, league_name, index_href, limit in LEAGUES:
        index_url = urljoin(BASE_URL, index_href)
        for league_index, (display_name, url) in enumerate(_league_links(index_url, limit), start=1):
            row = {
                "league_key": league_key,
                "league_name": league_name,
                "league_index": league_index,
                "display_name": display_name,
                "source_url": url,
            }
            all_links.append(row)
            by_name[_norm(display_name)] = (league_key, league_name, url, league_index)

    sources: list[ClubSource] = []
    for assignment in base_assignment.get("assignments", []):
        display_name = str(assignment.get("target_display_name") or assignment.get("club_key") or "").strip()
        club_key = str(assignment.get("target_club_key") or assignment.get("club_key") or _slug(display_name)).strip()
        match = by_name.get(_norm(display_name))
        if match is None:
            raise RuntimeError(f"No FootballSquads link found for assignment club {display_name!r} ({club_key})")
        league_key, league_name, source_url, league_index = match
        players = _select_twenty(_parse_team_players(source_url, league_key, country_codes))
        sources.append(
            ClubSource(
                club_key=club_key,
                display_name=display_name,
                league_key=league_key,
                league_name=league_name,
                league_index=league_index,
                source_url=source_url,
                players=players,
            )
        )
    return sources, all_links


def build_assignment(base_assignment: dict[str, Any], sources: list[ClubSource]) -> dict[str, Any]:
    source_by_key = {source.club_key: source for source in sources}
    output = json.loads(json.dumps(base_assignment))
    output["schema"] = "pm99-english80-footballsquads-slot-assignment-v1"
    output["source_snapshot"] = {
        "source": "FootballSquads",
        "base_url": BASE_URL,
        "season": "2025/2026",
        "snapshot_date": SOURCE_SNAPSHOT_DATE,
        "policy": "current squad only; first source-backed 20 after position-shaped lineup ordering",
    }
    for assignment in output.get("assignments", []):
        club_key = str(assignment.get("target_club_key") or assignment.get("club_key") or "")
        source = source_by_key[club_key]
        old_rows = {int(row.get("slot") or 0): row for row in assignment.get("roster", []) if isinstance(row, dict)}
        new_roster: list[dict[str, Any]] = []
        for player in source.players:
            slot = int(player["slot"])
            old_row = dict(old_rows.get(slot, {}))
            runtime_name = str(player["runtime_safe_name"])
            old_row.update(
                {
                    "slot": slot,
                    "target_name": runtime_name,
                    "applied_name": runtime_name,
                    "source_target_name": player["source_name"],
                    "source_number": int(player["source_number"]),
                    "source_nat_abbr": player["source_nat_abbr"],
                    "source_position": player["source_position"],
                    "source_url": source.source_url,
                }
            )
            old_row.setdefault("record_id", int(old_row.get("original_record_id") or 0))
            new_roster.append(old_row)
        assignment["roster"] = new_roster
        assignment["skipped_target_names"] = []
        assignment["source_skipped_target_names"] = []
        assignment["source_league"] = source.league_name
        assignment["source_url"] = source.source_url
    output["runtime_safe_name_policy"] = {
        "schema": "pm99-runtime-safe-name-policy-v1",
        "source": "build_pm99_runtime_safe_assignment.runtime_safe_name",
        "current_squad_display_max_bytes": 12,
    }
    return output


def build_world_state(base_world: dict[str, Any], sources: list[ClubSource]) -> dict[str, Any]:
    source_by_key = {source.club_key: source for source in sources}
    world = json.loads(json.dumps(base_world))
    world["schema"] = "pm99-english80-footballsquads-world-v1"
    world["generated_at"] = datetime.now(UTC).isoformat()
    world["generated_by"] = "scripts/build_english80_2026_football_squads.py"
    world["scope"] = {
        "source": "FootballSquads 2025/2026",
        "snapshot_date": SOURCE_SNAPSHOT_DATE,
        "clubs": 80,
        "players": 1600,
    }
    players: list[dict[str, Any]] = []
    memberships: list[dict[str, Any]] = []
    for club in world.get("clubs", []):
        club_key = str(club.get("club_key") or "")
        source = source_by_key.get(club_key)
        if source is None:
            continue
        club["source_league"] = source.league_name
        club["source_url"] = source.source_url
        club["target_display_name"] = source.display_name
        club["set_name"] = source.display_name
        for player in source.players:
            player_key = f"{club_key}_p{int(player['slot']):02d}"
            players.append(
                {
                    "player_key": player_key,
                    "club_key": club_key,
                    "slot": int(player["slot"]),
                    "set_name": player["runtime_safe_name"],
                    "source_name": player["source_name"],
                    "source_number": int(player["source_number"]),
                    "source_position": player["source_position"],
                    "source_nat_abbr": player["source_nat_abbr"],
                    "source_url": source.source_url,
                }
            )
            memberships.append({"club_key": club_key, "player_key": player_key, "slot": int(player["slot"])})
    world["players"] = players
    world["squad_memberships"] = memberships
    return world


def _encode_byte(value: int) -> int:
    if not 0 <= int(value) <= 255:
        raise ValueError(f"Byte value out of range: {value}")
    return int(value) ^ 0x61


def _decoded_byte(decoded: bytes, offset: int) -> int:
    return decoded[offset] ^ 0x61


def _write_decoded_byte(decoded: bytearray, offset: int, value: int) -> None:
    if offset < 0 or offset >= len(decoded):
        raise RuntimeError(f"Patch offset {offset} outside payload length {len(decoded)}")
    decoded[offset] = _encode_byte(value)


def _encode_role_slot(code: int) -> int:
    if int(code) == 98:
        decoded = 0
    elif 0 <= int(code) <= 17:
        decoded = int(code) + 1
    else:
        raise ValueError(f"Fine role code out of range: {code}")
    return _encode_byte(decoded)


def _read_clone_fields(decoded: bytes, name_end: int) -> dict[str, Any]:
    year = _decoded_byte(decoded, name_end + 11) | (_decoded_byte(decoded, name_end + 12) << 8)
    skills = [_decoded_byte(decoded, name_end + 15 + i) for i in range(9)]
    ui_role_decoded = _decoded_byte(decoded, name_end - 3)
    legacy_role_decoded = [_decoded_byte(decoded, name_end - 1 + i) for i in range(6)]
    return {
        "ui_primary_role_decoded": ui_role_decoded,
        "ui_primary_role_code": int(ui_role_decoded - 1) if ui_role_decoded > 0 else 98,
        "legacy_role_window_decoded": legacy_role_decoded,
        "legacy_role_window_codes": [int(value - 1) if value > 0 else 98 for value in legacy_role_decoded],
        "visible_nationality_code": _decoded_byte(decoded, name_end + 5),
        "unknown_6": _decoded_byte(decoded, name_end + 6),
        "parser_position_code": _decoded_byte(decoded, name_end + 7),
        "visible_position_code": _decoded_byte(decoded, name_end + 8),
        "birth_day": _decoded_byte(decoded, name_end + 9),
        "birth_month": _decoded_byte(decoded, name_end + 10),
        "birth_year": year,
        "height_cm": _decoded_byte(decoded, name_end + 13),
        "weight_kg": _decoded_byte(decoded, name_end + 14),
        "skills": dict(zip(SKILL_LABELS, skills, strict=True)),
    }


def _patch_clone_payload(decoded: bytes, source_row: dict[str, Any]) -> tuple[bytes, dict[str, Any], dict[str, Any], int]:
    parsed = PlayerRecord.from_bytes(decoded, 0)
    name_end = PlayerRecord._find_name_end(decoded)
    if name_end is None:
        raise RuntimeError(f"Could not locate name-end marker for {source_row['source_name']}")
    if decoded[2:5] != b"\xdd\x63\x60":
        raise RuntimeError(
            f"{source_row['source_name']} is not a dd6360 runtime clone payload: signature={decoded[2:5].hex()}"
        )
    required_end = name_end + 15 + len(SKILL_LABELS)
    if required_end > len(decoded):
        raise RuntimeError(
            f"{source_row['source_name']} payload too short for compact clone semantic block: "
            f"need {required_end}, length {len(decoded)}"
        )

    before = _read_clone_fields(decoded, name_end)
    patched = bytearray(decoded)
    primary_role = int(list(source_row["fine_role_codes"])[0])
    patched[name_end - 3] = _encode_role_slot(primary_role)
    patched[name_end - 1] = _encode_role_slot(primary_role)

    _write_decoded_byte(patched, name_end + 5, int(source_row["pm99_nat_code"]))
    _write_decoded_byte(patched, name_end + 7, int(source_row["pm99_position_code"]))
    _write_decoded_byte(patched, name_end + 8, int(source_row["pm99_position_code"]))
    _write_decoded_byte(patched, name_end + 9, int(source_row["birth_day"]))
    _write_decoded_byte(patched, name_end + 10, int(source_row["birth_month"]))
    year_bytes = struct.pack("<H", int(source_row["birth_year"]))
    _write_decoded_byte(patched, name_end + 11, year_bytes[0])
    _write_decoded_byte(patched, name_end + 12, year_bytes[1])
    _write_decoded_byte(patched, name_end + 13, int(source_row["height_cm"]))
    _write_decoded_byte(patched, name_end + 14, int(source_row["weight_kg"]))
    for index, label in enumerate(SKILL_LABELS):
        _write_decoded_byte(patched, name_end + 15 + index, int(source_row["skills"][label]))

    after = _read_clone_fields(bytes(patched), name_end)
    reparsed = PlayerRecord.from_bytes(bytes(patched), 0)
    if _norm(str(getattr(reparsed, "name", "") or "")) != _norm(str(getattr(parsed, "name", "") or "")):
        raise RuntimeError(f"Name changed while patching {source_row['source_name']}")
    if len(patched) != len(decoded):
        raise RuntimeError(f"Payload length changed for {source_row['source_name']}")
    return bytes(patched), before, after, name_end


def apply_semantic_patch(game_root: Path, sources: list[ClubSource], output_dir: Path) -> dict[str, Any]:
    player_file = game_root / "DBDAT" / "JUG98030.FDI"
    team_file = game_root / "DBDAT" / "EQ98030.FDI"
    coach_file = game_root / "DBDAT" / "ENT98030.FDI"
    textos_file = game_root / "DBDAT" / "TEXTOS.PKF"
    manifest_path = game_root / "repointed_roster_manifest.json"
    for path in (player_file, team_file, coach_file, textos_file, manifest_path):
        if not path.is_file():
            raise RuntimeError(f"Missing required file: {path}")

    source_rows = {(source.club_key, int(player["slot"])): {**player, "club_key": source.club_key, "club_name": source.display_name} for source in sources for player in source.players}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    file_bytes = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(file_bytes)
    entries_by_id = {int(entry.record_id): entry for entry in indexed.entries}
    patched_file = bytearray(file_bytes)
    ledger_rows: list[dict[str, Any]] = []
    readback_rows: list[dict[str, Any]] = []

    for allocation in manifest.get("allocations", []):
        club_key = str(allocation["club_key"])
        slot = int(allocation["slot"])
        source_row = dict(source_rows[(club_key, slot)])
        record_id = int(allocation["new_record_id"])
        entry = entries_by_id.get(record_id)
        if entry is None:
            raise RuntimeError(f"Allocation record {record_id} missing from JUG")
        decoded = entry.decode_payload(file_bytes)
        parsed = PlayerRecord.from_bytes(decoded, int(entry.payload_offset))
        parsed_name = " ".join(str(getattr(parsed, "name", "") or "").split())
        expected_runtime_name = str(source_row["runtime_safe_name"])
        if _norm(parsed_name) != _norm(expected_runtime_name):
            raise RuntimeError(
                f"{club_key} slot {slot} expected {expected_runtime_name!r}, "
                f"but JUG record {record_id} parses as {parsed_name!r}"
            )
        patched, before, after, name_end = _patch_clone_payload(decoded, source_row)
        encoded = xor_encode(patched)
        if len(encoded) != int(entry.payload_length):
            raise RuntimeError(f"{club_key} slot {slot} encoded length changed")
        start = int(entry.payload_offset)
        patched_file[start : start + int(entry.payload_length)] = encoded

        expected_after = {
            "ui_primary_role_code": int(list(source_row["fine_role_codes"])[0]),
            "visible_nationality_code": int(source_row["pm99_nat_code"]),
            "parser_position_code": int(source_row["pm99_position_code"]),
            "visible_position_code": int(source_row["pm99_position_code"]),
            "birth_day": int(source_row["birth_day"]),
            "birth_month": int(source_row["birth_month"]),
            "birth_year": int(source_row["birth_year"]),
            "height_cm": int(source_row["height_cm"]),
            "weight_kg": int(source_row["weight_kg"]),
            "skills": dict(source_row["skills"]),
        }
        actual_subset = {key: after[key] for key in expected_after if key != "skills"}
        actual_subset["skills"] = dict(after["skills"])
        matches = actual_subset == expected_after
        readback_rows.append(
            {
                "club_key": club_key,
                "club_name": source_row["club_name"],
                "slot": slot,
                "pid": record_id,
                "runtime_name": parsed_name,
                "source_name": source_row["source_name"],
                "payload_offset": int(entry.payload_offset),
                "payload_length": int(entry.payload_length),
                "name_end": int(name_end),
                "before": before,
                "expected_after": expected_after,
                "actual_after": actual_subset,
                "matches": bool(matches),
            }
        )
        ledger_rows.append(
            {
                **source_row,
                "pid": record_id,
                "runtime_name": parsed_name,
                "payload_offset": int(entry.payload_offset),
                "payload_length": int(entry.payload_length),
                "name_end": int(name_end),
                "readback_ok": bool(matches),
            }
        )

    backup_path = player_file.with_suffix(player_file.suffix + f".english80_semantic_backup_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}")
    shutil.copy2(player_file, backup_path)
    player_file.write_bytes(bytes(patched_file))
    reparsed_index = IndexedFDIFile.from_path(player_file)
    if len(reparsed_index.entries) != len(indexed.entries):
        raise RuntimeError("Indexed JUG entry count changed after semantic patch")

    source_json = output_dir / "english80_semantic_source_ledger.json"
    source_csv = output_dir / "english80_semantic_source_ledger.csv"
    readback_json = output_dir / "english80_semantic_readback.json"
    fieldnames = [
        "club_key",
        "club_name",
        "slot",
        "pid",
        "runtime_name",
        "source_name",
        "source_number",
        "source_nat_abbr",
        "pm99_nat_label",
        "pm99_nat_code",
        "source_position",
        "pm99_position_label",
        "dob_source",
        "real_birth_day",
        "real_birth_month",
        "real_birth_year",
        "birth_day",
        "birth_month",
        "birth_year",
        "height_cm",
        "weight_kg",
        *SKILL_LABELS,
        "attribute_basis",
        "source_url",
        "readback_ok",
    ]
    _json_dump(source_json, ledger_rows)
    with source_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in ledger_rows:
            flat = dict(row)
            flat.update(row.get("skills") or {})
            writer.writerow({key: flat.get(key, "") for key in fieldnames})
    _json_dump(readback_json, readback_rows)
    semantic_manifest = {
        "schema": "pm99-english80-footballsquads-semantic-patch-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "game_root": str(game_root),
        "row_count": len(readback_rows),
        "readback_ok": all(bool(row["matches"]) for row in readback_rows),
        "backup_path": str(backup_path),
        "source_json": str(source_json),
        "source_csv": str(source_csv),
        "readback_json": str(readback_json),
        "input_hashes": {
            "EQ98030.FDI": sha256(team_file),
            "JUG98030.FDI": sha256(player_file),
            "ENT98030.FDI": sha256(coach_file),
            "TEXTOS.PKF": sha256(textos_file),
        },
    }
    _json_dump(output_dir / "english80_semantic_manifest.json", semantic_manifest)
    return semantic_manifest


def cap_target_rosters_to_twenty(game_root: Path, assignment_path: Path, output_dir: Path) -> dict[str, Any]:
    team_file = game_root / "DBDAT" / "EQ98030.FDI"
    assignment = json.loads(assignment_path.read_text(encoding="utf-8"))
    target_eq = {
        int(item["carrier_eq_record_id"]): str(item.get("target_club_key") or item.get("club_key") or "")
        for item in assignment.get("assignments", [])
        if int(item.get("carrier_eq_record_id") or 0) > 0
    }
    team_data = team_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(team_data)
    entries_by_id = {int(entry.record_id): entry for entry in indexed.entries}
    raw_payload_by_offset: dict[int, bytes] = {}
    events: list[dict[str, Any]] = []
    for eq_record_id, club_key in sorted(target_eq.items()):
        entry = entries_by_id.get(eq_record_id)
        if entry is None:
            raise RuntimeError(f"Missing target EQ record {eq_record_id} for {club_key}")
        raw_payload = bytearray(
            team_data[int(entry.payload_offset) : int(entry.payload_offset) + int(entry.payload_length)]
        )
        layout = _linked_roster_layout(bytes(raw_payload))
        if layout is None:
            raise RuntimeError(f"Could not parse linked roster layout for EQ {eq_record_id} ({club_key})")
        old_count = int(layout["player_count"])
        if old_count > 20:
            raw_payload[int(layout["player_count_offset"])] = 20
            raw_payload_by_offset[int(entry.payload_offset)] = bytes(raw_payload)
            events.append(
                {
                    "club_key": club_key,
                    "carrier_eq_record_id": eq_record_id,
                    "old_player_count": old_count,
                    "new_player_count": 20,
                }
            )
    if raw_payload_by_offset:
        _write_raw_indexed_payloads(team_file, raw_payload_by_offset, create_backup=False)
    manifest = {
        "schema": "pm99-english80-roster-count-cap-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "game_root": str(game_root),
        "team_file": str(team_file),
        "assignment": str(assignment_path),
        "target_team_count": len(target_eq),
        "capped_count": len(events),
        "events": events,
    }
    _json_dump(output_dir / "english80_roster_count_cap_manifest.json", manifest)
    return manifest


def build_candidate(args: argparse.Namespace) -> dict[str, Any]:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else (Path(args.output_root).expanduser().resolve() / f"english80_2026_football_squads_{timestamp}")
    if output_dir.exists():
        if not args.force:
            raise FileExistsError(f"Output directory already exists: {output_dir}")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    game_root = output_dir / "game"

    base_assignment_path = Path(args.base_assignment).expanduser().resolve()
    base_world_path = Path(args.base_world).expanduser().resolve()
    base_game = Path(args.base_game).expanduser().resolve()
    base_assignment = json.loads(base_assignment_path.read_text(encoding="utf-8"))
    base_world = json.loads(base_world_path.read_text(encoding="utf-8"))
    country_codes = _extract_nationality_codes(base_game / "DBDAT" / "TEXTOS.PKF")

    sources, league_links = scrape_sources(country_codes, base_assignment=base_assignment)
    unknown_nats = sorted(
        {
            player["source_nat_abbr"]
            for source in sources
            for player in source.players
            if player["pm99_nat_label"] == "XXX" and player["source_nat_abbr"] != ""
        }
    )
    if unknown_nats and not args.allow_unknown_nations:
        raise RuntimeError("Unmapped FootballSquads nationality abbreviations: " + ", ".join(unknown_nats))

    source_payload = {
        "schema": "pm99-english80-footballsquads-source-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source": "FootballSquads",
        "base_url": BASE_URL,
        "snapshot_date": SOURCE_SNAPSHOT_DATE,
        "club_count": len(sources),
        "player_count": sum(len(source.players) for source in sources),
        "unknown_nationalities": unknown_nats,
        "league_links": league_links,
        "clubs": [
            {
                "club_key": source.club_key,
                "display_name": source.display_name,
                "league_key": source.league_key,
                "league_name": source.league_name,
                "league_index": source.league_index,
                "source_url": source.source_url,
                "players": source.players,
            }
            for source in sources
        ],
    }
    source_path = output_dir / "football_squads_source_ledger.json"
    assignment_path = output_dir / "slot_assignment_english80_2026_football_squads.json"
    world_path = output_dir / "world_english80_2026_football_squads.json"
    _json_dump(source_path, source_payload)
    assignment = build_assignment(base_assignment, sources)
    _json_dump(assignment_path, assignment)
    world = build_world_state(base_world, sources)
    _json_dump(world_path, world)

    writable_base_game = output_dir / "base_game_writable"
    shutil.copytree(base_game, writable_base_game, symlinks=True)
    _make_tree_user_writable(writable_base_game)
    repointed_manifest = build_repointed_candidate(
        base_game=writable_base_game,
        assignment_path=assignment_path,
        out_game=game_root,
        force=True,
    )
    roster_cap_manifest = cap_target_rosters_to_twenty(game_root, assignment_path, output_dir)
    semantic_manifest = apply_semantic_patch(game_root, sources, output_dir)
    manifest = {
        "schema": "pm99-english80-footballsquads-build-manifest-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "ok": bool(repointed_manifest.get("ok")) and bool(semantic_manifest.get("readback_ok")),
        "output_dir": str(output_dir),
        "game_root": str(game_root),
        "base_game": str(base_game),
        "writable_base_game": str(writable_base_game),
        "base_assignment": str(base_assignment_path),
        "base_world": str(base_world_path),
        "source_ledger": str(source_path),
        "assignment": str(assignment_path),
        "world_state": str(world_path),
        "repointed_manifest": str(game_root / "repointed_roster_manifest.json"),
        "semantic_manifest": str(output_dir / "english80_semantic_manifest.json"),
        "roster_count_cap_manifest": str(output_dir / "english80_roster_count_cap_manifest.json"),
        "club_count": len(sources),
        "player_count": sum(len(source.players) for source in sources),
        "unknown_nationalities": unknown_nats,
        "repointed_ok": bool(repointed_manifest.get("ok")),
        "roster_count_capped": int(roster_cap_manifest["capped_count"]),
        "semantic_readback_ok": bool(semantic_manifest.get("readback_ok")),
    }
    _json_dump(output_dir / "english80_build_manifest.json", manifest)
    return manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-assignment", default=str(DEFAULT_BASE_ASSIGNMENT))
    parser.add_argument("--base-world", default=str(DEFAULT_BASE_WORLD))
    parser.add_argument("--base-game", default=str(DEFAULT_BASE_GAME))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--allow-unknown-nations", action="store_true")
    return parser.parse_args()


def main() -> int:
    manifest = build_candidate(_parse_args())
    print(
        json.dumps(
            {
                "ok": manifest["ok"],
                "output_dir": manifest["output_dir"],
                "game_root": manifest["game_root"],
                "club_count": manifest["club_count"],
                "player_count": manifest["player_count"],
                "unknown_nationalities": manifest["unknown_nationalities"],
                "source_ledger": manifest["source_ledger"],
                "assignment": manifest["assignment"],
                "world_state": manifest["world_state"],
                "semantic_manifest": manifest["semantic_manifest"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if manifest["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
