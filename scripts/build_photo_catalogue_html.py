#!/usr/bin/env python3
"""Build a local HTML catalogue for PM99 investigation photos."""

from __future__ import annotations

import argparse
import glob
import html
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from string import Template


REPO = Path("/home/joe/pm99-research")
SKEZWEB = Path("/home/joe/skezmod-web")
WORK = REPO / "work"
ARTIFACTS = REPO / "artifacts"
RUNNER = REPO / "upstream" / "pm99-runner" / "docs" / "artifacts" / "pm99_runner"

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}


@dataclass(frozen=True)
class SubsectionSpec:
    label: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class SectionSpec:
    slug: str
    title: str
    summary: str
    default_open: bool
    cover: str
    subsections: tuple[SubsectionSpec, ...]


@dataclass
class Entry:
    source: Path
    asset: Path
    caption: str
    search_text: str
    source_url: str
    source_display: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a PM99 photo catalogue HTML page.")
    parser.add_argument(
        "--output-dir",
        default=str(REPO / "work" / "photo_catalogue"),
        help="Directory to write the catalogue into.",
    )
    return parser.parse_args()


def resolve_globs(patterns: Iterable[str]) -> list[Path]:
    resolved: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        for item in sorted(glob.glob(pattern)):
            path = Path(item)
            if not path.is_file():
                continue
            if path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            real = path.resolve()
            if real in seen:
                continue
            seen.add(real)
            resolved.append(path)
    return resolved


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def display_caption(path: Path) -> str:
    stem = path.stem
    stem = re.sub(r"^J\d+_", "", stem)
    stem = stem.replace("_", " ").replace("-", " ")
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem or path.name


def shorten_path(path: Path) -> str:
    for base in (REPO, SKEZWEB, Path("/home/joe")):
        try:
            rel = path.resolve().relative_to(base.resolve())
            return f"~/{rel.as_posix()}"
        except Exception:
            pass
    return str(path.resolve())


def to_file_url(path: Path) -> str:
    return path.resolve().as_uri()


