#!/usr/bin/env python3
"""Build a 2025-26 top-80 English roster world-state for PM99.

The generated world-state deliberately uses existing PM99 linked roster rows as
carrier records. Runtime-safe game-ready builds update player identities while
leaving EQ team-name fields unchanged unless team renames are explicitly opted
in for investigation.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
EDITOR_ROOT = REPO_ROOT / "upstream" / "pm99-skezmod-db-editor"
if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from app.editor_helpers import team_query_matches  # noqa: E402
from app.editor_actions import (  # noqa: E402
    _LINKED_RUNTIME_MIN_CERTIFIABLE_PLAYER_PAYLOAD_LENGTH,
    _collect_roundtrip_unsupported_fields,
)
from app.eq_jug_linked import EQLinkedTeamRoster, load_eq_linked_team_rosters  # noqa: E402
from app.fdi_indexed import IndexedFDIFile  # noqa: E402
from app.file_writer import replace_player_name_preserving_layout  # noqa: E402
from app.loaders import load_teams  # noqa: E402
from app.models import PlayerRecord  # noqa: E402
from app.xor import read_string, write_string  # noqa: E402
from pm99_world_state import SCHEMA_ID, SELECTOR_MAP_SCHEMA_ID, load_selector_map, sha256  # noqa: E402

WIKI_API = "https://en.wikipedia.org/w/api.php"
SEASON_PREFIX = "2025\u201326"
DEFAULT_CACHE_DIR = REPO_ROOT / ".local" / "cache" / "pm99_2025_wiki"
DEFAULT_OUTPUT_DIR = REPO_ROOT / ".local" / "pm99_2025_roster_world"
DEFAULT_SELECTOR_MAP = REPO_ROOT / ".local" / "selector_maps" / "pm99_vanilla_english_80_selector_map.json"
DEFAULT_GAME_ROOT = REPO_ROOT
HTTP_USER_AGENT = "pm99-research/2025-roster-world-state (local research)"

LEAGUES = [
    ("premier_league", "Premier League", "2025\u201326 Premier League", 20),
    ("championship", "EFL Championship", "2025\u201326 EFL Championship", 24),
    ("league_one", "EFL League One", "2025\u201326 EFL League One", 24),
    ("league_two", "EFL League Two", "2025\u201326 EFL League Two", 12),
]

RUNTIME_ROUTES = ["squad", "line_up", "tactics", "results", "league_tables", "fixtures"]
AUDIT_IDENTITY_FULL_NAME_CLUB_KEYS = {
    "coventry_city",
    "liverpool",
    "nottingham_forest",
    "wolverhampton_wanderers",
}


@dataclass(frozen=True)
class WikiPage:
    title: str
    pageid: int
    wikitext: str
    url: str


@dataclass(frozen=True)
class ClubSource:
    league_key: str
    league_name: str
    display_name: str
    wiki_target: str
    season_title: str
    source_url: str
    roster_source_title: str
    roster_source_url: str
    roster_source_kind: str
    roster_players: list[str]


@dataclass(frozen=True)
class SparePlayerRecord:
    record_id: int
    current_name: str
    payload_offset: int
    payload_length: int
    decoded_payload: bytes


@dataclass(frozen=True)
class PlayerCarrierRecord:
    record_id: int
    current_name: str
    payload_offset: int
    payload_length: int
    decoded_payload: bytes


@dataclass(frozen=True)
class _SpareCandidate:
    block_capacity: int
    text_capacity: int
    alias_capacity: int
    spare: SparePlayerRecord


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _slug(value: str) -> str:
    value = _ascii_text(value).casefold()
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    return value or "unknown"


def _ascii_text(value: str) -> str:
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


def _strip_templates(value: str) -> str:
    text = str(value or "")
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"\{\{[^{}]*\}\}", " ", text)
    return text


def _clean_markup(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"<ref\b[^>/]*/>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<ref\b.*?</ref>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _strip_templates(text)
    text = re.sub(r"'{2,}", "", text)
    text = re.sub(r"\[\[([^|\]]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    return _ascii_text(text)


def _strip_cell_attributes(cell: str) -> str:
    text = str(cell or "").strip()
    if "[[" in text:
        return text
    if "|" in text:
        prefix, rest = text.split("|", 1)
        if "=" in prefix or prefix.strip().casefold() in {"align", "style", "scope", "data-sort-value"}:
            return rest.strip()
    return text


def _extract_first_link(value: str) -> tuple[str, str] | None:
    text = str(value or "")
    text = re.sub(r"\{\{\s*[Ff]lag(?:icon)?[^{}]*\}\}", " ", text)
    for match in re.finditer(r"\[\[([^|\]#]+)(?:#[^|\]]*)?(?:\|([^\]]+))?\]\]", text):
        target = _clean_markup(match.group(1))
        display = _clean_markup(match.group(2) or match.group(1))
        if not target or not display:
            continue
        lowered = target.casefold()
        if lowered.startswith(("file:", "image:", "category:")):
            continue
        return target, display
    return None


def _split_top_level_rows(table: str) -> list[str]:
    rows: list[str] = []
    current: list[str] = []
    for line in table.splitlines():
        stripped = line.strip()
        if stripped.startswith("|-"):
            if current:
                rows.append("\n".join(current))
            current = []
            continue
        if stripped.startswith("|}"):
            break
        current.append(line)
    if current:
        rows.append("\n".join(current))
    return rows


def _row_cells(row: str) -> list[str]:
    cells: list[str] = []
    for line in row.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("{|", "|}", "|-")):
            continue
        if stripped[0] not in {"|", "!"}:
            continue
        body = stripped[1:].strip()
        if not body:
            continue
        separator = "!!" if stripped[0] == "!" else "||"
        for part in body.split(separator):
            part = _strip_cell_attributes(part)
            if part:
                cells.append(part)
    return cells


def _extract_tables(wikitext: str) -> list[str]:
    tables: list[str] = []
    cursor = 0
    while True:
        start = wikitext.find("{|", cursor)
        if start < 0:
            break
        end = wikitext.find("|}", start)
        if end < 0:
            break
        tables.append(wikitext[start : end + 2])
        cursor = end + 2
    return tables


class WikiClient:
    def __init__(self, cache_dir: Path, *, refresh: bool = False):
        self.cache_dir = cache_dir
        self.refresh = refresh
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": HTTP_USER_AGENT})

    def fetch_page(self, title: str) -> WikiPage | None:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", title).strip("_")
        cache_path = self.cache_dir / f"{safe}.json"
        if cache_path.exists() and not self.refresh:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        else:
            payload = self._fetch_payload(title)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            time.sleep(0.05)
        page = next(iter(payload.get("query", {}).get("pages", {}).values()), {})
        if "missing" in page:
            return None
        revisions = page.get("revisions") or []
        if not revisions:
            return None
        wikitext = revisions[0].get("slots", {}).get("main", {}).get("*", "")
        if not wikitext:
            return None
        canonical = str(page.get("title") or title)
        return WikiPage(
            title=canonical,
            pageid=int(page.get("pageid") or 0),
            wikitext=wikitext,
            url=f"https://en.wikipedia.org/wiki/{canonical.replace(' ', '_')}",
        )

    def _fetch_payload(self, title: str) -> dict[str, Any]:
        params = {
            "action": "query",
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
            "format": "json",
            "redirects": "1",
            "titles": title,
        }
        last_error: Exception | None = None
        for attempt, delay in enumerate([2, 5, 10, 20, 40], start=1):
            response = self.session.get(WIKI_API, params=params, timeout=30)
            if response.status_code != 429:
                response.raise_for_status()
                return response.json()
            last_error = requests.HTTPError(f"429 Too Many Requests fetching {title!r}", response=response)
            retry_after = response.headers.get("Retry-After")
            try:
                sleep_for = max(delay, int(retry_after)) if retry_after else delay
            except ValueError:
                sleep_for = delay
            if attempt < 5:
                time.sleep(sleep_for)
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Failed to fetch {title!r}")


def extract_league_clubs(page: WikiPage, *, league_key: str, league_name: str, limit: int) -> list[dict[str, str]]:
    for table in _extract_tables(page.wikitext):
        if "wikitable" not in table or "Stadium" not in table or "Capacity" not in table:
            continue
        clubs: list[dict[str, str]] = []
        seen: set[str] = set()
        for row in _split_top_level_rows(table):
            cells = _row_cells(row)
            if len(cells) < 2:
                continue
            first = cells[0]
            link = _extract_first_link(first)
            if link is None:
                continue
            target, display = link
            key = _slug(display)
            if key in seen:
                continue
            seen.add(key)
            clubs.append(
                {
                    "league_key": league_key,
                    "league_name": league_name,
                    "display_name": display,
                    "wiki_target": target,
                    "league_source_title": page.title,
                    "league_source_url": page.url,
                }
            )
        if len(clubs) >= limit:
            return clubs[:limit]
    raise RuntimeError(f"Could not extract {limit} clubs from {page.title}")


def _season_title_candidates(wiki_target: str, display_name: str) -> list[str]:
    candidates = [
        f"{SEASON_PREFIX} {wiki_target} season",
        f"{SEASON_PREFIX} {display_name} season",
    ]
    if not re.search(r"\bF\.?C\.?$|\bA\.?F\.?C\.?$", display_name):
        candidates.append(f"{SEASON_PREFIX} {display_name} F.C. season")
    if wiki_target.endswith(" F.C.") and display_name != wiki_target[:-5]:
        candidates.append(f"{SEASON_PREFIX} {wiki_target[:-5]} F.C. season")
    unique: list[str] = []
    for item in candidates:
        if item not in unique:
            unique.append(item)
    return unique


def _parse_squad_template_players(wikitext: str) -> list[tuple[int | None, str]]:
    players: list[tuple[int | None, str]] = []
    squad_start = re.search(r"\{\{\s*(?:[Ff]s|[Ff]ootball squad) start\s*\}\}", wikitext)
    if squad_start:
        squad_end = re.search(r"\{\{\s*(?:[Ff]s|[Ff]ootball squad) end\s*\}\}", wikitext[squad_start.start() :])
        if squad_end:
            wikitext = wikitext[squad_start.start() : squad_start.start() + squad_end.end()]
    for match in re.finditer(r"\{\{\s*(?:[Ff]s|[Ff]ootball squad) player\b(?P<body>.*?)\n?\}\}", wikitext, flags=re.DOTALL):
        body = match.group("body")
        no_match = re.search(r"\|\s*(?:no|num|number)\s*=\s*([^|\n}]+)", body, flags=re.IGNORECASE)
        number = int(no_match.group(1).strip()) if no_match and no_match.group(1).strip().isdigit() else None
        name_match = re.search(r"\|\s*name\s*=\s*(.+?)(?=\|\s*[a-zA-Z_]+\s*=|$)", body, flags=re.DOTALL)
        if not name_match:
            continue
        raw_name = name_match.group(1)
        link = _extract_first_link(raw_name)
        name = link[1] if link else _clean_markup(raw_name)
        if name:
            players.append((number, name))
    return players


def _looks_like_player_table(table: str) -> bool:
    normalized = _clean_markup(table).casefold()
    return ("name" in normalized or "player" in normalized) and (
        "pos" in normalized or "position" in normalized or "appearances" in normalized or "apps" in normalized
    )


def _extract_number(cell: str) -> int | None:
    text = _clean_markup(cell)
    match = re.fullmatch(r"\D*(\d{1,3})\D*", text)
    if not match:
        return None
    number = int(match.group(1))
    return number if 0 < number < 100 else None


def _parse_player_tables(wikitext: str) -> list[tuple[int | None, str]]:
    players: list[tuple[int | None, str]] = []
    for table in _extract_tables(wikitext):
        if not _looks_like_player_table(table):
            continue
        name_index: int | None = None
        for row in _split_top_level_rows(table):
            cells = _row_cells(row)
            if len(cells) < 3:
                continue
            cleaned_cells = [_clean_markup(cell).casefold() for cell in cells]
            if name_index is None:
                for idx, cleaned in enumerate(cleaned_cells):
                    if cleaned in {"name", "player"} or cleaned.endswith("|name") or cleaned.endswith("|player"):
                        name_index = idx
                        break
                if name_index is None and any("name" in cleaned or "player" in cleaned for cleaned in cleaned_cells):
                    continue
            number = _extract_number(cells[0])
            if number is None:
                continue
            name = ""
            candidate_cells = [cells[name_index]] if name_index is not None and name_index < len(cells) else cells[1:7]
            for cell in candidate_cells:
                cleaned_cell = re.sub(r"\{\{\s*[Ff]lag(?:icon)?[^{}]*\}\}", " ", cell)
                link = _extract_first_link(cleaned_cell)
                candidate = link[1] if link else ""
                if not candidate:
                    continue
                candidate_l = candidate.casefold()
                target_l = (link[0] if link else "").casefold()
                if any(token in candidate_l or token in target_l for token in ["football club", " f.c.", " a.f.c.", "stadium"]):
                    continue
                name = candidate
                break
            if name:
                players.append((number, name))
    return players


def extract_roster_players(page: WikiPage) -> list[str]:
    numbered = [*_parse_squad_template_players(page.wikitext), *_parse_player_tables(page.wikitext)]
    deduped: list[tuple[int | None, str]] = []
    seen: set[str] = set()
    for number, raw_name in numbered:
        name = fit_player_name(raw_name)
        key = _slug(name)
        if not name or key in seen:
            continue
        seen.add(key)
        deduped.append((number, name))
    deduped.sort(key=lambda item: (item[0] is None, item[0] or 999, item[1]))
    return [name for _, name in deduped]


def fit_player_name(raw_name: str, *, max_chars: int = 60) -> str:
    name = _ascii_text(_clean_markup(raw_name))
    name = re.sub(r"\s+\([^)]*\)$", "", name).strip()
    name = re.sub(r"\s+", " ", name)
    if len(name) <= max_chars:
        parts = name.split()
        if len(parts) == 1:
            return f"{name} Player"[:max_chars].rstrip()
        return name
    parts = name.split()
    if len(parts) >= 2:
        abbreviated = f"{parts[0][0]}. {' '.join(parts[1:])}"
        if len(abbreviated) <= max_chars:
            return abbreviated
    fitted = name[:max_chars].rstrip()
    if len(fitted.split()) == 1:
        fitted = f"{fitted} Player"[:max_chars].rstrip()
    return fitted


def fit_team_name(raw_name: str, *, max_chars: int = 60) -> str:
    name = _ascii_text(raw_name)
    replacements = {
        "AFC Wimbledon": "AFC Wimb",
        "Brighton & Hove Albion": "Brighton",
        "Manchester United": "Manchester Utd.",
        "Manchester City": "Man City",
        "Newcastle United": "Newcastle",
        "Nottingham Forest": "Nottingham F",
        "Tottenham Hotspur": "Tottenham",
        "Wolverhampton Wanderers": "Wolves",
        "West Bromwich Albion": "West Brom",
        "Queens Park Rangers": "QPR",
        "Sheffield Wednesday": "Sheff Wed",
        "Sheffield United": "Sheffield U",
        "Milton Keynes Dons": "MK Dons",
        "Burton Albion": "Burton",
        "Bradford City": "Bradford",
        "Bristol Rovers": "Bristol R",
        "Cheltenham Town": "Cheltenham",
        "Accrington Stanley": "Accrington",
        "Blackburn Rovers": "Blackburn R",
        "Bolton Wanderers": "Bolton W",
        "Cambridge United": "Cambridge",
        "Cardiff City": "Cardiff C",
        "Charlton Athletic": "Charlton Ath",
        "Colchester United": "Colchester",
        "Doncaster Rovers": "Doncaster",
        "Fleetwood Town": "Fleetwood",
        "Huddersfield Town": "Huddersfield",
        "Leicester City": "Leicester",
        "Lincoln City": "Lincoln C",
        "Northampton Town": "Northampton",
        "Oxford United": "Oxford Utd",
        "Peterborough United": "Peterboro",
        "Plymouth Argyle": "Plymouth",
        "Preston North End": "Preston NE",
        "Rotherham United": "Rotherham",
        "Stockport County": "Stockport C",
        "Swansea City": "Swansea",
        "West Ham United": "West Ham",
        "Wigan Athletic": "Wigan Ath",
        "Wycombe Wanderers": "Wycombe W",
    }
    name = replacements.get(name, name)
    return name[:max_chars].rstrip()


def fit_full_club_name(raw_name: str, *, max_chars: int = 60) -> str:
    name = _ascii_text(raw_name)
    if not name:
        return ""
    replacements = {
        "AFC Wimbledon": "AFC Wimb",
        "Brighton & Hove Albion": "Brighton",
        "Manchester United": "Man Utd",
        "Manchester City": "Man City",
        "Newcastle United": "Newcastle",
        "Nottingham Forest": "Nottm Fo",
        "Tottenham Hotspur": "Tottenham",
        "Wolverhampton Wanderers": "Wolves",
        "West Bromwich Albion": "West Brom",
        "Queens Park Rangers": "QPR",
        "Sheffield Wednesday": "Sheff Wed",
        "Sheffield United": "Sheffield",
        "Coventry City": "Coventry",
    }
    candidates = [name]
    if not name.casefold().endswith(("football club", "f.c.", "fc")):
        candidates.append(f"{name} Football Club")
    replacement = replacements.get(name)
    if replacement:
        candidates.insert(0, replacement)
    for candidate in candidates:
        if len(candidate) <= max_chars:
            return candidate
    return name[:max_chars].rstrip()


def _player_display_name(record: PlayerRecord) -> str:
    name = str(getattr(record, "name", "") or "").strip()
    if not name:
        name = " ".join(
            part
            for part in (
                str(getattr(record, "given_name", "") or "").strip(),
                str(getattr(record, "surname", "") or "").strip(),
            )
            if part
        )
    return " ".join(name.split()) or "Unknown Player"


def _normalized_player_name(value: str) -> str:
    return " ".join(_ascii_text(value).casefold().split())


def _encode_pm99_text(value: str) -> bytes:
    try:
        return str(value or "").encode("latin-1")
    except UnicodeEncodeError:
        return str(value or "").encode("cp1252", errors="replace")


def _surname_token(value: str) -> str:
    parts = " ".join(str(value or "").split()).split()
    return parts[-1].strip(" .'-") if parts else ""


def _has_runtime_alias_suffix_bleed(value: str) -> bool:
    """Reject parser names where adjacent runtime bytes appear appended."""
    surname = _surname_token(value)
    if re.fullmatch(r"[A-Z][a-z]{3,}(?:ja|ka|ua|va|ya)", surname):
        return True
    # In the PM99 source DB, runtime-safe surname labels are overwhelmingly
    # uppercase. Repeated runner failures came from Titlecase spare surnames
    # where parser text had swallowed adjacent runtime bytes.
    return bool(re.fullmatch(r"[A-Z][a-z]{4,}", surname))


def _player_runtime_alias_safe(original_payload: bytes, modified_payload: bytes, old_name: str, target_name: str) -> bool:
    old_surname = _normalized_player_name(_surname_token(old_name))
    target_surname = _normalized_player_name(_surname_token(target_name))
    if not old_surname or not target_surname:
        return False
    prefix = modified_payload[: min(len(modified_payload), 128)].decode("cp1252", errors="ignore")
    normalized_prefix = _normalized_player_name(prefix)
    if target_surname not in normalized_prefix:
        return False
    original_prefix = original_payload[: min(len(original_payload), 128)].decode("cp1252", errors="ignore")
    normalized_original_prefix = _normalized_player_name(original_prefix)
    # If the old surname was not represented in the runtime alias prefix, do
    # not require it to disappear; some payload families only expose full-name
    # text to the parser. When it was present, the alias must now change.
    return old_surname not in normalized_original_prefix or old_surname not in normalized_prefix


def _player_name_layout_safe(carrier: PlayerCarrierRecord | SparePlayerRecord, target_name: str) -> bool:
    if int(carrier.payload_length) < int(_LINKED_RUNTIME_MIN_CERTIFIABLE_PLAYER_PAYLOAD_LENGTH):
        return False
    if "'" in str(target_name):
        return False
    if _has_runtime_alias_suffix_bleed(str(carrier.current_name)):
        return False
    try:
        original_record = PlayerRecord.from_bytes(bytes(carrier.decoded_payload), int(carrier.payload_offset))
    except Exception:
        return False
    unsupported_fields = _collect_roundtrip_unsupported_fields(
        original_record,
        offset=int(carrier.payload_offset),
        new_name=str(target_name),
        position=None,
        nationality=None,
        birth_day=None,
        birth_month=None,
        birth_year=None,
        age=None,
        height=None,
        weight=None,
        attribute_updates={},
        allow_unresolved_attributes=False,
        age_reference_year=1999,
        overlap_write_policy="composite_guarded",
    )
    if unsupported_fields:
        return False
    modified, ok = replace_player_name_preserving_layout(
        bytes(carrier.decoded_payload),
        str(carrier.current_name),
        str(target_name),
    )
    if not ok or len(modified) != len(carrier.decoded_payload):
        return False
    try:
        reparsed = PlayerRecord.from_bytes(bytes(modified), int(carrier.payload_offset))
    except Exception:
        return False
    return (
        _normalized_player_name(_player_display_name(reparsed)) == _normalized_player_name(target_name)
        and _player_runtime_alias_safe(bytes(carrier.decoded_payload), bytes(modified), str(carrier.current_name), str(target_name))
    )


def _player_name_block_capacity(decoded_payload: bytes) -> int:
    try:
        pos = 5
        _given, consumed1 = read_string(decoded_payload, pos)
        pos += consumed1
        _surname, consumed2 = read_string(decoded_payload, pos)
    except Exception:
        return 0
    return int(consumed1 + consumed2)


def _player_name_text_capacity(decoded_payload: bytes, current_name: str) -> int:
    old_bytes = _encode_pm99_text(current_name)
    if not old_bytes:
        return 0
    best = 0
    start = 0
    while True:
        idx = decoded_payload.find(old_bytes, start)
        if idx < 0:
            break
        end = idx + len(old_bytes)
        slack = 0
        while end + slack < len(decoded_payload) and decoded_payload[end + slack] in (0x00, 0x20):
            slack += 1
        best = max(best, len(old_bytes) + slack)
        start = idx + 1
    return best


def _player_runtime_alias_capacity(decoded_payload: bytes, current_name: str) -> int:
    old_surname = _surname_token(current_name)
    if not old_surname:
        return 0
    prefix = decoded_payload[: min(len(decoded_payload), 128)]
    prefix_text = prefix.decode("cp1252", errors="ignore")
    match_index = prefix_text.casefold().find(old_surname.casefold())
    if match_index < 0:
        return 0
    token_text = prefix_text[match_index : match_index + len(old_surname)]
    return len(_encode_pm99_text(token_text))


def _target_name_text_size(target_name: str) -> int:
    return len(_encode_pm99_text(target_name))


def _target_name_block_size(target_name: str) -> int:
    parts = " ".join(str(target_name or "").split()).split(maxsplit=1)
    if len(parts) < 2:
        return 10**9
    try:
        return len(write_string(parts[0]) + write_string(parts[1]))
    except Exception:
        return 10**9


def _target_alias_size(target_name: str) -> int:
    surname = _surname_token(target_name)
    return len(_encode_pm99_text(surname)) if surname else 10**9


def _spare_record_pool_safe(spare: SparePlayerRecord) -> bool:
    """Keep expanded spare search to simple ASCII player identities."""
    if int(spare.payload_length) < int(_LINKED_RUNTIME_MIN_CERTIFIABLE_PLAYER_PAYLOAD_LENGTH):
        return False
    name = " ".join(str(spare.current_name or "").split())
    if not name or _ascii_text(name) != name:
        return False
    if _has_runtime_alias_suffix_bleed(name):
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9 .()'_-]+", name))


def _spare_candidate_can_fit_name(candidate: _SpareCandidate, target_name: str) -> bool:
    return (
        candidate.block_capacity >= _target_name_block_size(target_name)
        or candidate.text_capacity >= _target_name_text_size(target_name)
    )


def _find_layout_safe_spare(
    *,
    target_name: str,
    spare_candidates: list[_SpareCandidate],
    used_player_record_ids: set[int],
    spare_safety_cache: dict[tuple[int, str], bool],
) -> SparePlayerRecord | None:
    required_alias_size = _target_alias_size(target_name)
    normalized_target = _normalized_player_name(target_name)
    for candidate in spare_candidates:
        spare = candidate.spare
        if spare.record_id in used_player_record_ids:
            continue
        if candidate.alias_capacity < required_alias_size:
            continue
        if not _spare_candidate_can_fit_name(candidate, target_name):
            continue
        key = (int(spare.record_id), normalized_target)
        safe = spare_safety_cache.get(key)
        if safe is None:
            safe = _player_name_layout_safe(spare, target_name)
            spare_safety_cache[key] = safe
        if safe:
            return spare
    return None


def load_player_carrier_records(game_root: Path) -> dict[int, PlayerCarrierRecord]:
    player_file = game_root / "DBDAT" / "JUG98030.FDI"
    data = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(data)
    carriers: dict[int, PlayerCarrierRecord] = {}
    for entry in indexed.entries:
        record_id = int(entry.record_id)
        if record_id <= 0:
            continue
        try:
            payload = entry.decode_payload(data)
            record = PlayerRecord.from_bytes(payload, int(entry.payload_offset))
        except Exception:
            continue
        current_name = _player_display_name(record)
        if not current_name:
            continue
        carriers[record_id] = PlayerCarrierRecord(
            record_id=record_id,
            current_name=current_name,
            payload_offset=int(entry.payload_offset),
            payload_length=int(entry.payload_length),
            decoded_payload=bytes(payload),
        )
    return carriers


def load_spare_player_records(game_root: Path, excluded_record_ids: set[int]) -> list[SparePlayerRecord]:
    carrier_records = load_player_carrier_records(game_root)
    spares: list[SparePlayerRecord] = []
    for record_id in sorted(carrier_records):
        if record_id in excluded_record_ids or record_id <= 0:
            continue
        carrier = carrier_records[record_id]
        spares.append(
            SparePlayerRecord(
                record_id=record_id,
                current_name=carrier.current_name,
                payload_offset=carrier.payload_offset,
                payload_length=carrier.payload_length,
                decoded_payload=carrier.decoded_payload,
            )
        )
    return spares


def _find_roster_page(client: WikiClient, club: dict[str, str]) -> tuple[WikiPage, str]:
    for title in _season_title_candidates(club["wiki_target"], club["display_name"]):
        page = client.fetch_page(title)
        if page is None:
            continue
        players = extract_roster_players(page)
        if len(players) >= 20:
            return page, "season_page"
    fallback = client.fetch_page(club["wiki_target"])
    if fallback is not None and len(extract_roster_players(fallback)) >= 20:
        return fallback, "club_page_fallback"
    last = client.fetch_page(_season_title_candidates(club["wiki_target"], club["display_name"])[0])
    if last is not None:
        return last, "season_page_incomplete"
    raise RuntimeError(f"No roster page found for {club['display_name']} ({club['wiki_target']})")


def collect_club_sources(client: WikiClient) -> list[ClubSource]:
    clubs: list[ClubSource] = []
    for league_key, league_name, title, limit in LEAGUES:
        league_page = client.fetch_page(title)
        if league_page is None:
            raise RuntimeError(f"Missing league source page: {title}")
        league_clubs = extract_league_clubs(league_page, league_key=league_key, league_name=league_name, limit=limit)
        for row in league_clubs:
            roster_page, roster_kind = _find_roster_page(client, row)
            roster_players = extract_roster_players(roster_page)
            clubs.append(
                ClubSource(
                    league_key=league_key,
                    league_name=league_name,
                    display_name=row["display_name"],
                    wiki_target=row["wiki_target"],
                    season_title=f"{SEASON_PREFIX} {row['wiki_target']} season",
                    source_url=row["league_source_url"],
                    roster_source_title=roster_page.title,
                    roster_source_url=roster_page.url,
                    roster_source_kind=roster_kind,
                    roster_players=roster_players[:20],
                )
            )
    return clubs


def _find_carrier_roster(selector_row: dict[str, Any], rosters: list[EQLinkedTeamRoster]) -> EQLinkedTeamRoster | None:
    query = str(selector_row.get("team_query") or selector_row.get("team_name") or "").strip()
    query_key = _club_match_key(query)
    exact_candidates = [
        roster
        for roster in rosters
        if query_key
        and query_key
        in {
            _club_match_key(str(roster.short_name or "")),
            _club_match_key(str(roster.full_club_name or "")),
        }
    ]
    if exact_candidates:
        return exact_candidates[0]
    for roster in rosters:
        if team_query_matches(query, team_name=roster.short_name, full_club_name=roster.full_club_name):
            return roster
    normalized_query = _slug(query).replace("_", " ")
    candidates: list[tuple[float, EQLinkedTeamRoster]] = []
    for roster in rosters:
        for name in (roster.short_name, roster.full_club_name):
            normalized_name = _slug(name).replace("_", " ")
            if not normalized_name:
                continue
            score = difflib.SequenceMatcher(None, normalized_query, normalized_name).ratio()
            if score >= 0.72:
                candidates.append((score, roster))
    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]
    return None


def _club_match_key(value: str) -> str:
    text = _ascii_text(value).casefold().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    replacements = {
        "ath": "athletic",
        "c": "city",
        "cc": "county",
        "ha": "hove albion",
        "itd": "united",
        "litd": "united",
        "ne": "north end",
        "revers": "rovers",
        "rov": "rovers",
        "utd": "united",
        "w": "wanderers",
    }
    typo_replacements = {
        "carlisie": "carlisle",
        "chariton": "charlton",
        "nerthampton": "northampton",
    }
    tokens = []
    for token in text.split():
        token = typo_replacements.get(token, token)
        tokens.extend(replacements.get(token, token).split())
    return " ".join(tokens)


def _club_match_variants(value: str) -> set[str]:
    base = _club_match_key(value)
    out = {base} if base else set()
    fitted = fit_team_name(value)
    fitted_key = _club_match_key(fitted)
    if fitted_key:
        out.add(fitted_key)
    for suffix in (
        " athletic",
        " city",
        " county",
        " hotspur",
        " north end",
        " rovers",
        " town",
        " wanderers",
    ):
        if base.endswith(suffix):
            stripped = base[: -len(suffix)].strip()
            if stripped:
                out.add(stripped)
    custom = {
        "afc bournemouth": {"bournemouth"},
        "afc wimbledon": {"wimbledon"},
        "brighton and hove albion": {"brighton hove albion", "brighton"},
        "manchester city": {"manchester city"},
        "manchester united": {"manchester united"},
        "newcastle united": {"newcastle united", "newcastle"},
        "nottingham forest": {"nottingham forest", "nottingham"},
        "preston north end": {"preston north end", "preston"},
        "queens park rangers": {"qpr", "queens park rangers"},
        "tottenham hotspur": {"tottenham", "tottenham hotspur"},
        "west bromwich albion": {"west brom", "west bromwich albion"},
        "west ham united": {"west ham", "west ham united"},
        "wolverhampton wanderers": {"wolverhampton", "wolves"},
    }
    out.update(custom.get(base, set()))
    return {item for item in out if item}


def _selector_match_variants(selector_row: dict[str, Any]) -> set[str]:
    values = [
        str(selector_row.get("team_query") or ""),
        str(selector_row.get("team_name") or ""),
        str(selector_row.get("club_key") or "").replace("_", " "),
    ]
    out: set[str] = set()
    for value in values:
        out.update(_club_match_variants(value))
    return {item for item in out if item}


def _assign_selectors_to_sources(
    club_sources: list[ClubSource],
    selectors: list[dict[str, Any]],
) -> list[tuple[ClubSource, dict[str, Any], str]]:
    unused = set(range(len(selectors)))
    selector_variants = [_selector_match_variants(selector) for selector in selectors]
    assignments: list[tuple[int, str] | None] = [None] * len(club_sources)
    source_variants = [_club_match_variants(source.display_name) for source in club_sources]

    for source_index, variants in enumerate(source_variants):
        exact_indexes = [
            idx
            for idx in sorted(unused)
            if bool(variants & selector_variants[idx])
        ]
        if exact_indexes:
            chosen = exact_indexes[0]
            unused.remove(chosen)
            assignments[source_index] = (chosen, "identity_match")

    for source_index, variants in enumerate(source_variants):
        if assignments[source_index] is not None:
            continue
        scored: list[tuple[float, int]] = []
        for idx in sorted(unused):
            if not variants or not selector_variants[idx]:
                continue
            score = max(
                difflib.SequenceMatcher(None, source_value, selector_value).ratio()
                for source_value in variants
                for selector_value in selector_variants[idx]
            )
            scored.append((score, idx))
        scored.sort(key=lambda item: (item[0], -item[1]), reverse=True)
        if scored and scored[0][0] >= 0.88:
            chosen = scored[0][1]
            unused.remove(chosen)
            assignments[source_index] = (chosen, f"fuzzy_identity_match:{scored[0][0]:.3f}")

    for source_index, assignment in enumerate(assignments):
        if assignment is not None:
            continue
        chosen = min(unused)
        unused.remove(chosen)
        assignments[source_index] = (chosen, "ordered_fallback")

    return [
        (source, selectors[int(assignment[0])], str(assignment[1]))
        for source, assignment in zip(club_sources, assignments)
        if assignment is not None
    ]


def _unique_team_query_for_carrier(carrier: EQLinkedTeamRoster, parsed_teams: list[tuple[int, Any]]) -> str:
    def matches(query: str) -> list[str]:
        return [
            str(getattr(team, "name", "") or "")
            for _, team in parsed_teams
            if team_query_matches(
                query,
                team_name=str(getattr(team, "name", "") or ""),
                full_club_name=str(getattr(team, "full_club_name", "") or ""),
            )
        ]

    for query in (carrier.short_name, carrier.full_club_name):
        query = str(query or "").strip()
        if query and len(matches(query)) == 1:
            return query

    carrier_key = _slug(carrier.short_name).replace("_", "")
    for team_name in matches(carrier.short_name):
        if _slug(team_name).replace("_", "").startswith(carrier_key):
            return team_name

    return str(carrier.full_club_name or carrier.short_name).strip()


def build_world_state(
    club_sources: list[ClubSource],
    *,
    selector_map_path: Path,
    game_root: Path,
    output_dir: Path,
    include_team_renames: bool = False,
) -> dict[str, Any]:
    selector_map = load_selector_map(selector_map_path)
    selectors = sorted(
        list(selector_map["selectors"]),
        key=lambda row: (
            str((row.get("source") or {}).get("division_key") or ""),
            int((row.get("source") or {}).get("row_index") or 0),
            int(row.get("division_select_y") or 0),
            int(row.get("team_select_y") or 0),
            int(row.get("team_select_x") or 0),
        ),
    )
    if len(club_sources) != 80 or len(selectors) < 80:
        raise RuntimeError(f"Expected 80 club sources and selectors; got {len(club_sources)} sources, {len(selectors)} selectors")
    rosters = load_eq_linked_team_rosters(
        team_file=str(game_root / "DBDAT" / "EQ98030.FDI"),
        player_file=str(game_root / "DBDAT" / "JUG98030.FDI"),
    )
    parsed_teams = load_teams(str(game_root / "DBDAT" / "EQ98030.FDI"))
    player_carriers = load_player_carrier_records(game_root)
    # Spares only need to be unique within this generated 80-club world. The
    # wider PM99 database can still reference those records from non-target
    # clubs; those teams are outside the proven 80-slot selector milestone.
    spare_records = load_spare_player_records(game_root, set())
    spare_candidates = sorted(
        (
            _SpareCandidate(
                block_capacity=_player_name_block_capacity(spare.decoded_payload),
                text_capacity=_player_name_text_capacity(spare.decoded_payload, spare.current_name),
                alias_capacity=_player_runtime_alias_capacity(spare.decoded_payload, spare.current_name),
                spare=spare,
            )
            for spare in spare_records
            if _spare_record_pool_safe(spare)
        ),
        key=lambda item: (
            max(item.block_capacity, item.text_capacity),
            item.alias_capacity,
            item.spare.record_id,
        ),
    )
    spare_safety_cache: dict[tuple[int, str], bool] = {}
    direct_safety_cache: dict[tuple[int, str], bool] = {}

    clubs: list[dict[str, Any]] = []
    players: list[dict[str, Any]] = []
    squad_memberships: list[dict[str, Any]] = []
    assignments: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    name_fits: list[dict[str, Any]] = []
    used_player_record_ids: set[int] = set()

    selector_assignments = _assign_selectors_to_sources(club_sources, selectors[:80])

    for index, (source, selector, selector_assignment_reason) in enumerate(selector_assignments, start=1):
        club_key = _slug(source.display_name)
        carrier = _find_carrier_roster(selector, rosters)
        if carrier is None:
            blockers.append({"code": "carrier_roster_not_found", "slot": index, "team_query": selector.get("team_query"), "target": source.display_name})
            continue
        compile_team_query = _unique_team_query_for_carrier(carrier, parsed_teams)
        active_rows = [row for row in carrier.rows if int(row.player_record_id) > 0]
        target_row_count = min(len(active_rows), 20)
        if target_row_count <= 0:
            blockers.append({"code": "carrier_roster_empty", "slot": index, "team_query": selector.get("team_query"), "carrier_rows": len(active_rows)})
            continue
        if not source.roster_players:
            blockers.append({"code": "source_roster_empty", "slot": index, "target": source.display_name})
            continue
        selected_rows = active_rows[:target_row_count]
        target_players = [fit_player_name(name) for name in source.roster_players[:20]]
        assigned_target_indexes: set[int] = set()

        team_name_capacity = max(1, len(str(carrier.short_name or "").encode("latin-1", errors="replace")))
        full_club_name_capacity = max(1, len(str(carrier.full_club_name or "").encode("latin-1", errors="replace")))
        fitted_team_name = fit_team_name(source.display_name, max_chars=team_name_capacity)
        fitted_full_club_name = fit_full_club_name(source.display_name, max_chars=full_club_name_capacity)
        current_identity_variants = _club_match_variants(carrier.short_name) | _club_match_variants(carrier.full_club_name)
        target_identity_variants = _club_match_variants(source.display_name)
        fitted_name_is_existing_identity = _club_match_key(fitted_team_name) in current_identity_variants
        club_row = {
            "club_key": club_key,
            "team_query": compile_team_query,
            "selector_discovery_team_query": str(selector["team_query"]),
            "selector_assignment_reason": selector_assignment_reason,
            "source_league": source.league_name,
            "target_display_name": source.display_name,
            "target_wiki_page": source.roster_source_url,
            "runtime_routes": RUNTIME_ROUTES,
            "team_select_x": int(selector["team_select_x"]),
            "team_select_y": int(selector["team_select_y"]),
            "division_select_x": int(selector["division_select_x"]),
            "division_select_y": int(selector["division_select_y"]),
        }
        should_set_name = not (selector_assignment_reason == "identity_match" and fitted_name_is_existing_identity)
        if include_team_renames and should_set_name:
            club_row["set_name"] = fitted_team_name
        elif should_set_name:
            club_row["suppressed_set_name"] = fitted_team_name
            club_row["suppressed_set_name_reason"] = "team_renames_disabled_runtime_safety"
        should_set_full_name = (
            club_key in AUDIT_IDENTITY_FULL_NAME_CLUB_KEYS
            and not (selector_assignment_reason == "identity_match" and bool(target_identity_variants & current_identity_variants))
        )
        if include_team_renames and should_set_full_name:
            club_row["set_full_club_name"] = fitted_full_club_name
        elif should_set_full_name:
            club_row["suppressed_set_full_club_name"] = fitted_full_club_name
            club_row["suppressed_set_full_club_name_reason"] = "team_renames_disabled_runtime_safety"
        clubs.append(club_row)

        roster_assignment: list[dict[str, Any]] = []
        skipped_roster_slots: list[dict[str, Any]] = []
        for player_index, carrier_row in enumerate(selected_rows, start=1):
            original_record_id = int(carrier_row.player_record_id)
            original_carrier = player_carriers.get(original_record_id)
            if original_carrier is None:
                skipped_roster_slots.append(
                    {
                        "slot": int(carrier_row.slot_index) + 1,
                        "record_id": original_record_id,
                        "reason": "player_carrier_not_found",
                    }
                )
                continue

            chosen_target_index: int | None = None
            chosen_name = ""
            chosen_record: PlayerCarrierRecord | SparePlayerRecord | None = None
            chosen_original = False
            relink_reason = ""
            for target_index, candidate_name in enumerate(target_players):
                if target_index in assigned_target_indexes:
                    continue
                direct_key = (int(original_carrier.record_id), _normalized_player_name(candidate_name))
                direct_safe = direct_safety_cache.get(direct_key)
                if direct_safe is None:
                    direct_safe = _player_name_layout_safe(original_carrier, candidate_name)
                    direct_safety_cache[direct_key] = direct_safe
                if original_record_id not in used_player_record_ids and direct_safe:
                    chosen_target_index = target_index
                    chosen_name = candidate_name
                    chosen_record = original_carrier
                    chosen_original = True
                    break
                spare = _find_layout_safe_spare(
                    target_name=candidate_name,
                    spare_candidates=spare_candidates,
                    used_player_record_ids=used_player_record_ids,
                    spare_safety_cache=spare_safety_cache,
                )
                if spare is not None:
                    chosen_target_index = target_index
                    chosen_name = candidate_name
                    chosen_record = spare
                    chosen_original = False
                    relink_reason = (
                        "duplicate_linked_player_record_id"
                        if original_record_id in used_player_record_ids
                        else "layout_safe_spare_player_record"
                    )
                if chosen_record is not None:
                    break

            if chosen_record is None or chosen_target_index is None:
                skipped_roster_slots.append(
                    {
                        "slot": int(carrier_row.slot_index) + 1,
                        "record_id": original_record_id,
                        "carrier_name": str(carrier_row.player_name),
                        "reason": "no_layout_safe_target_name",
                        "remaining_target_names": [
                            name for target_index, name in enumerate(target_players) if target_index not in assigned_target_indexes
                        ][:8],
                    }
                )
                continue

            assigned_target_indexes.add(chosen_target_index)
            source_name = source.roster_players[chosen_target_index]
            fitted_name = chosen_name
            player_key = f"{club_key}_p{len(roster_assignment) + 1:02d}"
            record_id = int(chosen_record.record_id)
            current_name = str(chosen_record.current_name)
            relinked_from_duplicate = False
            if not chosen_original:
                relinked_from_duplicate = True
                carrier_flag = getattr(carrier_row, "flag", None)
                squad_memberships.append(
                    {
                        "club_key": club_key,
                        "player_key": player_key,
                        "slot": int(carrier_row.slot_index) + 1,
                        "source": "linked",
                        "flag": int(carrier_flag) if carrier_flag is not None else 1,
                        "relink_reason": relink_reason or "layout_safe_spare_player_record",
                        "original_player_record_id": original_record_id,
                    }
                )
            used_player_record_ids.add(record_id)
            players.append(
                {
                    "player_key": player_key,
                    "record_id": record_id,
                    "name": current_name,
                    "new_name": fitted_name,
                    "source_name": source_name,
                    "source_club": source.display_name,
                    "source_url": source.roster_source_url,
                    "original_linked_record_id": original_record_id,
                    "relinked_from_duplicate": relinked_from_duplicate,
                    "layout_safe": True,
                }
            )
            roster_assignment.append(
                {
                    "slot": int(carrier_row.slot_index) + 1,
                    "record_id": record_id,
                    "original_record_id": original_record_id,
                    "carrier_name": str(carrier_row.player_name),
                    "current_name": current_name,
                    "target_name": source_name,
                    "applied_name": fitted_name,
                    "relinked_from_duplicate": relinked_from_duplicate,
                    "layout_safe": True,
                }
            )
            if source_name != fitted_name:
                name_fits.append(
                    {
                        "kind": "player",
                        "club": source.display_name,
                        "source": source_name,
                        "applied": fitted_name,
                        "reason": "ascii_or_length_fit",
                    }
                )
        skipped_target_names = [
            name for target_index, name in enumerate(target_players) if target_index not in assigned_target_indexes
        ]
        if skipped_target_names:
            name_fits.append(
                {
                    "kind": "player_layout_skips",
                    "club": source.display_name,
                    "skipped_count": len(skipped_target_names),
                    "skipped_names": skipped_target_names,
                    "reason": "indexed_player_name_layout_not_runtime_safe",
                }
            )
        assignments.append(
            {
                "slot": index,
                "carrier_club_key": selector.get("club_key"),
                "carrier_team_query": selector.get("team_query"),
                "compile_team_query": compile_team_query,
                "carrier_eq_record_id": int(carrier.eq_record_id),
                "target_club_key": club_key,
                "target_display_name": source.display_name,
                "target_league": source.league_name,
                "target_player_count": len(roster_assignment),
                "requested_player_count": min(len(target_players), target_row_count),
                "carrier_active_rows": len(active_rows),
                "skipped_roster_slots": skipped_roster_slots,
                "skipped_target_names": skipped_target_names,
                "selector": {
                    "division_select_x": int(selector["division_select_x"]),
                    "division_select_y": int(selector["division_select_y"]),
                    "team_select_x": int(selector["team_select_x"]),
                    "team_select_y": int(selector["team_select_y"]),
                },
                "roster": roster_assignment,
            }
        )
        fitted_team = fitted_team_name
        if fitted_team != source.display_name:
            name_fits.append({"kind": "club", "source": source.display_name, "applied": fitted_team, "reason": "team_display_fit"})

    world = {
        "schema": SCHEMA_ID,
        "generated_by": "scripts/build_2025_roster_world_state.py",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "scope": {
            "season": "2025-26",
            "club_count": 80,
            "player_count": len(players),
            "policy": "top 80 English pyramid clubs mapped onto proven PM99 selector slots; fill every available PM99 carrier roster row up to 20; club/player identity only",
        },
        "clubs": clubs,
        "players": players,
        "squad_memberships": squad_memberships,
        "divisions": [],
    }
    source_audit = {
        "schema": "pm99-2025-roster-source-audit-v1",
        "source_system": "Wikipedia MediaWiki API",
        "leagues": [dict(zip(["league_key", "league_name", "title", "limit"], league)) for league in LEAGUES],
        "clubs": [asdict(source) for source in club_sources],
        "blockers": blockers,
    }
    _json_dump(output_dir / "world_2025_top80.json", world)
    _json_dump(output_dir / "slot_assignment_2025_top80.json", {"schema": "pm99-2025-slot-assignment-v1", "assignments": assignments, "blockers": blockers})
    _json_dump(output_dir / "source_audit_2025_top80.json", source_audit)
    _json_dump(output_dir / "name_capacity_report_2025_top80.json", {"schema": "pm99-2025-name-fit-v1", "fits": name_fits, "blockers": blockers})
    _json_dump(
        output_dir / "manifest.json",
        {
            "schema": "pm99-2025-roster-world-manifest-v1",
            "ok": not blockers,
            "world_state": str(output_dir / "world_2025_top80.json"),
            "slot_assignment": str(output_dir / "slot_assignment_2025_top80.json"),
            "source_audit": str(output_dir / "source_audit_2025_top80.json"),
            "name_capacity_report": str(output_dir / "name_capacity_report_2025_top80.json"),
            "selector_map": {"path": str(selector_map_path), "sha256": sha256(selector_map_path), "schema": SELECTOR_MAP_SCHEMA_ID},
            "counts": {"clubs": len(clubs), "players": len(players), "blockers": len(blockers)},
            "squad_membership_relinks": len(squad_memberships),
            "team_renames_enabled": bool(include_team_renames),
            "team_renames_suppressed": sum(1 for club in clubs if "suppressed_set_name" in club or "suppressed_set_full_club_name" in club),
            "blockers": blockers,
        },
    )
    return world


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--selector-map", default=str(DEFAULT_SELECTOR_MAP))
    parser.add_argument("--game-root", default=str(DEFAULT_GAME_ROOT))
    parser.add_argument("--refresh", action="store_true", help="Refresh MediaWiki API cache")
    parser.add_argument(
        "--include-team-renames",
        action="store_true",
        help="Investigation-only: emit EQ team-name edits. Default suppresses them because runner proof shows they can crash season initialization.",
    )
    args = parser.parse_args(argv)

    cache_dir = Path(args.cache_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    selector_map_path = Path(args.selector_map).expanduser().resolve()
    game_root = Path(args.game_root).expanduser().resolve()

    client = WikiClient(cache_dir, refresh=args.refresh)
    club_sources = collect_club_sources(client)
    world = build_world_state(
        club_sources,
        selector_map_path=selector_map_path,
        game_root=game_root,
        output_dir=output_dir,
        include_team_renames=bool(args.include_team_renames),
    )
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    print(json.dumps({"ok": bool(manifest["ok"]), "output_dir": str(output_dir), "counts": manifest["counts"], "world_state": str(output_dir / "world_2025_top80.json")}, indent=2, sort_keys=True))
    return 0 if len(world["clubs"]) == 80 and manifest["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
