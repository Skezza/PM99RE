from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pm99_world_state as ws


@pytest.fixture()
def canonical_world_state(tmp_path: Path) -> Path:
    payload = {
        "schema": ws.SCHEMA_ID,
        "clubs": [
            {
                "club_key": "stoke",
                "team_query": "Stoke C.",
                "set_name": "Stoke C.",
                "team_select_x": 327,
                "team_select_y": 356,
                "division_select_x": 559,
                "division_select_y": 302,
            }
        ],
        "players": [
            {
                "player_key": "butland",
                "name": "Jack Butland",
                "new_name": "Jack Butland",
            }
        ],
        "squad_memberships": [
            {
                "club_key": "stoke",
                "player_key": "butland",
                "slot": 1,
                "source": "linked",
            }
        ],
        "divisions": [
            {
                "club_key": "stoke",
                "division": "premier",
                "country": "england",
            }
        ],
    }
    path = tmp_path / "world.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_world_state_rejects_unknown_squad_player(tmp_path: Path) -> None:
    payload = {
        "schema": ws.SCHEMA_ID,
        "clubs": [{"club_key": "stoke", "team_query": "Stoke C."}],
        "players": [],
        "squad_memberships": [{"club_key": "stoke", "player_key": "missing", "slot": 1}],
        "divisions": [{"club_key": "stoke", "division": "premier"}],
    }
    path = tmp_path / "bad_world.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="Unknown squad_memberships.player_key"):
        ws.load_world_state(path)


