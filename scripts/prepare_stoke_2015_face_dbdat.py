#!/usr/bin/env python3
"""Prepare a Stoke 2015 DBDAT override set with face-matched MINIFOTO entries."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, datetime
import io
import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from PIL import Image, ImageOps

REPO_ROOT = Path(__file__).resolve().parents[1]
EDITOR_ROOT = REPO_ROOT / "upstream" / "pm99-skezmod-db-editor"
RUNNER_SCRIPTS = REPO_ROOT / "upstream" / "pm99-runner" / "scripts" / "pm99_runner"

if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))
if str(RUNNER_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RUNNER_SCRIPTS))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.eq_jug_linked import load_eq_linked_team_rosters  # noqa: E402
from app.minifoto_bitmap_archive import (  # noqa: E402
    discover_riff_palette_resource,
    iter_minifoto_records,
    load_riff_palette,
    validate_minifoto_bitmap,
)
from app.minifoto_bitmap_replace import replace_minifoto_bitmap_in_bytes  # noqa: E402
from apply_stoke_2015_squad import STOKE_2015_SQUAD  # noqa: E402
from assert_pm99_isolated_input import resolve_dbdat_dir, resolve_game_root, sha256  # noqa: E402

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"

TITLE_OVERRIDES: dict[str, list[str]] = {
    "Marko Arnautovic": ["Marko Arnautović"],
    "Joselu Mato": ["Joselu"],
    "Marc Wilson": ["Marc Wilson (footballer)"],
    "Mame Diouf": ["Mame Biram Diouf"],
}


def _now_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip())
    cleaned = cleaned.strip("_")
    return cleaned.lower() or "item"


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _load_stoke_rows(eq_file: Path, jug_file: Path, team_query: str) -> list[dict[str, Any]]:
    rosters = load_eq_linked_team_rosters(team_file=str(eq_file), player_file=str(jug_file))
    target = _normalize(team_query)
    chosen = None
    for roster in rosters:
        short_name = str(getattr(roster, "short_name", "") or "")
        full_name = str(getattr(roster, "full_club_name", "") or "")
        if target in _normalize(short_name) or target in _normalize(full_name):
            chosen = roster
            break
    if chosen is None:
        raise RuntimeError(f"Could not resolve roster for team query {team_query!r}")

    rows = sorted(list(getattr(chosen, "rows", []) or []), key=lambda row: int(getattr(row, "slot_index", 0)))
    if len(rows) < len(STOKE_2015_SQUAD):
        raise RuntimeError(f"Expected at least {len(STOKE_2015_SQUAD)} roster rows, found {len(rows)}")

    out: list[dict[str, Any]] = []
    for row in rows[: len(STOKE_2015_SQUAD)]:
        out.append(
            {
                "slot": int(getattr(row, "slot_index", 0)) + 1,
                "pid": int(getattr(row, "player_record_id", 0) or 0),
                "player_name": str(getattr(row, "player_name", "") or ""),
            }
        )
    return out


def _query_page_image(session: requests.Session, title: str, headers: dict[str, str]) -> dict[str, Any]:
    response = session.get(
        WIKIPEDIA_API,
        params={
            "action": "query",
            "format": "json",
            "prop": "pageimages",
            "piprop": "original|thumbnail",
            "pithumbsize": 640,
            "redirects": 1,
            "titles": title,
        },
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    time.sleep(0.2)
    pages = dict((payload.get("query") or {}).get("pages") or {})
    page = next(iter(pages.values()), {})
    return {
        "requested_title": title,
        "resolved_title": str(page.get("title") or title),
        "page_id": page.get("pageid"),
        "image_url": (
            ((page.get("thumbnail") or {}).get("source") if isinstance(page, dict) else None)
            or ((page.get("original") or {}).get("source") if isinstance(page, dict) else None)
        ),
    }


def _search_titles(session: requests.Session, query: str, headers: dict[str, str]) -> list[str]:
    response = session.get(
        WIKIPEDIA_API,
        params={
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": query,
            "srlimit": 8,
        },
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    time.sleep(0.2)
    return [str(item.get("title") or "") for item in list((payload.get("query") or {}).get("search") or [])]


def _download_image_bytes(
    session: requests.Session,
    *,
    image_url: str,
    headers: dict[str, str],
    max_attempts: int = 6,
) -> bytes:
    wait_seconds = 1.0
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = session.get(image_url, headers=headers, timeout=45)
            if response.status_code == 200:
                return response.content
            if response.status_code in {429, 502, 503, 504}:
                time.sleep(wait_seconds)
                wait_seconds = min(wait_seconds * 1.8, 12.0)
                continue
            response.raise_for_status()
        except Exception as exc:  # pragma: no cover - network lane
            last_error = exc
            time.sleep(wait_seconds)
            wait_seconds = min(wait_seconds * 1.8, 12.0)
            continue
        time.sleep(wait_seconds)
        wait_seconds = min(wait_seconds * 1.8, 12.0)
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Failed to download source image after retries: {image_url}")


def _resolve_player_image(
    session: requests.Session,
    *,
    player_name: str,
    headers: dict[str, str],
) -> dict[str, Any]:
    attempted_titles: list[str] = []
    candidates = list(TITLE_OVERRIDES.get(player_name, [])) + [player_name]
    for title in candidates:
        if title in attempted_titles:
            continue
        attempted_titles.append(title)
        hit = _query_page_image(session, title, headers)
        if hit.get("image_url"):
            hit["attempted_titles"] = attempted_titles
            return hit

    search_queries = [f"{player_name} footballer", player_name]
    for query in search_queries:
        for title in _search_titles(session, query, headers):
            if title in attempted_titles:
                continue
            attempted_titles.append(title)
            hit = _query_page_image(session, title, headers)
            if hit.get("image_url"):
                hit["attempted_titles"] = attempted_titles
                hit["search_query"] = query
                return hit

    return {
        "requested_title": player_name,
        "resolved_title": None,
        "page_id": None,
        "image_url": None,
        "attempted_titles": attempted_titles,
    }


def _build_palette_image(palette_rgb: list[tuple[int, int, int]]) -> Image.Image:
    palette_image = Image.new("P", (16, 16))
    palette_flat: list[int] = []
    for red, green, blue in palette_rgb[:256]:
        palette_flat.extend([int(red), int(green), int(blue)])
    if len(palette_flat) < 768:
        palette_flat.extend([0] * (768 - len(palette_flat)))
    palette_image.putpalette(palette_flat)
    return palette_image


def _crop_portrait_region(image: Image.Image) -> Image.Image:
    width, height = image.size
    if width <= 0 or height <= 0:
        raise ValueError("source image has invalid dimensions")
    if height >= width:
        crop = width
        top = int(round((height - crop) * 0.18))
        top = max(0, min(height - crop, top))
        box = (0, top, width, top + crop)
    else:
        crop = height
        left = int(round((width - crop) * 0.5))
        left = max(0, min(width - crop, left))
        box = (left, 0, left + crop, height)
    return image.crop(box)


def _build_replacement_bitmap(
    *,
    raw_bitmap_template: bytes,
    pixel_offset: int,
    width: int,
    height: int,
    source_image: Image.Image,
    palette_image: Image.Image,
    palette_rgb: list[tuple[int, int, int]],
    allowed_indices: list[int],
) -> tuple[bytes, Image.Image, Image.Image]:
    cropped = _crop_portrait_region(source_image.convert("RGB"))
    prepared = ImageOps.autocontrast(cropped, cutoff=2)
    prepared = prepared.resize((width, height), Image.Resampling.LANCZOS)

    if not allowed_indices:
        raise ValueError("allowed_indices must not be empty")
    candidate_indices = sorted(set(int(index) for index in allowed_indices if 0 <= int(index) < len(palette_rgb)))
    if not candidate_indices:
        raise ValueError("allowed_indices resolved to an empty candidate index set")
    candidate_colors = {index: palette_rgb[index] for index in candidate_indices}

    cache: dict[tuple[int, int, int], int] = {}
    top_down_array = bytearray(width * height)
    for offset, pixel in enumerate(prepared.getdata()):
        red, green, blue = (int(pixel[0]), int(pixel[1]), int(pixel[2]))
        key = (red, green, blue)
        selected = cache.get(key)
        if selected is None:
            selected = min(
                candidate_indices,
                key=lambda idx: (
                    (red - int(candidate_colors[idx][0])) ** 2
                    + (green - int(candidate_colors[idx][1])) ** 2
                    + (blue - int(candidate_colors[idx][2])) ** 2
                ),
            )
            cache[key] = selected
        top_down_array[offset] = selected

    top_down = bytes(top_down_array)
    rows = [top_down[row * width : (row + 1) * width] for row in range(height)]
    bottom_up = b"".join(reversed(rows))

    out = bytearray(raw_bitmap_template)
    start = pixel_offset
    end = pixel_offset + (width * height)
    out[start:end] = bottom_up
    replacement = bytes(out)
    validate_minifoto_bitmap(replacement)

    indexed_preview = Image.new("P", (width, height))
    indexed_preview.putpalette(palette_image.getpalette())
    indexed_preview.frombytes(top_down)
    return replacement, prepared, indexed_preview.convert("RGB")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare Stoke 2015 DBDAT override set with face replacements.")
    parser.add_argument(
        "--game-root",
        default="",
        help="Optional PM99 game root. If set, DBDAT is read from <game-root>/DBDAT.",
    )
    parser.add_argument(
        "--source-dbdat-dir",
        default="",
        help="Source DBDAT directory containing JUG/EQ/ENT/MINIFOTO. If omitted, the pristine fixture is used.",
    )
    parser.add_argument(
        "--output-root",
        default=str(REPO_ROOT / "work"),
        help="Root directory for generated milestone workspace.",
    )
    parser.add_argument(
        "--output-dir",
        help="Explicit output directory. If omitted, a timestamped work directory is created.",
    )
    parser.add_argument("--team-query", default="Stoke C.", help="Roster team query for Stoke.")
    parser.add_argument(
        "--user-agent",
        default="pm99-research-face-pipeline/1.0 (+local)",
        help="HTTP user-agent for Wikimedia API requests.",
    )
    parser.add_argument(
        "--json-output",
        help="Optional explicit manifest output path (defaults to <output-dir>/prepare_manifest.json).",
    )
    parser.add_argument(
        "--apply-to-game-root",
        default="",
        help="Optional writable isolated PM99 game root to receive the patched JUG/EQ/ENT/MINIFOTO files.",
    )
    parser.add_argument(
        "--allow-name-mismatch",
        action="store_true",
        help="Continue even when source Stoke names do not already match the Stoke 2015 target list.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    source_game_root = resolve_game_root(args.game_root, required=False) if str(args.game_root or "").strip() else None
    apply_to_game_root = (
        resolve_game_root(args.apply_to_game_root, require_writable=True, required=False)
        if str(args.apply_to_game_root or "").strip()
        else None
    )
    source_dbdat_dir = resolve_dbdat_dir(
        dbdat_dir=args.source_dbdat_dir,
        game_root=source_game_root,
        required_files=("JUG98030.FDI", "EQ98030.FDI", "ENT98030.FDI", "MINIFOTO.PKF"),
        default_to_fixture=not bool(source_game_root),
    )
    output_root = Path(args.output_root).expanduser().resolve()
    timestamp = _now_stamp()

    if args.output_dir:
        output_dir = Path(args.output_dir).expanduser().resolve()
    else:
        output_dir = (output_root / f"stoke_2015_face_milestone_{timestamp}").resolve()

    game_dir = output_dir / "game"
    dbdat_dir = game_dir / "DBDAT"
    apply_artifacts_dir = output_dir / "apply"
    sources_dir = output_dir / "face_sources"
    generated_dir = output_dir / "generated_faces"

    output_dir.mkdir(parents=True, exist_ok=True)
    dbdat_dir.mkdir(parents=True, exist_ok=True)
    apply_artifacts_dir.mkdir(parents=True, exist_ok=True)
    sources_dir.mkdir(parents=True, exist_ok=True)
    generated_dir.mkdir(parents=True, exist_ok=True)

    required_files = ("JUG98030.FDI", "EQ98030.FDI", "ENT98030.FDI", "MINIFOTO.PKF")
    for file_name in required_files:
        source_file = source_dbdat_dir / file_name
        if not source_file.is_file():
            raise FileNotFoundError(f"Missing required source file: {source_file}")
        shutil.copy2(source_file, dbdat_dir / file_name)

    eq_file = dbdat_dir / "EQ98030.FDI"
    jug_file = dbdat_dir / "JUG98030.FDI"
    ent_file = dbdat_dir / "ENT98030.FDI"
    minifoto_file = dbdat_dir / "MINIFOTO.PKF"

    apply_summary_path = apply_artifacts_dir / "summary.json"
    slot_rows = _load_stoke_rows(eq_file, jug_file, args.team_query)
    name_mismatches: list[dict[str, Any]] = []
    for slot in range(1, len(STOKE_2015_SQUAD) + 1):
        observed = str(slot_rows[slot - 1].get("player_name") or "")
        expected = STOKE_2015_SQUAD[slot - 1]
        if observed.strip().lower() != expected.strip().lower():
            name_mismatches.append(
                {
                    "slot": slot,
                    "pid": int(slot_rows[slot - 1].get("pid") or 0),
                    "observed_name": observed,
                    "expected_name": expected,
                }
            )

    apply_summary = {
        "success": not bool(name_mismatches) or bool(args.allow_name_mismatch),
        "mode": "pre_applied_source_dbdat",
        "team_query": str(args.team_query),
        "slot_rows_observed": slot_rows,
        "name_mismatches": name_mismatches,
        "allow_name_mismatch": bool(args.allow_name_mismatch),
    }
    apply_summary_path.write_text(json.dumps(apply_summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if name_mismatches and not bool(args.allow_name_mismatch):
        raise RuntimeError(
            "Source DBDAT does not already contain Stoke 2015 names. "
            "Re-run with --allow-name-mismatch to continue anyway."
        )
    minifoto_records = {record.player_record_id: record for record in iter_minifoto_records(minifoto_file)}
    minifoto_bytes = minifoto_file.read_bytes()

    palette_path, palette_source = discover_riff_palette_resource(minifoto_file, extra_roots=[source_dbdat_dir, game_dir])
    if palette_path is None:
        raise RuntimeError("Could not discover palette resource for MINIFOTO conversion.")
    palette_rgb = load_riff_palette(palette_path)
    palette_image = _build_palette_image(palette_rgb)

    session = requests.Session()
    headers = {"User-Agent": str(args.user_agent)}

    patch_results: list[dict[str, Any]] = []
    image_cache: dict[str, dict[str, Any]] = {}

    for slot in range(1, len(STOKE_2015_SQUAD) + 1):
        target_name = STOKE_2015_SQUAD[slot - 1]
        row = slot_rows[slot - 1]
        pid = int(row.get("pid", 0) or 0)
        current_name = str(row.get("player_name") or "")
        entry: dict[str, Any] = {
            "slot": slot,
            "target_name": target_name,
            "pid": pid,
            "current_name_after_apply": current_name,
            "has_bitmap": bool(pid in minifoto_records),
        }

        if pid not in minifoto_records:
            entry["status"] = "skipped_missing_bitmap"
            patch_results.append(entry)
            continue

        if target_name not in image_cache:
            image_cache[target_name] = _resolve_player_image(session, player_name=target_name, headers=headers)
        image_info = dict(image_cache[target_name])
        entry["image_lookup"] = image_info
        image_url = str(image_info.get("image_url") or "")
        if not image_url:
            entry["status"] = "skipped_missing_source_image"
            patch_results.append(entry)
            continue

        image_bytes = _download_image_bytes(session, image_url=image_url, headers=headers)
        extension = Path(urlparse(image_url).path).suffix.lower() or ".jpg"
        source_image_path = sources_dir / f"{slot:02d}_{pid}_{_slug(target_name)}{extension}"
        source_image_path.write_bytes(image_bytes)

        with Image.open(io.BytesIO(image_bytes)) as source_image:
            record = minifoto_records[pid]
            original_pixels = record.raw_bitmap[record.pixel_offset : record.pixel_offset + (record.width * record.height)]
            replacement_bitmap, prepared_face, indexed_preview = _build_replacement_bitmap(
                raw_bitmap_template=record.raw_bitmap,
                pixel_offset=record.pixel_offset,
                width=record.width,
                height=record.height,
                source_image=source_image,
                palette_image=palette_image,
                palette_rgb=palette_rgb,
                allowed_indices=sorted(set(original_pixels)),
            )

        prepared_face_path = generated_dir / f"{slot:02d}_{pid}_{_slug(target_name)}_crop.png"
        preview_path = generated_dir / f"{slot:02d}_{pid}_{_slug(target_name)}_preview.png"
        replacement_bmp_path = generated_dir / f"{slot:02d}_{pid}_{_slug(target_name)}.bmp"
        prepared_face.save(prepared_face_path)
        indexed_preview.save(preview_path)
        replacement_bmp_path.write_bytes(replacement_bitmap)

        minifoto_bytes, replace_result = replace_minifoto_bitmap_in_bytes(
            minifoto_bytes,
            replacement_bitmap,
            archive_name=minifoto_file.name,
            player_record_id=pid,
        )

        entry["status"] = "patched"
        entry["replace_result"] = asdict(replace_result)
        entry["source_image_path"] = str(source_image_path)
        entry["prepared_face_path"] = str(prepared_face_path)
        entry["preview_path"] = str(preview_path)
        entry["replacement_bmp_path"] = str(replacement_bmp_path)
        patch_results.append(entry)

    minifoto_original_path = output_dir / "MINIFOTO.original.PKF"
    minifoto_patched_path = output_dir / "MINIFOTO.patched.PKF"
    minifoto_original_path.write_bytes(minifoto_file.read_bytes())
    minifoto_patched_path.write_bytes(minifoto_bytes)
    minifoto_file.write_bytes(minifoto_bytes)

    applied_files: dict[str, Any] = {}
    if apply_to_game_root is not None:
        target_dbdat_dir = apply_to_game_root / "DBDAT"
        for file_name in required_files:
            target_file = target_dbdat_dir / file_name
            source_file = dbdat_dir / file_name
            before_hash = sha256(target_file) if target_file.exists() else ""
            shutil.copy2(source_file, target_file)
            applied_files[file_name] = {
                "target_path": str(target_file),
                "before_sha256": before_hash,
                "after_sha256": sha256(target_file),
            }

    patched_count = sum(1 for item in patch_results if item.get("status") == "patched")
    missing_bitmap_count = sum(1 for item in patch_results if item.get("status") == "skipped_missing_bitmap")
    missing_source_count = sum(1 for item in patch_results if item.get("status") == "skipped_missing_source_image")

    manifest = {
        "scope": "stoke_2015_face_dbdat_prepare",
        "timestamp_utc": timestamp,
        "source_game_root": str(source_game_root) if source_game_root is not None else "",
        "apply_to_game_root": str(apply_to_game_root) if apply_to_game_root is not None else "",
        "source_dbdat_dir": str(source_dbdat_dir),
        "source_hashes": {
            file_name: sha256(source_dbdat_dir / file_name)
            for file_name in ("JUG98030.FDI", "EQ98030.FDI", "ENT98030.FDI", "MINIFOTO.PKF")
        },
        "output_dir": str(output_dir),
        "game_dir": str(game_dir),
        "dbdat_override_dir": str(dbdat_dir),
        "apply_summary_path": str(apply_summary_path),
        "apply_summary": apply_summary,
        "palette_path": str(palette_path),
        "palette_source": palette_source,
        "slot_rows_after_apply": slot_rows,
        "patch_results": patch_results,
        "counts": {
            "slots_total": len(STOKE_2015_SQUAD),
            "patched": patched_count,
            "skipped_missing_bitmap": missing_bitmap_count,
            "skipped_missing_source_image": missing_source_count,
        },
        "outputs": {
            "minifoto_original": str(minifoto_original_path),
            "minifoto_patched": str(minifoto_patched_path),
            "face_sources_dir": str(sources_dir),
            "generated_faces_dir": str(generated_dir),
            "applied_files": applied_files,
            "hashes": {
                "JUG98030.FDI": sha256(jug_file),
                "EQ98030.FDI": sha256(eq_file),
                "ENT98030.FDI": sha256(ent_file),
                "MINIFOTO.original.PKF": sha256(minifoto_original_path),
                "MINIFOTO.patched.PKF": sha256(minifoto_patched_path),
                "MINIFOTO.PKF": sha256(minifoto_file),
            },
        },
    }

    manifest_path = Path(args.json_output).expanduser().resolve() if args.json_output else output_dir / "prepare_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "success": True,
                "prepare_manifest": str(manifest_path),
                "dbdat_override_dir": str(dbdat_dir),
                "patched_slots": patched_count,
                "missing_bitmap_slots": missing_bitmap_count,
                "missing_source_slots": missing_source_count,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