def ensure_symlink(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        target.unlink()
    os.symlink(source.resolve(), target)


def build_entries(*, output_dir: Path, section_slug: str, subsection_slug: str, patterns: Iterable[str]) -> list[Entry]:
    entries: list[Entry] = []
    for index, source in enumerate(resolve_globs(patterns), start=1):
        safe_name = f"{index:03d}-{source.name}"
        asset = Path("assets") / section_slug / subsection_slug / safe_name
        ensure_symlink(source, output_dir / asset)
        caption = display_caption(source)
        source_display = shorten_path(source)
        entries.append(
            Entry(
                source=source,
                asset=asset,
                caption=caption,
                search_text=" ".join(
                    [caption, source.name, source_display, section_slug, subsection_slug]
                ).lower(),
                source_url=to_file_url(source),
                source_display=source_display,
            )
        )
    return entries


def pick_cover(output_dir: Path, section_slug: str, cover_pattern: str) -> str | None:
    cover_candidates = resolve_globs([cover_pattern])
    if not cover_candidates:
        return None
    cover = cover_candidates[0]
    cover_asset = Path("assets") / section_slug / "_cover" / f"cover-{cover.name}"
    ensure_symlink(cover, output_dir / cover_asset)
    return cover_asset.as_posix()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    assets_dir = output_dir / "assets"
    validation_dir = output_dir / "validation"

    if assets_dir.exists():
        shutil.rmtree(assets_dir)
    if validation_dir.exists():
        shutil.rmtree(validation_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)
    validation_dir.mkdir(parents=True, exist_ok=True)

    sections_spec = [
        SectionSpec(
            slug="title-badge",
            title="Title badge",
            summary="The little corner badge looked like a string, but it came from code. This section keeps the final screenshot separate from the earlier title-screen proof runs.",
            default_open=True,
            cover=str(SKEZWEB / "public" / "articles" / "title-badge" / "hero.png"),
            subsections=(
                SubsectionSpec(
                    label="Article-ready",
                    paths=(
                        str(SKEZWEB / "public" / "articles" / "title-badge" / "hero.png"),
                        str(SKEZWEB / "public" / "articles" / "title-badge" / "badge-flow.svg"),
                    ),
                ),
                SubsectionSpec(
                    label="Proof runs",
                    paths=(
                        str(WORK / "title_badge_validation" / "title_badge_skezmod_00_title.png"),
                        str(WORK / "title_badge_validation" / "title_badge_skezmod_v2_00_title.png"),
                        str(WORK / "title_badge_validation" / "title_badge_skezmod_smoke_00_smoke.png"),
                    ),
                ),
            ),
        ),
        SectionSpec(
            slug="minifoto",
            title="MINIFOTO / Graham Kavanagh",
            summary="A portrait swap that only makes sense once you see the before, the after, and the difference between them.",
            default_open=True,
            cover=str(SKEZWEB / "public" / "articles" / "minifoto" / "hero.png"),
            subsections=(
                SubsectionSpec(
                    label="Article-ready",
                    paths=(
                        str(SKEZWEB / "public" / "articles" / "minifoto" / "hero.png"),
                        str(SKEZWEB / "public" / "articles" / "minifoto" / "before.png"),
                        str(SKEZWEB / "public" / "articles" / "minifoto" / "after.png"),
                        str(SKEZWEB / "public" / "articles" / "minifoto" / "diff.png"),
                    ),
                ),
                SubsectionSpec(
                    label="Palette proof",
                    paths=(str(WORK / "minifoto_smiley_validation" / "20260409T211409Z" / "*.png"),),
                ),
                SubsectionSpec(
                    label="Runner comparison",
                    paths=(str(WORK / "minifoto_smiley_validation" / "runner_row10_compare_20260409T232732Z" / "*.png"),),
                ),
            ),
        ),
        SectionSpec(
            slug="staff-lists",
            title="Staff lists that do not stay put",
            summary="Two fresh starts of the same club landed on different staff lists. The article set shows the comparison; the proof folders show the full runs.",
            default_open=True,
            cover=str(SKEZWEB / "public" / "articles" / "staff" / "hero.png"),
            subsections=(
                SubsectionSpec(
                    label="Article-ready",
                    paths=(
                        str(SKEZWEB / "public" / "articles" / "staff" / "hero.png"),
                        str(SKEZWEB / "public" / "articles" / "staff" / "run1.png"),
                        str(SKEZWEB / "public" / "articles" / "staff" / "run2.png"),
                        str(SKEZWEB / "public" / "articles" / "staff" / "compare.png"),
                    ),
                ),
                SubsectionSpec(
                    label="Run 1",
                    paths=(str(RUNNER / "manutd_prem_staff_clean_run1" / "screens" / "*.png"),),
                ),
                SubsectionSpec(
                    label="Run 2",
                    paths=(str(RUNNER / "manutd_prem_staff_clean_run2" / "screens" / "*.png"),),
                ),
                SubsectionSpec(
                    label="Comparison",
                    paths=(str(RUNNER / "manutd_prem_staff_run1_vs_run2_staff.png"),),
                ),
            ),
        ),
        SectionSpec(
            slug="stoke-crash",
            title="Stoke crash and late injection",
            summary="This is the story where the bug looked like one crash but turned out to be two separate failures. The proof set stays apart from the squad-route story.",
            default_open=True,
            cover=str(SKEZWEB / "public" / "articles" / "stoke" / "hero.png"),
            subsections=(
                SubsectionSpec(
                    label="Article-ready",
                    paths=(
                        str(SKEZWEB / "public" / "articles" / "stoke" / "hero.png"),
                        str(SKEZWEB / "public" / "articles" / "stoke" / "continue-after-rivals.png"),
                        str(SKEZWEB / "public" / "articles" / "stoke" / "blocking-modal.png"),
                        str(SKEZWEB / "public" / "articles" / "stoke" / "late-inject.png"),
                    ),
                ),
                SubsectionSpec(
                    label="No-inject proof",
                    paths=(str(RUNNER / "stoke_2015_noinject_validate4_20260410T203355Z" / "screens" / "*.png"),),
                ),
                SubsectionSpec(
                    label="Late-inject proof",
                    paths=(
                        str(RUNNER / "stoke_2015_faces_lateinject_v2_20260410T131057Z" / "screens" / "*.png"),
                        str(RUNNER / "stoke_2015_faces_lateinject_v2_20260410T131057Z" / "profiles" / "*.png"),
                    ),
                ),
            ),
        ),
        SectionSpec(
            slug="stoke-squad-route",
            title="Stoke 2015: getting into the squad",
            summary="The route from title screen to selected team. Kept separate from the Valderrama offer path so the two stories stay cleanly divided.",
            default_open=True,
            cover=str(SKEZWEB / "public" / "articles" / "stoke-2015" / "hero.png"),
            subsections=(
                SubsectionSpec(
                    label="Article-ready",
                    paths=(
                        str(SKEZWEB / "public" / "articles" / "stoke-2015" / "hero.png"),
                        str(SKEZWEB / "public" / "articles" / "stoke-2015" / "title.png"),
                        str(SKEZWEB / "public" / "articles" / "stoke-2015" / "league.png"),
                        str(SKEZWEB / "public" / "articles" / "stoke-2015" / "second-division.png"),
                        str(SKEZWEB / "public" / "articles" / "stoke-2015" / "pick-team.png"),
                        str(SKEZWEB / "public" / "articles" / "stoke-2015" / "continue-team.png"),
                        str(SKEZWEB / "public" / "articles" / "stoke-2015" / "squad-route.png"),
                    ),
                ),
                SubsectionSpec(
                    label="Runner walk-through",
                    paths=(str(ARTIFACTS / "stoke_2015_metadata_20260410" / "runner_verify" / "screens" / "*.png"),),
                ),
            ),
        ),
        SectionSpec(
            slug="valderrama-offer-path",
            title="Valderrama, the row, and the offer path",
            summary="A separate story with its own screen path, its own offer screens, and its own final article images. This is not the Stoke squad route.",
            default_open=True,
            cover=str(SKEZWEB / "public" / "articles" / "stars" / "hero.png"),
            subsections=(
                SubsectionSpec(
                    label="Article-ready",
                    paths=(
                        str(SKEZWEB / "public" / "articles" / "stars" / "hero.png"),
                        str(SKEZWEB / "public" / "articles" / "stars" / "transfers.png"),
                        str(SKEZWEB / "public" / "articles" / "stars" / "player-row.png"),
                        str(SKEZWEB / "public" / "articles" / "stars" / "two-surfaces.svg"),
                        str(SKEZWEB / "public" / "articles" / "stoke-2015" / "offer-primary.png"),
                        str(SKEZWEB / "public" / "articles" / "stoke-2015" / "offer-fallback.png"),
                        str(SKEZWEB / "public" / "articles" / "stoke-2015" / "valderrama-route.png"),
                        str(SKEZWEB / "public" / "articles" / "stoke-2015" / "path.svg"),
                    ),
                ),
                SubsectionSpec(
                    label="Offer proof",
                    paths=(str(WORK / "runner_valderrama_offer_path_20260410" / "screens" / "*.png"),),
                ),
            ),
        ),
        SectionSpec(
            slug="stoke-eq-jug-split",
            title="Stoke EQ / JUG split",
            summary="A narrower proof wall for the split investigation. It is useful as supporting evidence, but it is not one of the article lead images.",
            default_open=False,
            cover=str(ARTIFACTS / "research" / "stoke_eq_jug_split_20260410T214430Z" / "eq" / "26_continue_after_rivals.png"),
            subsections=(
                SubsectionSpec(
                    label="EQ lane",
                    paths=(str(ARTIFACTS / "research" / "stoke_eq_jug_split_20260410T214430Z" / "eq" / "*.png"),),
                ),
                SubsectionSpec(
                    label="JUG lane",
                    paths=(str(ARTIFACTS / "research" / "stoke_eq_jug_split_20260410T214430Z" / "jug" / "*.png"),),
                ),
            ),
        ),
        SectionSpec(
            slug="player-bitmap-review",
            title="Player bitmap review wall",
            summary="The broad portrait corpus. This is the room to open when you want to choose a face, compare options, or see how many portraits are actually in play.",
            default_open=False,
            cover=str(WORK / "player_bitmap_review_20260408T114609Z" / "J9600025_Albert_FERRER.png"),
            subsections=(
                SubsectionSpec(
                    label="Raw review set",
                    paths=(str(WORK / "player_bitmap_review_20260408T114609Z" / "*.png"),),
                ),
            ),
        ),
    ]

    sections: list[dict] = []
    total_images = 0

    for spec in sections_spec:
        section = {
            "slug": spec.slug,
            "title": spec.title,
            "summary": spec.summary,
            "default_open": spec.default_open,
            "cover": None,
            "subsections": [],
            "count": 0,
        }
        for subsection in spec.subsections:
            entries = build_entries(
                output_dir=output_dir,
                section_slug=spec.slug,
                subsection_slug=slugify(subsection.label),
                patterns=subsection.paths,
            )
            section["subsections"].append(
                {
                    "label": subsection.label,
                    "entries": entries,
                    "count": len(entries),
                }
            )
            section["count"] += len(entries)
        section["cover"] = pick_cover(output_dir, spec.slug, spec.cover)
        sections.append(section)
        total_images += section["count"]

    manifest = {
        "generated_at": "2026-04-12",
        "total_images": total_images,
        "sections": [
            {
                "slug": section["slug"],
                "title": section["title"],
                "summary": section["summary"],
                "default_open": section["default_open"],
                "count": section["count"],
                "subsections": [
                    {
                        "label": subgroup["label"],
                        "count": subgroup["count"],
                        "entries": [
                            {
                                "caption": entry.caption,
                                "asset": entry.asset.as_posix(),
                                "source": str(entry.source.resolve()),
                                "source_display": entry.source_display,
                                "source_url": entry.source_url,
                                "search_text": entry.search_text,
                            }
                            for entry in subgroup["entries"]
                        ],
                    }
                    for subgroup in section["subsections"]
                ],
            }
            for section in sections
        ],
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    nav_links = "\n".join(
        f"<a class='nav-pill' href='#{section['slug']}'>{html.escape(section['title'])}</a>"
        for section in sections
    )

    summary_cards = "\n".join(
        f"""
        <div class="metric">
          <strong>{section['count']}</strong>
          <span>{html.escape(section['title'])}</span>
        </div>
        """
        for section in sections
    )

    section_html: list[str] = []
    for section in sections:
        cover_html = ""
        if section["cover"]:
            cover_html = f"""
              <div class="cover">
                <img loading="lazy" decoding="async" src="{html.escape(section['cover'])}" alt="{html.escape(section['title'])} cover">
              </div>
            """

        subgroup_html: list[str] = []
        for subgroup in section["subsections"]:
            if not subgroup["entries"]:
                continue
            cards = []
            for entry in subgroup["entries"]:
                cards.append(
                    f"""
                    <figure class="photo-card" data-search="{html.escape(entry.search_text)}">
                      <a href="{html.escape(entry.source_url)}" target="_blank" rel="noreferrer">
                        <img loading="lazy" decoding="async" src="{html.escape(entry.asset.as_posix())}" alt="{html.escape(entry.caption)}">
                      </a>
                      <figcaption>
                        <strong>{html.escape(entry.caption)}</strong>
                        <span>{html.escape(entry.source_display)}</span>
                      </figcaption>
                    </figure>
                    """
                )
            subgroup_html.append(
                f"""
                <section class="subgroup">
                  <div class="subgroup-head">
                    <h3>{html.escape(subgroup['label'])}</h3>
                    <span>{subgroup['count']} images</span>
                  </div>
                  <div class="gallery">
                    {''.join(cards)}
                  </div>
                </section>
                """
            )

        section_html.append(
            f"""
            <details class="section" id="{html.escape(section['slug'])}" {'open' if section['default_open'] else ''} data-default-open="{str(section['default_open']).lower()}">
              <summary>
                <div class="summary-text">
                  <strong>{html.escape(section['title'])}</strong>
                  <span>{html.escape(section['summary'])}</span>
                </div>
                <div class="summary-count">{section['count']} images</div>
              </summary>
              <div class="section-body">
                {cover_html}
                {''.join(subgroup_html)}
              </div>
            </details>
            """
        )

    css = """
    :root {
      --paper: #f4efe4;
      --ink: #172033;
      --muted: #5c6472;
      --line: rgba(23, 32, 51, 0.14);
      --panel: rgba(255, 252, 246, 0.88);
      --panel-strong: rgba(255, 255, 255, 0.94);
      --accent: #274f7a;
      --shadow: 0 20px 60px rgba(20, 30, 52, 0.12);
      --radius: 24px;
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      color: var(--ink);
      background: linear-gradient(180deg, #faf6ef 0%, var(--paper) 34%, #ece2d2 100%);
      font-family: "Avenir Next", "Segoe UI", "Trebuchet MS", sans-serif;
      line-height: 1.5;
    }
    a { color: var(--accent); }
    .wrap { width: min(1480px, calc(100vw - 40px)); margin: 0 auto; }
    .hero { padding: 34px 0 18px; }
    .hero-shell {
      color: #f9f5ee;
      background: linear-gradient(135deg, rgba(23, 32, 51, 0.96), rgba(18, 31, 62, 0.92));
      border-radius: 34px;
      box-shadow: var(--shadow);
      padding: 32px;
    }
    .eyebrow {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      text-transform: uppercase;
      letter-spacing: 0.14em;
      font-size: 12px;
      color: rgba(249, 245, 238, 0.76);
    }
    .eyebrow::before {
      content: "";
      width: 38px;
      height: 1px;
      background: rgba(249, 245, 238, 0.38);
    }
    h1, h2, h3 {
      font-family: Georgia, "Times New Roman", serif;
      letter-spacing: -0.02em;
      margin: 0;
    }
    h1 {
      font-size: clamp(2.4rem, 6vw, 4.7rem);
      line-height: 0.96;
      margin: 14px 0 12px;
      max-width: 10.5ch;
    }
    .hero-copy { max-width: 780px; font-size: 1.05rem; color: rgba(249, 245, 238, 0.88); }
    .hero-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
      margin-top: 24px;
    }
    .metric {
      padding: 16px 18px;
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid rgba(255, 255, 255, 0.12);
    }
    .metric strong { display: block; font-size: 1.4rem; color: #fff8ef; margin-bottom: 4px; }
    .metric span { color: rgba(249, 245, 238, 0.76); font-size: 0.92rem; }
    .nav-bar {
      position: sticky;
      top: 0;
      z-index: 25;
      backdrop-filter: blur(12px);
      background: rgba(244, 239, 228, 0.9);
      border-bottom: 1px solid var(--line);
    }
    .nav-row {
      display: flex;
      gap: 10px;
      overflow-x: auto;
      padding: 12px 0 10px;
      scrollbar-width: thin;
    }
    .nav-pill {
      flex: 0 0 auto;
      display: inline-flex;
      align-items: center;
      text-decoration: none;
      padding: 10px 14px;
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--ink);
      background: rgba(255, 255, 255, 0.66);
      font-size: 0.93rem;
    }
    main { padding: 22px 0 72px; }
    .controls {
      display: grid;
      grid-template-columns: minmax(280px, 1fr) auto auto;
      gap: 12px;
      align-items: center;
      margin: 18px 0 14px;
    }
    .search {
      width: 100%;
      padding: 14px 16px;
      border-radius: 16px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.78);
      color: var(--ink);
      font: inherit;
      box-shadow: var(--shadow);
    }
    .button {
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.74);
      color: var(--ink);
      padding: 12px 14px;
      border-radius: 14px;
      font: inherit;
      cursor: pointer;
      box-shadow: var(--shadow);
    }
    .note { margin: 0 0 14px; color: var(--muted); max-width: 980px; }
    .section {
      margin: 18px 0;
      border-radius: var(--radius);
      border: 1px solid rgba(23, 32, 51, 0.1);
      background: var(--panel);
      box-shadow: var(--shadow);
      overflow: clip;
    }
    .section > summary {
      list-style: none;
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
      cursor: pointer;
      padding: 20px 24px;
      border-bottom: 1px solid rgba(23, 32, 51, 0.08);
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.5), rgba(255, 255, 255, 0.18));
    }
    .section > summary::-webkit-details-marker { display: none; }
    .summary-text strong { display: block; font-size: 1.42rem; margin-bottom: 4px; }
    .summary-text span { display: block; color: var(--muted); max-width: 950px; }
    .summary-count {
      flex: 0 0 auto;
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(39, 79, 122, 0.08);
      color: var(--accent);
      border: 1px solid rgba(39, 79, 122, 0.16);
      font-weight: 600;
    }
    .section-body { padding: 20px 22px 24px; }
    .cover {
      margin-bottom: 18px;
      border-radius: 22px;
      overflow: hidden;
      border: 1px solid rgba(23, 32, 51, 0.12);
      background: #10161f;
      box-shadow: 0 16px 40px rgba(20, 30, 52, 0.12);
    }
    .cover img {
      width: 100%;
      display: block;
      max-height: 430px;
      object-fit: cover;
      object-position: center;
    }
    .subgroup { margin: 18px 0 24px; }
    .subgroup-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
      margin-bottom: 12px;
    }
    .subgroup-head h3 { font-size: 1.16rem; }
    .subgroup-head span { color: var(--muted); font-size: 0.95rem; }
    .gallery {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
      gap: 14px;
    }
    .photo-card {
      margin: 0;
      border-radius: 18px;
      overflow: hidden;
      background: var(--panel-strong);
      border: 1px solid rgba(23, 32, 51, 0.11);
      box-shadow: 0 12px 28px rgba(20, 30, 52, 0.08);
    }
    .photo-card a { display: block; background: #111923; }
    .photo-card img {
      width: 100%;
      height: 168px;
      object-fit: contain;
      display: block;
      background: #111923;
    }
    .photo-card figcaption {
      padding: 10px 11px 12px;
      display: grid;
      gap: 4px;
    }
    .photo-card strong { display: block; font-size: 0.93rem; line-height: 1.25; }
    .photo-card span { display: block; color: var(--muted); font-size: 0.8rem; overflow-wrap: anywhere; }
    .hidden-by-filter { display: none !important; }
    .footer { margin-top: 20px; color: var(--muted); font-size: 0.92rem; }
    @media (max-width: 900px) {
      .controls { grid-template-columns: 1fr; }
      .section > summary { flex-direction: column; align-items: flex-start; }
      .summary-count { align-self: flex-start; }
    }
    """

    js = """
    const search = document.getElementById('search');
    const expandAll = document.getElementById('expand-all');
    const collapseAll = document.getElementById('collapse-all');
    const sections = Array.from(document.querySelectorAll('details.section'));

    function restoreOpenState() {
      sections.forEach((section) => {
        section.open = section.dataset.defaultOpen === 'true';
      });
    }

    function updateFilter() {
      const query = search.value.trim().toLowerCase();

      sections.forEach((section) => {
        const cards = Array.from(section.querySelectorAll('[data-search]'));
        let sectionMatch = false;
        cards.forEach((card) => {
          const hit = !query || card.dataset.search.includes(query);
          card.classList.toggle('hidden-by-filter', !hit);
          if (hit) {
            sectionMatch = true;
          }
        });

        section.classList.toggle('hidden-by-filter', query.length > 0 && !sectionMatch);
        if (query.length > 0) {
          section.open = sectionMatch;
        } else {
          section.open = section.dataset.defaultOpen === 'true';
        }
      });
    }

    search.addEventListener('input', updateFilter);
    expandAll.addEventListener('click', () => sections.forEach((section) => { section.open = true; }));
    collapseAll.addEventListener('click', () => sections.forEach((section) => { section.open = false; }));
    restoreOpenState();
    """

    parts = [
        "<!doctype html>",
        "<html lang='en'>",
        "<head>",
        "<meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>PM99 Investigation Photo Catalogue</title>",
        "<style>",
        css,
        "</style>",
        "</head>",
        "<body>",
        "<div class='wrap'>",
        "<header class='hero'>",
        "<div class='hero-shell'>",
        "<div class='eyebrow'>PM99 research catalogue</div>",
        "<h1>Investigation photo catalogue</h1>",
        "<p class='hero-copy'>A working wall of the images behind the articles: the finished story pictures, the proof runs, and the larger raw review sets. The sections stay separate so Stoke, Valderrama, and the other threads are easy to compare without blending them together.</p>",
        "<div class='hero-grid'>",
        summary_cards,
        "</div>",
        "</div>",
        "</header>",
        "<div class='nav-bar'><div class='wrap nav-row'>",
        nav_links,
        "</div></div>",
        "<main>",
        "<div class='controls'>",
        "<input id='search' class='search' type='search' placeholder='Search by player, folder, story, or filename'>",
        "<button class='button' id='expand-all' type='button'>Expand all</button>",
        "<button class='button' id='collapse-all' type='button'>Collapse all</button>",
        "</div>",
        "<p class='note'>Start with the story sections at the top. Open the proof groups when you want the full run. The portrait wall is the biggest set, so it stays collapsed until you need it.</p>",
        "".join(section_html),
        "<div class='footer'>Generated from local PM99 research assets on 2026-04-12. Click any image to open the source file.</div>",
        "</main>",
        "</div>",
        "<script>",
        js,
        "</script>",
        "</body>",
        "</html>",
    ]
    html_text = "\n".join(parts)
    (output_dir / "index.html").write_text(html_text, encoding="utf-8")

    summary = {
        "output_dir": str(output_dir),
        "total_images": total_images,
        "section_count": len(sections),
        "sections": [
            {"slug": section["slug"], "title": section["title"], "count": section["count"]}
            for section in sections
        ],
    }
    (validation_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