def test_compile_world_plan_blocks_unreleased_division_write(
    canonical_world_state: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    game_root = tmp_path / "game"
    (game_root / "DBDAT").mkdir(parents=True)

    monkeypatch.setattr(ws, "resolve_game_root", lambda game_root, require_writable=False: Path(game_root))
    monkeypatch.setattr(ws, "core_file_hashes", lambda game_root: {"JUG98030.FDI": "a", "EQ98030.FDI": "b", "ENT98030.FDI": "c"})
    monkeypatch.setattr(
        ws,
        "_resolve_clubs",
        lambda world, team_file, player_file: (
            {
                "stoke": ws.ResolvedClub(
                    club_key="stoke",
                    team_query="Stoke C.",
                    team_name="Stoke C.",
                    full_club_name="Stoke City",
                    team_id=3425,
                    team_offset=1234,
                    league="division one",
                    country="england",
                    eq_record_id=777,
                    linked_source_available=True,
                )
            },
            [],
        ),
    )
    monkeypatch.setattr(
        ws,
        "_resolve_players",
        lambda world, player_file: (
            {
                "butland": ws.ResolvedPlayer(
                    player_key="butland",
                    input_name="Jack Butland",
                    record_id=3445,
                    payload_offset=9000,
                    current_name="Jack Butland",
                    team_id=3425,
                )
            },
            [],
        ),
    )

    plan = ws.compile_world_plan(canonical_world_state, game_root=game_root)

    assert plan["ok"] is False
    blocker_codes = {item["code"] for item in plan["blockers"]}
    assert "division_write_surface_unreleased" in blocker_codes
    assert plan["counts"]["roster_batch_rows"] == 1
    assert plan["counts"]["player_batch_rows"] == 1
    club_cases = plan["runtime_proof_cases"]["club_smoke"]
    assert club_cases[0]["status"] == "ready"
    assert club_cases[0]["selector"]["team_select_y"] == 356


def test_compile_world_plan_marks_club_proof_blocked_without_selector(
    canonical_world_state: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = json.loads(canonical_world_state.read_text(encoding="utf-8"))
    for key in ("team_select_x", "team_select_y", "division_select_x", "division_select_y"):
        payload["clubs"][0].pop(key)
    world_state = tmp_path / "world_without_selector.json"
    world_state.write_text(json.dumps(payload), encoding="utf-8")
    game_root = tmp_path / "game"
    (game_root / "DBDAT").mkdir(parents=True)

    monkeypatch.setattr(ws, "resolve_game_root", lambda game_root, require_writable=False: Path(game_root))
    monkeypatch.setattr(ws, "core_file_hashes", lambda game_root: {})
    monkeypatch.setattr(
        ws,
        "_resolve_clubs",
        lambda world, team_file, player_file: (
            {
                "stoke": ws.ResolvedClub(
                    club_key="stoke",
                    team_query="Stoke C.",
                    team_name="Stoke C.",
                    full_club_name="Stoke City",
                    team_id=3425,
                    team_offset=1234,
                    league="premier",
                    country="england",
                    eq_record_id=777,
                    linked_source_available=True,
                )
            },
            [],
        ),
    )
    monkeypatch.setattr(
        ws,
        "_resolve_players",
        lambda world, player_file: (
            {
                "butland": ws.ResolvedPlayer(
                    player_key="butland",
                    input_name="Jack Butland",
                    record_id=3445,
                    payload_offset=9000,
                    current_name="Jack Butland",
                    team_id=3425,
                )
            },
            [],
        ),
    )

    plan = ws.compile_world_plan(world_state, game_root=game_root)

    club_case = plan["runtime_proof_cases"]["club_smoke"][0]
    assert club_case["status"] == "blocked_missing_selector"
    assert "missing_team_select_x" in club_case["blockers"]


def test_selector_map_supplies_runtime_selector(
    canonical_world_state: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = json.loads(canonical_world_state.read_text(encoding="utf-8"))
    for key in ("team_select_x", "team_select_y", "division_select_x", "division_select_y"):
        payload["clubs"][0].pop(key)
    world_state = tmp_path / "world_without_selector.json"
    world_state.write_text(json.dumps(payload), encoding="utf-8")
    selector_map = tmp_path / "selectors.json"
    selector_map.write_text(
        json.dumps(
            {
                "schema": ws.SELECTOR_MAP_SCHEMA_ID,
                "selectors": [
                    {
                        "club_key": "stoke",
                        "team_select_x": 327,
                        "team_select_y": 356,
                        "division_select_x": 559,
                        "division_select_y": 302,
                        "runtime_routes": ["squad", "line_up"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    game_root = tmp_path / "game"
    (game_root / "DBDAT").mkdir(parents=True)

    monkeypatch.setattr(ws, "resolve_game_root", lambda game_root, require_writable=False: Path(game_root))
    monkeypatch.setattr(ws, "core_file_hashes", lambda game_root: {})
    monkeypatch.setattr(
        ws,
        "_resolve_clubs",
        lambda world, team_file, player_file: (
            {
                "stoke": ws.ResolvedClub(
                    club_key="stoke",
                    team_query="Stoke C.",
                    team_name="Stoke C.",
                    full_club_name="Stoke City",
                    team_id=3425,
                    team_offset=1234,
                    league="premier",
                    country="england",
                    eq_record_id=777,
                    linked_source_available=True,
                )
            },
            [],
        ),
    )
    monkeypatch.setattr(
        ws,
        "_resolve_players",
        lambda world, player_file: (
            {
                "butland": ws.ResolvedPlayer(
                    player_key="butland",
                    input_name="Jack Butland",
                    record_id=3445,
                    payload_offset=9000,
                    current_name="Jack Butland",
                    team_id=3425,
                )
            },
            [],
        ),
    )

    coverage = ws.build_selector_coverage(world_state, selector_map)
    plan = ws.compile_world_plan(world_state, game_root=game_root, selector_map=selector_map)

    assert coverage["ok"] is True
    club_case = plan["runtime_proof_cases"]["club_smoke"][0]
    assert club_case["status"] == "ready"
    assert club_case["selector"]["team_select_y"] == 356
    assert club_case["routes"] == ["squad", "line_up"]
    assert plan["selector_map_source"] is not None


def test_selector_scaffold_marks_missing_fields(canonical_world_state: Path, tmp_path: Path) -> None:
    payload = json.loads(canonical_world_state.read_text(encoding="utf-8"))
    for key in ("team_select_x", "team_select_y", "division_select_x", "division_select_y"):
        payload["clubs"][0].pop(key)
    world_state = tmp_path / "world_without_selector.json"
    world_state.write_text(json.dumps(payload), encoding="utf-8")

    scaffold = ws.build_selector_scaffold(world_state)

    selector = scaffold["selectors"][0]
    assert scaffold["ok"] is False
    assert selector["club_key"] == "stoke"
    assert selector["status"] == "blocked_missing_selector"
    assert selector["team_select_x"] is None
    assert set(selector["missing"]) == set(ws.SELECTOR_KEYS)


def test_selector_scaffold_merges_existing_selector(canonical_world_state: Path, tmp_path: Path) -> None:
    payload = json.loads(canonical_world_state.read_text(encoding="utf-8"))
    for key in ("team_select_x", "team_select_y", "division_select_x", "division_select_y"):
        payload["clubs"][0].pop(key)
    world_state = tmp_path / "world_without_selector.json"
    world_state.write_text(json.dumps(payload), encoding="utf-8")
    selector_map = tmp_path / "selectors.json"
    selector_map.write_text(
        json.dumps(
            {
                "schema": ws.SELECTOR_MAP_SCHEMA_ID,
                "selectors": [
                    {
                        "club_key": "stoke",
                        "team_select_x": 327,
                        "team_select_y": 356,
                        "division_select_x": 559,
                        "division_select_y": 302,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    scaffold = ws.build_selector_scaffold(world_state, selector_map)

    selector = scaffold["selectors"][0]
    assert scaffold["ok"] is True
    assert selector["status"] == "ready"
    assert selector["team_select_y"] == 356
    assert selector["missing"] == []


def test_selector_generate_uses_menu_indices(tmp_path: Path) -> None:
    world_state = tmp_path / "world.json"
    world_state.write_text(
        json.dumps(
            {
                "schema": ws.SCHEMA_ID,
                "clubs": [
                    {
                        "club_key": "stoke",
                        "team_query": "Stoke C.",
                        "division_menu_index": 1,
                        "team_menu_index": 2,
                    }
                ],
                "players": [],
                "squad_memberships": [],
                "divisions": [{"club_key": "stoke", "division": "premier"}],
            }
        ),
        encoding="utf-8",
    )

    generated = ws.build_selector_map_from_layout(
        world_state,
        division_start_y=300,
        division_step_y=40,
        team_start_y=350,
        team_step_y=20,
    )

    selector = generated["selectors"][0]
    assert generated["ok"] is True
    assert selector["status"] == "ready"
    assert selector["division_select_y"] == 300
    assert selector["team_select_y"] == 370
    assert set(selector["generated_fields"]) == set(ws.SELECTOR_KEYS)


def test_selector_generate_preserves_existing_selector(canonical_world_state: Path, tmp_path: Path) -> None:
    payload = json.loads(canonical_world_state.read_text(encoding="utf-8"))
    for key in ("team_select_x", "team_select_y", "division_select_x", "division_select_y"):
        payload["clubs"][0].pop(key)
    payload["clubs"][0]["division_menu_index"] = 4
    payload["clubs"][0]["team_menu_index"] = 4
    world_state = tmp_path / "world_without_selector.json"
    world_state.write_text(json.dumps(payload), encoding="utf-8")
    selector_map = tmp_path / "selectors.json"
    selector_map.write_text(
        json.dumps(
            {
                "schema": ws.SELECTOR_MAP_SCHEMA_ID,
                "selectors": [
                    {
                        "club_key": "stoke",
                        "team_select_x": 111,
                        "team_select_y": 222,
                        "division_select_x": 333,
                        "division_select_y": 444,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    generated = ws.build_selector_map_from_layout(world_state, selector_map)

    selector = generated["selectors"][0]
    assert selector["status"] == "ready"
    assert selector["team_select_x"] == 111
    assert selector["team_select_y"] == 222
    assert selector["division_select_x"] == 333
    assert selector["division_select_y"] == 444
    assert selector["generated_fields"] == []


def test_write_plan_bundle_emits_compiled_inputs(tmp_path: Path) -> None:
    plan = {
        "schema": ws.SCHEMA_ID,
        "operations": {
            "team_edits": [{"team_query": "Stoke C.", "team_offset": 1234, "set_name": "Stoke City"}],
            "player_batch_rows": [{"name": "Jack Butland", "offset": 9000, "new_name": "Jack B."}],
            "roster_batch_rows": [{"team": "Stoke C.", "source": "linked", "eq_record_id": 777, "team_offset": 1234, "slot": 1, "player_id": 3445, "flag": 1, "pid": ""}],
        },
    }

    bundle = ws.write_plan_bundle(plan, tmp_path / "bundle")

    assert bundle.world_plan_path.is_file()
    assert bundle.player_csv_path is not None and bundle.player_csv_path.is_file()
    assert bundle.roster_csv_path is not None and bundle.roster_csv_path.is_file()
    assert bundle.team_edit_json_path is not None and bundle.team_edit_json_path.is_file()


def test_raw_linked_team_name_fallback_patches_fixed_xor_span(tmp_path: Path) -> None:
    team_file = tmp_path / "EQ98030.FDI"
    offset = 32
    payload = bytearray(b"\x00" * 96)
    payload[offset:offset + 7] = b"\x00\xbc\x02\x00\x00\x09\x00"
    payload[offset + 7:offset + 16] = ws._xor61_encode_fixed_text("Brentford", 9)
    team_file.write_bytes(bytes(payload))

    result = ws._patch_linked_team_name_fallback(team_file, team_offset=offset, new_name="Port Vale")

    patched = team_file.read_bytes()
    assert result["changed"] is True
    assert result["old_name"] == "Brentford"
    assert result["new_name"] == "Port Vale"
    assert ws._xor61_decode_text(patched[offset + 7:offset + 16]) == "Port Vale"


def test_world_apply_readiness_requires_global_audit() -> None:
    plan = {
        "operations": {
            "player_batch_rows": [{"offset": 1}],
            "roster_batch_rows": [{"slot": 1}],
            "team_edits": [{"team_offset": 10}],
        }
    }

    readiness = ws._build_world_apply_readiness(
        plan=plan,
        player_result={"returncode": 0, "json": {"row_count": 1, "matched_row_count": 1, "warnings": [], "applied_to_disk": True}},
        roster_result={"returncode": 0, "json": {"row_count": 1, "matched_row_count": 1, "warnings": [], "applied_to_disk": True}},
        team_results=[{"returncode": 0, "json": {"matched_count": 1, "warnings": [], "applied_to_disk": True}}],
        validate_result={"returncode": 0, "json": {"all_valid": True}},
        audit_result={"returncode": 1, "json": {"ok": False, "issues": ["team_release: residual global gap"]}},
    )

    assert readiness["ok"] is False
    assert readiness["checks"]["global_game_ready_audit"]["ok"] is False
    assert readiness["global_audit_required"] is True
