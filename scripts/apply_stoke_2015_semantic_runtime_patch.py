#!/usr/bin/env python3
"""Apply source-backed Stoke 2015 semantic metadata to runtime-safe clone records.

This targets the 80-byte dd6360 clone payloads used by the Stoke runtime proof.
Those records are game-visible, but their visible nationality byte lives in the
compact clone profile block at ``name_end + 5``. The generic player metadata
serializer currently writes the older parser field at ``name_end + 8``, which is
why Dely Valdes clone records surfaced as Panama in-game.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import struct
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
EDITOR_ROOT = REPO_ROOT / "upstream" / "pm99-skezmod-db-editor"
if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.eq_jug_linked import load_eq_linked_team_rosters  # noqa: E402
from app.fdi_indexed import IndexedFDIFile  # noqa: E402
from app.models import PlayerRecord  # noqa: E402
from app.xor import xor_encode  # noqa: E402
from assert_pm99_isolated_input import sha256  # noqa: E402
from stoke_2015_apply_metadata import _extract_nationality_codes  # noqa: E402


SOURCE_URL = "https://www.footballsquads.co.uk/eng/2015-2016/faprem/stoke.htm"
SOURCE_URLS = {
    "squad_bio": SOURCE_URL,
    "wikipedia_squad_stats": "https://en.wikipedia.org/wiki/2015%E2%80%9316_Stoke_City_F.C._season#Squad_statistics",
    "espn_pl_squad_stats": "https://www.espn.com/soccer/team/squad/_/id/336/league/ENG.1/season/2015",
    "sky_season_review": "https://www.skysports.com/football/news/15133/10283160/stoke-city-2015-16-premier-league-season-review",
    "fifa_index_team_shape": "https://www.fifaindex.com/team/1806/stoke-city/fifa16/",
    "futbin_diouf_pace": "https://www.futbin.com/16/player/5256/diouf",
}

POSITION_CODE = {"G": 0, "D": 1, "M": 2, "F": 3}
POSITION_LABEL = {0: "Goalkeeper", 1: "Defender", 2: "Midfielder", 3: "Forward"}

NAT_ABBR_TO_SOURCE_LABEL = {
    "ENG": "England",
    "SCO": "Scotland",
    "NED": "Netherlands",
    "ESP": "Spain",
    "IRL": "Republic of Ireland",
    "NGA": "Nigeria",
    "AUT": "Austria",
    "SEN": "Senegal",
    "USA": "United States",
    "CGO": "Congo / DR Congo",
}

NAT_ABBR_TO_PM99_LABEL = {
    "ENG": "ENGLAND",
    "SCO": "SCOTLAND",
    "NED": "HOLLAND",
    "ESP": "SPAIN",
    "IRL": "IRELAND",
    "NGA": "NIGERIA",
    "AUT": "AUSTRIA",
    "SEN": "SENEGAL",
    "USA": "UNITED STATES",
    # PM99's 1998-era country table uses ZAIRE rather than a modern Congo label.
    "CGO": "ZAIRE",
}

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


@dataclass(frozen=True)
class StokeTarget:
    slot: int
    game_name: str
    source_name: str
    source_number: int
    nat_abbr: str
    pos_abbr: str
    height_m: str
    weight_kg: int
    dob: str
    birth_place: str
    previous_club: str
    skills: tuple[int, int, int, int, int, int, int, int, int]
    fine_roles: tuple[int, ...]
    source_section: str = "current squad"


STOKE_TARGETS: list[StokeTarget] = [
    StokeTarget(1, "Jack Butland", "Jack Butland", 1, "ENG", "G", "1.92", 95, "10-03-93", "Bristol", "Birmingham C", (65, 70, 62, 77, 45, 35, 55, 20, 45), (0,)),
    StokeTarget(2, "Phil Bardsley", "Phillip Bardsley", 2, "SCO", "D", "1.79", 74, "28-06-85", "Salford", "Sunderland", (68, 76, 78, 70, 70, 62, 66, 58, 78), (1, 2, 4, 5)),
    StokeTarget(3, "Erik Pieters", "Erik Pieters", 3, "NED", "D", "1.86", 82, "07-08-88", "Tiel", "PSV Eindhoven", (70, 76, 70, 72, 69, 66, 68, 55, 76), (2, 4, 5)),
    StokeTarget(4, "Marc Muniesa", "Marc Muniesa", 5, "ESP", "D", "1.80", 77, "27-03-92", "Lloret de Mar", "Barcelona", (68, 72, 66, 73, 66, 68, 70, 55, 73), (4, 5, 3)),
    StokeTarget(5, "Glenn Whelan", "Glenn Whelan", 6, "IRL", "M", "1.80", 79, "13-01-84", "Dublin", "Sheffield W", (62, 80, 78, 72, 68, 62, 76, 58, 76), (14, 9)),
    StokeTarget(6, "Stephen Ireland", "Stephen Ireland", 7, "IRL", "M", "1.75", 68, "22-08-86", "Cork", "Aston Villa", (70, 72, 58, 74, 55, 75, 76, 63, 56), (9, 7, 10)),
    StokeTarget(7, "Glen Johnson", "Glen Johnson", 8, "ENG", "D", "1.82", 70, "23-08-84", "Greenwich", "Liverpool", (76, 73, 68, 75, 70, 72, 70, 62, 73), (1, 6, 2)),
    StokeTarget(8, "Peter Odemwingie", "Peter Odemwingie", 9, "NGA", "F", "1.82", 74, "15-07-81", "Tashkent", "Cardiff C", (78, 70, 66, 74, 67, 75, 68, 76, 45), (15, 16, 8)),
    StokeTarget(9, "Marko Arnautovic", "Marko Arnautovic", 10, "AUT", "F", "1.92", 83, "19-04-89", "Vienna", "Werder Bremen", (76, 72, 72, 80, 76, 78, 74, 80, 48), (16, 15, 8)),
    StokeTarget(10, "Joselu Mato", "Joselu", 11, "ESP", "F", "1.91", 79, "27-03-90", "Stuttgart", "Hannover 96", (68, 70, 70, 73, 78, 66, 65, 76, 46), (12, 8)),
    StokeTarget(11, "Marc Wilson", "Marc Wilson", 12, "IRL", "D", "1.88", 80, "17-08-87", "Belfast", "Portsmouth", (64, 74, 72, 70, 75, 58, 66, 52, 74), (4, 5, 14)),
    StokeTarget(12, "Ibrahim Afellay", "Ibrahim Afellay", 14, "NED", "M", "1.81", 68, "02-04-86", "Utrecht", "Barcelona", (75, 68, 58, 76, 54, 79, 76, 69, 50), (9, 7, 10, 11, 13)),
    StokeTarget(13, "Marco van Ginkel", "Marco van Ginkel", 15, "NED", "M", "1.80", 67, "01-12-92", "Amersfoort", "Chelsea", (72, 74, 66, 74, 70, 72, 75, 68, 67), (9, 14)),
    StokeTarget(14, "Charlie Adam", "Charlie Adam", 16, "SCO", "M", "1.85", 83, "10-12-85", "Dundee", "Liverpool", (58, 70, 75, 76, 66, 68, 82, 75, 62), (9, 14)),
    StokeTarget(15, "Ryan Shawcross", "Ryan Shawcross", 17, "ENG", "D", "1.83", 76, "04-10-87", "Chester", "Manchester U", (58, 78, 82, 74, 82, 48, 62, 54, 83), (4, 5, 3)),
    StokeTarget(16, "Mame Diouf", "Mame Biram Diouf", 18, "SEN", "F", "1.85", 76, "16-12-87", "Dakar", "Hannover 96", (78, 74, 70, 74, 80, 70, 66, 76, 50), (12, 8, 15)),
    StokeTarget(17, "Jonathan Walters", "Jonathan Walters", 19, "IRL", "F", "1.83", 79, "20-09-83", "Birkenhead", "Ipswich T", (68, 80, 80, 73, 78, 66, 68, 74, 62), (8, 12, 6)),
    StokeTarget(18, "Geoff Cameron", "Geoff Cameron", 20, "USA", "D", "1.91", 92, "11-07-85", "Attleboro", "Houston Dynamo", (70, 78, 74, 73, 78, 66, 70, 58, 76), (4, 5, 14)),
    StokeTarget(19, "Giannelli Imbula", "Giannelli Imbula", 21, "CGO", "M", "1.86", 77, "12-09-92", "Vilvoorde", "FC Porto", (74, 72, 68, 74, 68, 76, 72, 64, 66), (9, 14)),
    StokeTarget(20, "Steve Sidwell", "Steve Sidwell", 21, "ENG", "M", "1.78", 70, "14-12-82", "Wandsworth", "Brighton & HA (On Loan)", (64, 74, 74, 70, 70, 60, 70, 60, 72), (9, 14), "players no longer at this club"),
]

# Wikipedia 2015-16 Stoke squad statistics supply total appearances/goals and
# discipline. ESPN supplies Premier League assists, shots, shots on target,
# fouls committed/suffered and cards. Pace is not present in either stat table,
# so it is style-calibrated explicitly rather than guessed from output.
STOKE_SEASON_STATS: dict[str, dict[str, int | str | None]] = {
    "Jack Butland": {"wiki_starts": 35, "wiki_subs": 0, "wiki_goals": 0, "wiki_yellow": 0, "wiki_red": 0, "espn_app": 31, "espn_sub": 0, "espn_goals": 0, "espn_assists": 0, "espn_shots": 0, "espn_sot": 0, "espn_fouls_committed": 1, "espn_fouls_suffered": 1},
    "Phil Bardsley": {"wiki_starts": 14, "wiki_subs": 3, "wiki_goals": 1, "wiki_yellow": 4, "wiki_red": 1, "espn_app": 11, "espn_sub": 2, "espn_goals": 0, "espn_assists": 1, "espn_shots": 7, "espn_sot": 2, "espn_fouls_committed": 12, "espn_fouls_suffered": 15},
    "Erik Pieters": {"wiki_starts": 41, "wiki_subs": 0, "wiki_goals": 0, "wiki_yellow": 11, "wiki_red": 0, "espn_app": 35, "espn_sub": 0, "espn_goals": 0, "espn_assists": 1, "espn_shots": 5, "espn_sot": 1, "espn_fouls_committed": 59, "espn_fouls_suffered": 50},
    "Marc Muniesa": {"wiki_starts": 14, "wiki_subs": 3, "wiki_goals": 0, "wiki_yellow": 3, "wiki_red": 0, "espn_app": 15, "espn_sub": 3, "espn_goals": 0, "espn_assists": 0, "espn_shots": 3, "espn_sot": 0, "espn_fouls_committed": 10, "espn_fouls_suffered": 8},
    "Glenn Whelan": {"wiki_starts": 40, "wiki_subs": 2, "wiki_goals": 0, "wiki_yellow": 6, "wiki_red": 0, "espn_app": 37, "espn_sub": 0, "espn_goals": 0, "espn_assists": 1, "espn_shots": 11, "espn_sot": 3, "espn_fouls_committed": 25, "espn_fouls_suffered": 20},
    "Stephen Ireland": {"wiki_starts": 3, "wiki_subs": 13, "wiki_goals": 0, "wiki_yellow": 2, "wiki_red": 0, "espn_app": 13, "espn_sub": 13, "espn_goals": 0, "espn_assists": 1, "espn_shots": 3, "espn_sot": 0, "espn_fouls_committed": 4, "espn_fouls_suffered": 0},
    "Glen Johnson": {"wiki_starts": 28, "wiki_subs": 1, "wiki_goals": 0, "wiki_yellow": 1, "wiki_red": 0, "espn_app": 25, "espn_sub": 0, "espn_goals": 0, "espn_assists": 3, "espn_shots": 17, "espn_sot": 5, "espn_fouls_committed": 11, "espn_fouls_suffered": 11},
    "Peter Odemwingie": {"wiki_starts": 2, "wiki_subs": 6, "wiki_goals": 0, "wiki_yellow": 0, "wiki_red": 0, "espn_app": None, "espn_sub": None, "espn_goals": None, "espn_assists": None, "espn_shots": None, "espn_sot": None, "espn_fouls_committed": None, "espn_fouls_suffered": None},
    "Marko Arnautovic": {"wiki_starts": 38, "wiki_subs": 2, "wiki_goals": 12, "wiki_yellow": 2, "wiki_red": 0, "espn_app": 34, "espn_sub": 1, "espn_goals": 11, "espn_assists": 6, "espn_shots": 70, "espn_sot": 22, "espn_fouls_committed": 49, "espn_fouls_suffered": 23},
    "Joselu Mato": {"wiki_starts": 12, "wiki_subs": 15, "wiki_goals": 4, "wiki_yellow": 0, "wiki_red": 0, "espn_app": 22, "espn_sub": 12, "espn_goals": 4, "espn_assists": 1, "espn_shots": 29, "espn_sot": 16, "espn_fouls_committed": 19, "espn_fouls_suffered": 18},
    "Marc Wilson": {"wiki_starts": 6, "wiki_subs": 4, "wiki_goals": 0, "wiki_yellow": 2, "wiki_red": 0, "espn_app": 4, "espn_sub": 3, "espn_goals": 0, "espn_assists": 0, "espn_shots": 0, "espn_sot": 0, "espn_fouls_committed": 2, "espn_fouls_suffered": 3},
    "Ibrahim Afellay": {"wiki_starts": 29, "wiki_subs": 7, "wiki_goals": 3, "wiki_yellow": 3, "wiki_red": 1, "espn_app": 31, "espn_sub": 7, "espn_goals": 2, "espn_assists": 2, "espn_shots": 39, "espn_sot": 8, "espn_fouls_committed": 19, "espn_fouls_suffered": 36},
    "Marco van Ginkel": {"wiki_starts": 11, "wiki_subs": 10, "wiki_goals": 0, "wiki_yellow": 2, "wiki_red": 0, "espn_app": None, "espn_sub": None, "espn_goals": None, "espn_assists": None, "espn_shots": None, "espn_sot": None, "espn_fouls_committed": None, "espn_fouls_suffered": None},
    "Charlie Adam": {"wiki_starts": 14, "wiki_subs": 11, "wiki_goals": 1, "wiki_yellow": 6, "wiki_red": 1, "espn_app": 22, "espn_sub": 10, "espn_goals": 1, "espn_assists": 1, "espn_shots": 29, "espn_sot": 4, "espn_fouls_committed": 30, "espn_fouls_suffered": 25},
    "Ryan Shawcross": {"wiki_starts": 23, "wiki_subs": 0, "wiki_goals": 0, "wiki_yellow": 4, "wiki_red": 1, "espn_app": 20, "espn_sub": 0, "espn_goals": 0, "espn_assists": 0, "espn_shots": 8, "espn_sot": 0, "espn_fouls_committed": 18, "espn_fouls_suffered": 3},
    "Mame Diouf": {"wiki_starts": 14, "wiki_subs": 16, "wiki_goals": 5, "wiki_yellow": 3, "wiki_red": 0, "espn_app": 26, "espn_sub": 14, "espn_goals": 5, "espn_assists": 1, "espn_shots": 30, "espn_sot": 16, "espn_fouls_committed": 21, "espn_fouls_suffered": 26},
    "Jonathan Walters": {"wiki_starts": 23, "wiki_subs": 10, "wiki_goals": 8, "wiki_yellow": 2, "wiki_red": 0, "espn_app": 27, "espn_sub": 9, "espn_goals": 5, "espn_assists": 3, "espn_shots": 32, "espn_sot": 13, "espn_fouls_committed": 14, "espn_fouls_suffered": 27},
    "Geoff Cameron": {"wiki_starts": 30, "wiki_subs": 4, "wiki_goals": 0, "wiki_yellow": 0, "wiki_red": 1, "espn_app": 30, "espn_sub": 3, "espn_goals": 0, "espn_assists": 0, "espn_shots": 15, "espn_sot": 2, "espn_fouls_committed": 27, "espn_fouls_suffered": 8},
    "Giannelli Imbula": {"wiki_starts": 14, "wiki_subs": 0, "wiki_goals": 2, "wiki_yellow": 4, "wiki_red": 0, "espn_app": 14, "espn_sub": 0, "espn_goals": 2, "espn_assists": 0, "espn_shots": 21, "espn_sot": 5, "espn_fouls_committed": 17, "espn_fouls_suffered": 20},
    "Steve Sidwell": {"wiki_starts": 2, "wiki_subs": 2, "wiki_goals": 0, "wiki_yellow": 1, "wiki_red": 0, "espn_app": None, "espn_sub": None, "espn_goals": None, "espn_assists": None, "espn_shots": None, "espn_sot": None, "espn_fouls_committed": None, "espn_fouls_suffered": None},
}

STOKE_ATTRIBUTE_BACKFILL: dict[str, dict[str, int | str]] = {
    "Jack Butland": {"speed": 64, "stamina": 82, "aggression": 60, "quality": 82, "heading": 45, "dribbling": 35, "passing": 58, "shooting": 20, "tackling": 45, "basis": "35 total apps, 31 PL apps and 103 ESPN saves; raised quality/stamina, goalkeeper outfield skills kept low."},
    "Phil Bardsley": {"speed": 66, "stamina": 74, "aggression": 78, "quality": 72, "heading": 70, "dribbling": 62, "passing": 66, "shooting": 58, "tackling": 78, "basis": "Defender with 17 total apps, 1 cup goal, 4Y/1R; hard tackling/aggression preserved, moderate output."},
    "Erik Pieters": {"speed": 72, "stamina": 86, "aggression": 74, "quality": 75, "heading": 70, "dribbling": 68, "passing": 70, "shooting": 55, "tackling": 79, "basis": "Ever-present full-back: 41 total starts, 35 PL apps, heavy foul volume and 11 yellows; high stamina/tackling."},
    "Marc Muniesa": {"speed": 67, "stamina": 70, "aggression": 65, "quality": 73, "heading": 66, "dribbling": 68, "passing": 70, "shooting": 54, "tackling": 74, "basis": "17 total apps and low attacking output; balanced technical defender profile."},
    "Glenn Whelan": {"speed": 59, "stamina": 84, "aggression": 77, "quality": 76, "heading": 68, "dribbling": 63, "passing": 78, "shooting": 57, "tackling": 78, "basis": "42 total apps, 37 PL apps, deep midfield role, 6 yellows; high stamina/passing/tackling, low pace."},
    "Stephen Ireland": {"speed": 68, "stamina": 64, "aggression": 58, "quality": 72, "heading": 55, "dribbling": 75, "passing": 76, "shooting": 60, "tackling": 55, "basis": "Mostly substitute usage, 1 PL assist, low defensive/foul involvement; technical midfielder shape."},
    "Glen Johnson": {"speed": 73, "stamina": 78, "aggression": 68, "quality": 75, "heading": 70, "dribbling": 72, "passing": 71, "shooting": 60, "tackling": 73, "basis": "29 total apps, 3 PL assists and 17 shots from full-back; useful pace/ball-carrying."},
    "Peter Odemwingie": {"speed": 72, "stamina": 58, "aggression": 62, "quality": 69, "heading": 65, "dribbling": 71, "passing": 64, "shooting": 64, "tackling": 45, "basis": "Only 8 total Stoke apps before Bristol City loan; older wide-forward profile reduced for limited 2015-16 role."},
    "Marko Arnautovic": {"speed": 68, "stamina": 83, "aggression": 74, "quality": 84, "heading": 75, "dribbling": 82, "passing": 80, "shooting": 84, "tackling": 49, "basis": "Stoke's elite attacker: 40 total apps, 12 total goals, ESPN 11G/6A/70SH/22SOT; pace pulled down versus Diouf, output/technical skills raised."},
    "Joselu Mato": {"speed": 67, "stamina": 67, "aggression": 70, "quality": 73, "heading": 81, "dribbling": 66, "passing": 65, "shooting": 77, "tackling": 46, "basis": "27 total apps, 4 PL goals, 16 SOT from 29 shots; target-forward heading/shooting emphasis."},
    "Marc Wilson": {"speed": 62, "stamina": 62, "aggression": 72, "quality": 69, "heading": 75, "dribbling": 57, "passing": 65, "shooting": 50, "tackling": 74, "basis": "10 total apps before injury; defensive utility retained, stamina/quality reduced for limited season."},
    "Ibrahim Afellay": {"speed": 74, "stamina": 75, "aggression": 60, "quality": 77, "heading": 54, "dribbling": 80, "passing": 78, "shooting": 70, "tackling": 50, "basis": "36 total apps, 3 total goals, 2 PL assists, 36 fouls suffered; technical dribbler/passer profile."},
    "Marco van Ginkel": {"speed": 70, "stamina": 67, "aggression": 65, "quality": 72, "heading": 68, "dribbling": 71, "passing": 73, "shooting": 62, "tackling": 66, "basis": "21 total apps on loan with no goals; balanced Chelsea loanee CM profile, no ESPN detailed row available."},
    "Charlie Adam": {"speed": 55, "stamina": 68, "aggression": 80, "quality": 76, "heading": 66, "dribbling": 68, "passing": 82, "shooting": 75, "tackling": 62, "basis": "25 total apps, 29 PL shots, 6Y/1R; slow playmaker with strong passing/shot/aggression."},
    "Ryan Shawcross": {"speed": 55, "stamina": 75, "aggression": 84, "quality": 78, "heading": 84, "dribbling": 48, "passing": 62, "shooting": 52, "tackling": 85, "basis": "Captain/CB: 23 total starts, 4Y/1R, low attacking output; elite heading/tackling, low speed/dribbling."},
    "Mame Diouf": {"speed": 88, "stamina": 72, "aggression": 70, "quality": 77, "heading": 88, "dribbling": 68, "passing": 58, "shooting": 78, "tackling": 45, "basis": "30 total apps, 5 PL goals, all five PL goals noted by Sky as headers; FUTBIN FIFA16 gives 90 pace, so PM99 speed is very high."},
    "Jonathan Walters": {"speed": 68, "stamina": 78, "aggression": 80, "quality": 76, "heading": 80, "dribbling": 66, "passing": 68, "shooting": 78, "tackling": 62, "basis": "33 total apps, 8 total goals, 3 PL assists and strong foul-suffered count; durable physical forward."},
    "Geoff Cameron": {"speed": 69, "stamina": 81, "aggression": 74, "quality": 75, "heading": 78, "dribbling": 66, "passing": 70, "shooting": 56, "tackling": 78, "basis": "34 total apps, defensive/midfield utility and 30 PL apps; high stamina/tackling/heading."},
    "Giannelli Imbula": {"speed": 73, "stamina": 72, "aggression": 72, "quality": 75, "heading": 68, "dribbling": 78, "passing": 73, "shooting": 71, "tackling": 67, "basis": "January signing with 14 starts, 2 goals and 21 shots; ball-carrying CM profile."},
    "Steve Sidwell": {"speed": 62, "stamina": 58, "aggression": 72, "quality": 68, "heading": 68, "dribbling": 58, "passing": 68, "shooting": 55, "tackling": 70, "basis": "4 total Stoke apps before Brighton loan; experienced CM/CDM profile reduced for tiny 2015-16 role."},
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", required=True, help="Isolated game root containing DBDAT/")
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "artifacts" / f"stoke_2015_semantic_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"),
        help="Artifact output directory",
    )
    parser.add_argument("--team-query", default="Stoke", help="Team query for linked roster lookup")
    parser.add_argument("--dry-run", action="store_true", help="Build ledgers/readback without writing JUG")
    return parser.parse_args()


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _height_cm(value: str) -> int:
    return int(round(float(value) * 100.0))


def _dob_parts(value: str) -> tuple[int, int, int]:
    day_text, month_text, year_text = value.split("-")
    year_two = int(year_text)
    year = 1900 + year_two
    return int(day_text), int(month_text), year


def _encode_byte(value: int) -> int:
    if not 0 <= int(value) <= 255:
        raise ValueError(f"Byte value out of range: {value}")
    return int(value) ^ 0x61


def _encode_role_slot(code: int) -> int:
    if int(code) == 98:
        decoded = 0
    elif 0 <= int(code) <= 17:
        decoded = int(code) + 1
    else:
        raise ValueError(f"Fine role code out of range: {code}")
    return _encode_byte(decoded)


def _stats_for(target: StokeTarget) -> dict[str, int | str | None]:
    stats = STOKE_SEASON_STATS.get(target.game_name)
    if stats is None:
        raise RuntimeError(f"No 2015-16 season stats mapped for {target.game_name!r}")
    return stats


def _skills_for(target: StokeTarget) -> tuple[dict[str, int], str]:
    backfill = STOKE_ATTRIBUTE_BACKFILL.get(target.game_name)
    if backfill is None:
        # Keep the old tuple as a hard failure fallback only for future expansion.
        return dict(zip(SKILL_LABELS, target.skills, strict=True)), "legacy seed tuple fallback"
    skills = {label: int(backfill[label]) for label in SKILL_LABELS}
    return skills, str(backfill["basis"])


def _source_rows(country_codes: dict[str, int]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for target in STOKE_TARGETS:
        pm99_label = NAT_ABBR_TO_PM99_LABEL[target.nat_abbr]
        if pm99_label not in country_codes:
            raise RuntimeError(f"PM99 country label {pm99_label!r} not present in TEXTOS.PKF")
        day, month, year = _dob_parts(target.dob)
        stats = _stats_for(target)
        skills, attribute_basis = _skills_for(target)
        rows.append(
            {
                "slot": target.slot,
                "game_name": target.game_name,
                "source_name": target.source_name,
                "source_number": target.source_number,
                "source_nat_abbr": target.nat_abbr,
                "source_nat_label": NAT_ABBR_TO_SOURCE_LABEL[target.nat_abbr],
                "pm99_nat_label": pm99_label,
                "pm99_nat_code": int(country_codes[pm99_label]),
                "source_position": target.pos_abbr,
                "pm99_position_code": POSITION_CODE[target.pos_abbr],
                "pm99_position_label": POSITION_LABEL[POSITION_CODE[target.pos_abbr]],
                "height_m": target.height_m,
                "height_cm": _height_cm(target.height_m),
                "weight_kg": target.weight_kg,
                "dob_source": target.dob,
                "birth_day": day,
                "birth_month": month,
                "birth_year": year,
                "birth_place": target.birth_place,
                "previous_club": target.previous_club,
                "wiki_total_starts": stats["wiki_starts"],
                "wiki_total_subs": stats["wiki_subs"],
                "wiki_total_apps": int(stats["wiki_starts"] or 0) + int(stats["wiki_subs"] or 0),
                "wiki_total_goals": stats["wiki_goals"],
                "wiki_yellow_cards": stats["wiki_yellow"],
                "wiki_red_cards": stats["wiki_red"],
                "espn_pl_apps": stats["espn_app"],
                "espn_pl_subs": stats["espn_sub"],
                "espn_pl_goals": stats["espn_goals"],
                "espn_pl_assists": stats["espn_assists"],
                "espn_pl_shots": stats["espn_shots"],
                "espn_pl_shots_on_target": stats["espn_sot"],
                "espn_pl_fouls_committed": stats["espn_fouls_committed"],
                "espn_pl_fouls_suffered": stats["espn_fouls_suffered"],
                "skills": skills,
                "attribute_basis": attribute_basis,
                "fine_role_codes": list(target.fine_roles),
                "source_section": target.source_section,
                "source_url": SOURCE_URL,
                "source_urls": dict(SOURCE_URLS),
            }
        )
    return rows


def _resolve_stoke_roster(team_file: Path, player_file: Path, team_query: str) -> list[dict[str, Any]]:
    rosters = load_eq_linked_team_rosters(team_file=str(team_file), player_file=str(player_file))
    needle = team_query.strip().lower()
    for roster in rosters:
        names = [
            str(getattr(roster, "short_name", "") or "").lower(),
            str(getattr(roster, "full_club_name", "") or "").lower(),
        ]
        if any(needle in item for item in names):
            rows = sorted(list(getattr(roster, "rows", []) or []), key=lambda row: int(getattr(row, "slot_index", 0)))
            return [
                {
                    "slot": int(getattr(row, "slot_index", 0)) + 1,
                    "pid": int(getattr(row, "player_record_id", 0) or 0),
                    "player_name": str(getattr(row, "player_name", "") or ""),
                }
                for row in rows[: len(STOKE_TARGETS)]
            ]
    raise RuntimeError(f"Could not resolve linked roster for team query {team_query!r}")


def _decoded_byte(decoded: bytes, offset: int) -> int:
    return decoded[offset] ^ 0x61


def _write_decoded_byte(decoded: bytearray, offset: int, value: int) -> None:
    if offset < 0 or offset >= len(decoded):
        raise RuntimeError(f"Patch offset {offset} outside payload length {len(decoded)}")
    decoded[offset] = _encode_byte(value)


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
        raise RuntimeError(f"Could not locate name-end marker for {source_row['game_name']}")
    if decoded[2:5] != b"\xdd\x63\x60":
        raise RuntimeError(
            f"{source_row['game_name']} is not a dd6360 runtime clone payload: signature={decoded[2:5].hex()}"
        )
    required_end = name_end + 15 + len(SKILL_LABELS)
    if required_end > len(decoded):
        raise RuntimeError(
            f"{source_row['game_name']} payload too short for compact clone semantic block: "
            f"need {required_end}, length {len(decoded)}"
        )

    before = _read_clone_fields(decoded, name_end)
    patched = bytearray(decoded)

    # The squad/profile POS label in this compact clone family reads the primary
    # role byte at name_end-3. Older probes also identify a role-like window at
    # name_end-1, so mirror the primary role into that first byte only. Secondary
    # bytes can alter the heuristic name-end marker on short names when changed
    # from zero to non-zero, so keep them as template-preserved data for this
    # runtime proof.
    primary_role = list(source_row["fine_role_codes"])[0]
    patched[name_end - 3] = _encode_role_slot(int(primary_role))
    patched[name_end - 1] = _encode_role_slot(int(primary_role))

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
    # Reparse to ensure the name survived. The generic parser nationality is not
    # used as the truth source for this compact clone family.
    reparsed = PlayerRecord.from_bytes(bytes(patched), 0)
    if _norm(str(getattr(reparsed, "name", "") or "")) != _norm(str(getattr(parsed, "name", "") or "")):
        raise RuntimeError(f"Name changed while patching {source_row['game_name']}")
    if len(patched) != len(decoded):
        raise RuntimeError(f"Payload length changed for {source_row['game_name']}")
    return bytes(patched), before, after, name_end


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "slot",
        "pid",
        "game_name",
        "source_name",
        "source_nat_abbr",
        "source_nat_label",
        "pm99_nat_label",
        "pm99_nat_code",
        "source_position",
        "pm99_position_label",
        "dob_source",
        "birth_day",
        "birth_month",
        "birth_year",
        "height_cm",
        "weight_kg",
        "wiki_total_starts",
        "wiki_total_subs",
        "wiki_total_apps",
        "wiki_total_goals",
        "wiki_yellow_cards",
        "wiki_red_cards",
        "espn_pl_apps",
        "espn_pl_subs",
        "espn_pl_goals",
        "espn_pl_assists",
        "espn_pl_shots",
        "espn_pl_shots_on_target",
        "espn_pl_fouls_committed",
        "espn_pl_fouls_suffered",
        *SKILL_LABELS,
        "attribute_basis",
        "source_url",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            flat = dict(row)
            flat.update(row.get("skills") or {})
            writer.writerow({key: flat.get(key, "") for key in fieldnames})


def main() -> int:
    args = _parse_args()
    game_root = Path(args.game_root).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    dbdat = game_root / "DBDAT"
    team_file = dbdat / "EQ98030.FDI"
    player_file = dbdat / "JUG98030.FDI"
    coach_file = dbdat / "ENT98030.FDI"
    textos_pkf = dbdat / "TEXTOS.PKF"
    for path in (team_file, player_file, coach_file, textos_pkf):
        if not path.is_file():
            raise SystemExit(f"Required PM99 file missing: {path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    country_codes = _extract_nationality_codes(textos_pkf)
    source_rows = _source_rows(country_codes)
    source_by_slot = {int(row["slot"]): row for row in source_rows}
    roster_rows = _resolve_stoke_roster(team_file, player_file, args.team_query)
    if len(roster_rows) != len(STOKE_TARGETS):
        raise RuntimeError(f"Resolved {len(roster_rows)} Stoke rows, expected {len(STOKE_TARGETS)}")

    file_bytes = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(file_bytes)
    entries_by_id = {int(entry.record_id): entry for entry in indexed.entries}

    patched_file = bytearray(file_bytes)
    readback_rows: list[dict[str, Any]] = []
    ledger_rows: list[dict[str, Any]] = []
    for roster_row in roster_rows:
        slot = int(roster_row["slot"])
        source_row = dict(source_by_slot[slot])
        record_id = int(roster_row["pid"])
        entry = entries_by_id.get(record_id)
        if entry is None:
            raise RuntimeError(f"Slot {slot} record id {record_id} not found in indexed JUG")
        decoded = entry.decode_payload(file_bytes)
        parsed = PlayerRecord.from_bytes(decoded, int(entry.payload_offset))
        parsed_name = str(getattr(parsed, "name", "") or "")
        if _norm(parsed_name) != _norm(str(source_row["game_name"])):
            raise RuntimeError(
                f"Slot {slot} expected {source_row['game_name']!r}, but JUG record {record_id} parses as {parsed_name!r}"
            )

        patched, before, after, name_end = _patch_clone_payload(decoded, source_row)
        encoded = xor_encode(patched)
        if len(encoded) != int(entry.payload_length):
            raise RuntimeError(
                f"Slot {slot} encoded payload length changed ({entry.payload_length} -> {len(encoded)})"
            )
        if not args.dry_run:
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

        ledger_row = {
            **source_row,
            "pid": record_id,
            "payload_offset": int(entry.payload_offset),
            "payload_length": int(entry.payload_length),
            "name_end": int(name_end),
        }
        ledger_rows.append(ledger_row)
        readback_rows.append(
            {
                "slot": slot,
                "pid": record_id,
                "name": parsed_name,
                "payload_offset": int(entry.payload_offset),
                "payload_length": int(entry.payload_length),
                "name_end": int(name_end),
                "before": before,
                "expected_after": expected_after,
                "actual_after": actual_subset,
                "matches": bool(matches),
            }
        )

    if not args.dry_run:
        backup_path = player_file.with_suffix(player_file.suffix + f".semantic_patch_backup_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}")
        shutil.copy2(player_file, backup_path)
        player_file.write_bytes(bytes(patched_file))
    else:
        backup_path = None

    reparsed_index = IndexedFDIFile.from_path(player_file)
    if len(reparsed_index.entries) != len(indexed.entries):
        raise RuntimeError("Indexed JUG entry count changed after semantic patch")

    source_json = output_dir / "stoke_2015_semantic_source_ledger.json"
    source_csv = output_dir / "stoke_2015_semantic_source_ledger.csv"
    readback_json = output_dir / "stoke_2015_semantic_readback.json"
    manifest_path = output_dir / "stoke_2015_semantic_manifest.json"
    source_json.write_text(json.dumps(ledger_rows, indent=2), encoding="utf-8")
    _write_csv(source_csv, ledger_rows)
    readback_json.write_text(json.dumps(readback_rows, indent=2), encoding="utf-8")

    manifest = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "game_root": str(game_root),
        "dbdat": str(dbdat),
        "team_file": str(team_file),
        "player_file": str(player_file),
        "coach_file": str(coach_file),
        "textos_pkf": str(textos_pkf),
        "source_url": SOURCE_URL,
        "source_urls": dict(SOURCE_URLS),
        "source_note": (
            "FootballSquads supplies nationality, position, height, weight, DOB, "
            "birthplace and previous club. Wikipedia 2015-16 Stoke squad statistics "
            "supply total apps/goals/cards. ESPN supplies Premier League assists, "
            "shots, shots on target and fouls. Sky confirms Arnautovic's 17 direct "
            "PL goal involvements and Diouf's headed-goal profile. FIFA Index/FUTBIN "
            "are used only as style/pace anchors where public season tables do not "
            "encode sprint speed."
        ),
        "dry_run": bool(args.dry_run),
        "backup_path": str(backup_path) if backup_path is not None else None,
        "input_hashes": {
            "EQ98030.FDI": sha256(team_file),
            "JUG98030.FDI": sha256(player_file),
            "ENT98030.FDI": sha256(coach_file),
            "TEXTOS.PKF": sha256(textos_pkf),
        },
        "country_code_subset": {
            label: int(country_codes[label])
            for label in sorted(set(NAT_ABBR_TO_PM99_LABEL.values()))
            if label in country_codes
        },
        "source_json": str(source_json),
        "source_csv": str(source_csv),
        "readback_json": str(readback_json),
        "readback_ok": all(bool(row["matches"]) for row in readback_rows),
        "row_count": len(readback_rows),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"ok": bool(manifest["readback_ok"]), "manifest": str(manifest_path)}, indent=2))
    return 0 if manifest["readback_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
