#!/usr/bin/env python3
"""Build a local PM99 artifact image browser grouped by run."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote


REPO = Path(__file__).resolve().parents[1]
ARTICLE_ROOT = Path("/home/joe/skezmod-web/public/articles")
REPO_RESOLVED = REPO.resolve()
ARTICLE_ROOT_RESOLVED = ARTICLE_ROOT.resolve()

IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".svg",
}

SKIP_DIR_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".venv-web-run",
    ".vite",
    "__pycache__",
    "coverage",
    "dist",
    "node_modules",
    "venv",
}

GENERATED_DIRS = (
    REPO / "work" / "artifact_browser",
    REPO / "work" / "photo_catalogue",
)

DETAIL_DIR_NAMES = {
    "capture",
    "captures",
    "gallery",
    "guided",
    "image",
    "images",
    "imgs",
    "new_game",
    "profile",
    "profiles",
    "proof",
    "proofs",
    "screen",
    "screens",
    "snapshot",
    "snapshots",
    "thumbs",
    "thumbnails",
    "validation",
    "window_debug",
}

TIMESTAMP_RE = re.compile(r"((?:19|20)\d{6})(?:T(\d{4,6})Z?)?")
NATURAL_RE = re.compile(r"(\d+)")


@dataclass
class ImageEntry:
    path: Path
    rel_to_run: Path
    caption: str
    size_bytes: int
    mtime: float


@dataclass
class RunGroup:
    run_dir: Path
    root_label: str
    mtime: float = 0.0
    images: list[ImageEntry] = field(default_factory=list)

    @property
    def newest_mtime(self) -> float:
        return max((self.mtime, *(entry.mtime for entry in self.images)))

    @property
    def total_size(self) -> int:
        return sum(entry.size_bytes for entry in self.images)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a static HTML browser for local artifact images."
    )
    parser.add_argument(
        "--output-dir",
        default=str(REPO / "work" / "artifact_browser"),
        help="Directory to write index.html and artifact-data.js into.",
    )
    parser.add_argument(
        "--root",
        action="append",
        default=[],
        help="Additional image root to scan. Can be passed more than once.",
    )
    parser.add_argument(
        "--no-default-roots",
        action="store_true",
        help="Only scan roots passed with --root.",
    )
    parser.add_argument(
        "--max-images",
        type=int,
        default=0,
        help="Stop after this many images. Default: no limit.",
    )
    parser.add_argument(
        "--include-generated",
        action="store_true",
        help="Include previously generated catalogue/browser folders.",
    )
    parser.add_argument(
        "--stat-images",
        action="store_true",
        help="Collect per-image size and modified time. Slower on large artifact trees.",
    )
    return parser.parse_args()


def default_roots() -> list[Path]:
    return [
        REPO / "docs" / "artifacts",
        REPO / "artifacts",
        REPO / "upstream" / "pm99-runner" / "docs" / "artifacts",
        REPO / "upstream" / "pm99-skezmod-db-editor" / "docs" / "artifacts",
        REPO / "tools" / "pm99-in-a-browser" / ".local" / "proof",
        ARTICLE_ROOT,
    ]


def is_relative_to(path: Path, base: Path) -> bool:
    try:
        return os.path.commonpath((os.fspath(path), os.fspath(base))) == os.fspath(base)
    except ValueError:
        return False


def natural_key(value: str) -> list[object]:
    return [int(part) if part.isdigit() else part.lower() for part in NATURAL_RE.split(value)]


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or "run"


def shorten_path(path: Path) -> str:
    resolved = path.absolute()
    for base, prefix in ((REPO_RESOLVED, "repo"), (Path("/home/joe"), "~")):
        try:
            return f"{prefix}/{resolved.relative_to(base).as_posix()}"
        except ValueError:
            pass
    return str(resolved)


def file_url_rel(path: Path) -> str:
    return quote(path.as_posix(), safe="/")


def format_bytes(size: int) -> str:
    units = ("B", "KB", "MB", "GB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def format_mtime(timestamp: float) -> str:
    if not timestamp:
        return ""
    return dt.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


def parse_run_datetime(value: str) -> tuple[float, str] | None:
    matches = list(TIMESTAMP_RE.finditer(value))
    if not matches:
        return None

    match = matches[-1]
    date_part = match.group(1)
    time_part = match.group(2) or ""
    try:
        year = int(date_part[0:4])
        month = int(date_part[4:6])
        day = int(date_part[6:8])
        hour = int(time_part[0:2]) if len(time_part) >= 2 else 0
        minute = int(time_part[2:4]) if len(time_part) >= 4 else 0
        second = int(time_part[4:6]) if len(time_part) >= 6 else 0
        parsed = dt.datetime(year, month, day, hour, minute, second, tzinfo=dt.timezone.utc)
    except ValueError:
        return None

    if time_part:
        label = parsed.strftime("%Y-%m-%d %H:%MZ")
    else:
        label = parsed.strftime("%Y-%m-%d")
    return parsed.timestamp(), label


def run_date_info(run_dir: Path, fallback_mtime: float) -> tuple[float, str, bool]:
    parsed = parse_run_datetime(run_dir.name) or parse_run_datetime(shorten_path(run_dir))
    if parsed:
        timestamp, label = parsed
        return timestamp, label, True
    return fallback_mtime, format_mtime(fallback_mtime), False


def display_caption(path: Path) -> str:
    stem = path.stem
    stem = re.sub(r"^\d+[_ -]+", "", stem)
    stem = re.sub(r"^J\d+_", "", stem)
    stem = stem.replace("_", " ").replace("-", " ")
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem or path.name


def root_label(root: Path) -> str:
    root = root.absolute()
    if root == ARTICLE_ROOT_RESOLVED:
        return "article-assets"
    try:
        return root.relative_to(REPO_RESOLVED).as_posix()
    except ValueError:
        return shorten_path(root)


def should_skip_dir(path: Path, output_dir: Path, include_generated: bool) -> bool:
    if path.name in SKIP_DIR_NAMES:
        return True
    resolved = path.absolute()
    if is_relative_to(resolved, output_dir):
        return True
    if not include_generated:
        for generated_dir in GENERATED_DIRS:
            generated = generated_dir.absolute()
            if is_relative_to(resolved, generated):
                return True
    return False


def iter_image_files(
    roots: list[Path],
    *,
    output_dir: Path,
    include_generated: bool,
    max_images: int,
) -> list[tuple[Path, Path]]:
    images: list[tuple[Path, Path]] = []
    seen: set[Path] = set()

    def add_candidate(root: Path, path: Path) -> bool:
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            return False
        absolute = path.absolute()
        if absolute in seen:
            return False
        seen.add(absolute)
        images.append((root, absolute))
        return bool(max_images and len(images) >= max_images)

    for root in roots:
        root = root.expanduser().absolute()
        if not root.exists():
            continue
        if root.is_file():
            if add_candidate(root.parent, root):
                return images
            continue

        for dirpath, dirnames, filenames in os.walk(root):
            current = Path(dirpath)
            dirnames[:] = [
                dirname
                for dirname in dirnames
                if not should_skip_dir(current / dirname, output_dir, include_generated)
            ]
            for filename in filenames:
                if add_candidate(root, current / filename):
                    return images

    return images


def detect_run_dir(root: Path, path: Path) -> Path:
    rel = os.path.relpath(os.fspath(path), os.fspath(root))
    if rel == os.pardir or rel.startswith(os.pardir + os.sep):
        return path.parent

    parent_parts = rel.split(os.sep)[:-1]
    if not parent_parts:
        return root

    if root == ARTICLE_ROOT_RESOLVED:
        return root / parent_parts[0]

    if "pm99_runner" in parent_parts:
        index = parent_parts.index("pm99_runner")
        if index + 1 < len(parent_parts):
            return root.joinpath(*parent_parts[: index + 2])

    stripped_parts = parent_parts[:]
    while stripped_parts and stripped_parts[-1].lower() in DETAIL_DIR_NAMES:
        stripped_parts.pop()
    if not stripped_parts:
        return root

    timestamp_indexes = [
        index for index, part in enumerate(stripped_parts) if TIMESTAMP_RE.search(part)
    ]
    if timestamp_indexes:
        index = timestamp_indexes[-1]
        return root.joinpath(*stripped_parts[: index + 1])

    return root.joinpath(*stripped_parts)


def build_run_groups(images: list[tuple[Path, Path]], *, stat_images: bool) -> list[RunGroup]:
    groups: dict[Path, RunGroup] = {}
    for root, path in images:
        size_bytes = 0
        mtime = 0.0
        if stat_images:
            try:
                stat = path.stat()
            except OSError:
                continue
            size_bytes = stat.st_size
            mtime = stat.st_mtime
        run_dir = detect_run_dir(root, path).absolute()
        rel = os.path.relpath(os.fspath(path), os.fspath(run_dir))
        rel_to_run = Path(path.name) if rel.startswith(os.pardir + os.sep) else Path(rel)
        group = groups.get(run_dir)
        if group is None:
            group = RunGroup(run_dir=run_dir, root_label=root_label(root))
            groups[run_dir] = group
        group.images.append(
            ImageEntry(
                path=path,
                rel_to_run=rel_to_run,
                caption=display_caption(path),
                size_bytes=size_bytes,
                mtime=mtime,
            )
        )

    for group in groups.values():
        try:
            group.mtime = group.run_dir.stat().st_mtime
        except OSError:
            group.mtime = 0.0
        group.images.sort(key=lambda entry: natural_key(entry.rel_to_run.as_posix()))

    return sorted(
        groups.values(),
        key=lambda group: (-group.newest_mtime, natural_key(shorten_path(group.run_dir))),
    )


def make_run_id(run_dir: Path, used: set[str]) -> str:
    base = slugify(shorten_path(run_dir))
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def serialize_runs(groups: list[RunGroup]) -> list[dict[str, object]]:
    used_ids: set[str] = set()
    runs: list[dict[str, object]] = []
    for group in groups:
        run_id = make_run_id(group.run_dir, used_ids)
        run_url = group.run_dir.as_uri().rstrip("/") + "/"
        run_timestamp, run_date_label, has_run_date = run_date_info(
            group.run_dir,
            group.newest_mtime,
        )
        images = []
        for entry in group.images:
            rel = entry.rel_to_run.as_posix()
            images.append(
                [
                    entry.caption,
                    file_url_rel(entry.rel_to_run),
                    rel,
                    entry.path.name,
                    format_bytes(entry.size_bytes) if entry.size_bytes else "",
                    format_mtime(entry.mtime) if entry.mtime else "",
                ]
            )
        runs.append(
            {
                "id": run_id,
                "title": group.run_dir.name,
                "path": shorten_path(group.run_dir),
                "absPath": str(group.run_dir),
                "root": group.root_label,
                "url": run_url,
                "count": len(group.images),
                "mtime": group.newest_mtime,
                "mtimeLabel": format_mtime(group.newest_mtime),
                "runDate": run_timestamp,
                "runDateLabel": run_date_label,
                "hasRunDate": has_run_date,
                "sizeLabel": format_bytes(group.total_size) if group.total_size else "",
                "images": images,
            }
        )
    return runs


def build_index_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PM99 Artifact Browser</title>
  <style>
    :root {
      --bg: #f6f4ef;
      --ink: #172033;
      --muted: #667085;
      --line: #d8d1c4;
      --panel: #fffefa;
      --panel-alt: #ece7de;
      --accent: #0f766e;
      --accent-ink: #064e45;
      --focus: #2563eb;
      --shadow: 0 10px 32px rgba(23, 32, 51, 0.12);
    }
    * { box-sizing: border-box; }
    html, body { min-height: 100%; }
    body {
      margin: 0;
      color: var(--ink);
      background: var(--bg);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.4;
    }
    button, input, select {
      font: inherit;
    }
    button {
      cursor: pointer;
    }
    a {
      color: var(--accent-ink);
    }
    .topbar {
      position: sticky;
      top: 0;
      z-index: 20;
      display: grid;
      grid-template-columns: minmax(220px, 1fr) minmax(300px, 640px) auto auto auto;
      gap: 12px;
      align-items: center;
      padding: 12px 18px;
      background: rgba(246, 244, 239, 0.96);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(12px);
    }
    .brand {
      display: grid;
      gap: 2px;
      min-width: 0;
    }
    .brand strong {
      font-size: 18px;
      line-height: 1.1;
    }
    .brand span,
    .statline,
    .empty {
      color: var(--muted);
      font-size: 13px;
    }
    .server-status {
      display: none;
      color: var(--accent-ink);
      font-size: 12px;
      font-weight: 700;
      white-space: nowrap;
    }
    body.delete-enabled .server-status {
      display: block;
    }
    body:not(.delete-enabled) .delete-only {
      display: none !important;
    }
    .searchbox {
      width: 100%;
      min-width: 0;
    }
    .searchbox input,
    .topbar select {
      width: 100%;
      height: 38px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      color: var(--ink);
      padding: 0 10px;
    }
    .topbar select {
      min-width: 150px;
    }
    .layout {
      display: grid;
      grid-template-columns: 330px minmax(0, 1fr);
      gap: 18px;
      padding: 18px;
    }
    .sidebar {
      position: sticky;
      top: 74px;
      height: calc(100vh - 92px);
      overflow: auto;
      border-right: 1px solid var(--line);
      padding-right: 12px;
    }
    .run-list {
      display: grid;
      gap: 8px;
    }
    .run-button {
      width: 100%;
      display: grid;
      gap: 5px;
      text-align: left;
      padding: 10px;
      border: 1px solid transparent;
      border-radius: 8px;
      background: transparent;
      color: var(--ink);
    }
    .run-button:hover {
      background: var(--panel-alt);
    }
    .run-button.active {
      border-color: rgba(15, 118, 110, 0.45);
      background: #e3f2ee;
    }
    .run-title {
      overflow-wrap: anywhere;
      font-weight: 650;
      line-height: 1.2;
    }
    .run-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
      color: var(--muted);
      font-size: 12px;
    }
    .run-date {
      display: inline-flex;
      align-items: center;
      max-width: 100%;
      min-height: 20px;
      padding: 1px 7px;
      border: 1px solid rgba(15, 118, 110, 0.28);
      border-radius: 999px;
      background: #dceee9;
      color: var(--accent-ink);
      font-weight: 700;
    }
    .main {
      min-width: 0;
      display: grid;
      gap: 14px;
    }
    .run-head {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 16px;
      align-items: start;
      padding-bottom: 12px;
      border-bottom: 1px solid var(--line);
    }
    .run-head h1 {
      margin: 0 0 5px;
      font-size: clamp(24px, 3vw, 36px);
      line-height: 1.1;
      overflow-wrap: anywhere;
    }
    .run-path {
      color: var(--muted);
      font-size: 13px;
      overflow-wrap: anywhere;
    }
    .run-actions {
      display: flex;
      gap: 8px;
      align-items: center;
      justify-content: end;
    }
    .button {
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      color: var(--ink);
      padding: 7px 10px;
      text-decoration: none;
      white-space: nowrap;
    }
    .button.primary {
      border-color: var(--accent);
      background: var(--accent);
      color: white;
    }
    .button.danger,
    .card-delete {
      border-color: #b42318;
      background: #b42318;
      color: white;
    }
    .gallery {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(178px, 1fr));
      gap: 12px;
    }
    .photo-card {
      position: relative;
      display: grid;
      grid-template-rows: 150px auto;
      margin: 0;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: 0 1px 0 rgba(23, 32, 51, 0.04);
    }
    .photo-button {
      display: grid;
      place-items: center;
      border: 0;
      border-bottom: 1px solid var(--line);
      background: #1f2933;
      padding: 0;
      min-width: 0;
    }
    .photo-button img {
      width: 100%;
      height: 100%;
      object-fit: contain;
      image-rendering: auto;
    }
    .photo-card figcaption {
      display: grid;
      gap: 3px;
      padding: 9px;
      min-width: 0;
    }
    .photo-card strong,
    .photo-card span {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .photo-card strong {
      font-size: 13px;
    }
    .photo-card span {
      color: var(--muted);
      font-size: 12px;
    }
    .card-delete {
      position: absolute;
      top: 6px;
      right: 6px;
      min-height: 26px;
      border: 1px solid #b42318;
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 12px;
      font-weight: 700;
      box-shadow: 0 2px 10px rgba(0, 0, 0, 0.22);
    }
    .more-row {
      display: flex;
      justify-content: center;
      padding: 10px 0 24px;
    }
    .empty {
      padding: 32px 0;
    }
    .lightbox {
      position: fixed;
      inset: 0;
      z-index: 50;
      display: none;
      grid-template-columns: minmax(0, 1fr) 330px;
      background: rgba(12, 17, 24, 0.92);
      color: white;
    }
    .lightbox.open {
      display: grid;
    }
    .lightbox-stage {
      position: relative;
      display: grid;
      place-items: center;
      min-width: 0;
      min-height: 0;
      padding: 18px;
    }
    .lightbox-stage img {
      max-width: 100%;
      max-height: calc(100vh - 36px);
      object-fit: contain;
      background: #111827;
      box-shadow: var(--shadow);
    }
    .lightbox-panel {
      display: grid;
      grid-template-rows: auto 1fr auto;
      gap: 14px;
      min-width: 0;
      padding: 18px;
      background: #f6f4ef;
      color: var(--ink);
      overflow: auto;
    }
    .lightbox-panel h2 {
      margin: 0;
      font-size: 20px;
      line-height: 1.15;
      overflow-wrap: anywhere;
    }
    .lightbox-detail {
      display: grid;
      gap: 9px;
      color: var(--muted);
      font-size: 13px;
    }
    .lightbox-detail code {
      display: block;
      overflow-wrap: anywhere;
      white-space: normal;
      color: var(--ink);
    }
    .lightbox-actions {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }
    .lightbox-actions .wide {
      grid-column: 1 / -1;
    }
    .nav-arrow {
      position: absolute;
      top: 50%;
      transform: translateY(-50%);
      width: 42px;
      height: 42px;
      border-radius: 50%;
      border: 1px solid rgba(255, 255, 255, 0.35);
      background: rgba(255, 255, 255, 0.12);
      color: white;
      font-size: 22px;
    }
    .nav-arrow.prev { left: 18px; }
    .nav-arrow.next { right: 18px; }
    :focus-visible {
      outline: 3px solid var(--focus);
      outline-offset: 2px;
    }
    @media (max-width: 920px) {
      .topbar {
        grid-template-columns: 1fr;
      }
      .layout {
        grid-template-columns: 1fr;
        padding: 12px;
      }
      .sidebar {
        position: static;
        height: auto;
        max-height: 320px;
        border-right: 0;
        border-bottom: 1px solid var(--line);
        padding: 0 0 12px;
      }
      .run-head {
        grid-template-columns: 1fr;
      }
      .run-actions {
        justify-content: start;
        flex-wrap: wrap;
      }
      .lightbox {
        grid-template-columns: 1fr;
        grid-template-rows: minmax(0, 1fr) auto;
      }
      .lightbox-panel {
        max-height: 42vh;
      }
    }
  </style>
</head>
<body>
  <header class="topbar">
    <div class="brand">
      <strong>PM99 Artifact Browser</strong>
      <span id="summaryText">Loading artifact index...</span>
    </div>
    <label class="searchbox">
      <input id="searchInput" type="search" placeholder="Search runs, filenames, paths" autocomplete="off">
    </label>
    <select id="rootFilter" aria-label="Filter by source root"></select>
    <select id="sortSelect" aria-label="Sort runs">
      <option value="date-newest">Run date newest</option>
      <option value="date-oldest">Run date oldest</option>
      <option value="modified-newest">Modified newest</option>
      <option value="name">Name</option>
      <option value="count">Most images</option>
      <option value="root">Source root</option>
    </select>
    <span id="serverStatus" class="server-status">Delete server active</span>
  </header>

  <div class="layout">
    <aside class="sidebar">
      <div id="runList" class="run-list"></div>
    </aside>
    <main class="main">
      <section class="run-head">
        <div>
          <h1 id="runTitle">No run selected</h1>
          <div id="runPath" class="run-path"></div>
          <div id="runStats" class="statline"></div>
        </div>
        <div class="run-actions">
          <a id="openRunLink" class="button" href="#" target="_blank" rel="noreferrer">Open Folder</a>
          <button id="copyRunPath" class="button" type="button">Copy Path</button>
          <button id="deleteRun" class="button danger delete-only" type="button">Delete Run</button>
        </div>
      </section>
      <div id="emptyState" class="empty" hidden>No images match the current filters.</div>
      <section id="gallery" class="gallery" aria-live="polite"></section>
      <div class="more-row">
        <button id="showMore" class="button primary" type="button" hidden>Show More</button>
      </div>
    </main>
  </div>

  <div id="lightbox" class="lightbox" role="dialog" aria-modal="true" aria-label="Image preview">
    <div class="lightbox-stage">
      <button id="prevImage" class="nav-arrow prev" type="button" aria-label="Previous image">‹</button>
      <img id="lightboxImage" alt="">
      <button id="nextImage" class="nav-arrow next" type="button" aria-label="Next image">›</button>
    </div>
    <aside class="lightbox-panel">
      <div>
        <h2 id="lightboxTitle"></h2>
        <div id="lightboxCounter" class="statline"></div>
      </div>
      <div class="lightbox-detail">
        <div><strong>Run</strong><code id="lightboxRun"></code></div>
        <div><strong>Path</strong><code id="lightboxPath"></code></div>
        <div><strong>File</strong><code id="lightboxFile"></code></div>
        <div id="lightboxMeta"></div>
      </div>
      <div class="lightbox-actions">
        <button id="closeLightbox" class="button" type="button">Close</button>
        <button id="copyImagePath" class="button" type="button">Copy Path</button>
        <button id="deleteImage" class="button danger delete-only" type="button">Delete Image</button>
        <a id="openImageLink" class="button primary wide" href="#" target="_blank" rel="noreferrer">Open Original</a>
      </div>
    </aside>
  </div>

  <script src="artifact-data.js"></script>
  <script>
    const DATA = window.ARTIFACT_BROWSER_DATA;
    const batchSize = 300;
    const state = {
      query: "",
      root: "all",
      sort: "date-newest",
      selectedRunId: null,
      visibleLimit: batchSize,
      visibleImages: [],
      lightboxIndex: -1,
      deleteAvailable: false,
      deleteBusy: false,
      statusMessage: ""
    };

    const el = {
      summaryText: document.getElementById("summaryText"),
      searchInput: document.getElementById("searchInput"),
      rootFilter: document.getElementById("rootFilter"),
      sortSelect: document.getElementById("sortSelect"),
      runList: document.getElementById("runList"),
      runTitle: document.getElementById("runTitle"),
      runPath: document.getElementById("runPath"),
      runStats: document.getElementById("runStats"),
      openRunLink: document.getElementById("openRunLink"),
      copyRunPath: document.getElementById("copyRunPath"),
      deleteRun: document.getElementById("deleteRun"),
      serverStatus: document.getElementById("serverStatus"),
      emptyState: document.getElementById("emptyState"),
      gallery: document.getElementById("gallery"),
      showMore: document.getElementById("showMore"),
      lightbox: document.getElementById("lightbox"),
      lightboxImage: document.getElementById("lightboxImage"),
      lightboxTitle: document.getElementById("lightboxTitle"),
      lightboxCounter: document.getElementById("lightboxCounter"),
      lightboxRun: document.getElementById("lightboxRun"),
      lightboxPath: document.getElementById("lightboxPath"),
      lightboxFile: document.getElementById("lightboxFile"),
      lightboxMeta: document.getElementById("lightboxMeta"),
      openImageLink: document.getElementById("openImageLink"),
      copyImagePath: document.getElementById("copyImagePath"),
      deleteImage: document.getElementById("deleteImage"),
      closeLightbox: document.getElementById("closeLightbox"),
      prevImage: document.getElementById("prevImage"),
      nextImage: document.getElementById("nextImage")
    };

    let runs = DATA.runs.map((run) => {
      const images = run.images.map((image, index) => ({
        index,
        caption: image[0],
        urlRel: image[1],
        relPath: image[2],
        fileName: image[3],
        sizeLabel: image[4],
        mtimeLabel: image[5],
        fileSrc: run.url + image[1],
        get src() {
          return state.deleteAvailable
            ? `/api/image?path=${encodeURIComponent(this.absPath)}`
            : this.fileSrc;
        },
        get absPath() { return run.absPath + "/" + this.relPath; }
      }));
      run.images = images;
      run.search = [run.title, run.path, run.root, run.runDateLabel].join(" ").toLowerCase();
      for (const image of run.images) {
        image.search = [image.caption, image.relPath, image.fileName, run.title, run.path, run.root, run.runDateLabel].join(" ").toLowerCase();
      }
      return run;
    });

    function escapeHtml(value) {
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }

    function folderUrl(run) {
      return run.url;
    }

    function copyText(value) {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(value).catch(() => {});
      }
    }

    function setStatus(message) {
      state.statusMessage = message || "";
      el.serverStatus.textContent = state.statusMessage || "Delete server active";
    }

    async function initDeleteApi() {
      if (!["http:", "https:"].includes(window.location.protocol)) {
        return;
      }
      try {
        const response = await fetch("/api/status", { cache: "no-store" });
        if (!response.ok) {
          return;
        }
        const data = await response.json();
        if (!data.deleteEnabled) {
          return;
        }
        state.deleteAvailable = true;
        document.body.classList.add("delete-enabled");
        setStatus("Delete moves to trash");
      } catch (error) {
        state.deleteAvailable = false;
      }
    }

    async function deleteRequest(kind, path) {
      if (!state.deleteAvailable || state.deleteBusy) {
        return null;
      }
      state.deleteBusy = true;
      setStatus("Deleting...");
      try {
        const response = await fetch("/api/delete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kind, path })
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.ok) {
          throw new Error(data.error || `Delete failed (${response.status})`);
        }
        setStatus(`Moved to trash: ${data.trashDisplay || "done"}`);
        return data;
      } catch (error) {
        setStatus(error.message || "Delete failed");
        return null;
      } finally {
        state.deleteBusy = false;
      }
    }

    function updateSummaryCounts() {
      DATA.imageCount = runs.reduce((total, run) => total + run.images.length, 0);
      DATA.runCount = runs.length;
    }

    function removeRunFromState(runId) {
      runs = runs.filter((run) => run.id !== runId);
      if (state.selectedRunId === runId) {
        state.selectedRunId = null;
      }
      updateSummaryCounts();
    }

    function removeImageFromState(absPath) {
      for (const run of runs) {
        const before = run.images.length;
        run.images = run.images.filter((image) => image.absPath !== absPath);
        if (run.images.length !== before) {
          run.count = run.images.length;
          if (!run.images.length) {
            removeRunFromState(run.id);
          } else {
            updateSummaryCounts();
          }
          return;
        }
      }
    }

    async function deleteRun(run) {
      if (!run || !state.deleteAvailable) {
        return;
      }
      const confirmed = window.confirm(`Move this entire run folder to trash?\\n\\n${run.path}\\n\\n${run.count} images`);
      if (!confirmed) {
        return;
      }
      const result = await deleteRequest("run", run.absPath);
      if (!result) {
        return;
      }
      removeRunFromState(run.id);
      el.lightbox.classList.remove("open");
      render();
    }

    async function deleteImageEntry(image) {
      if (!image || !state.deleteAvailable) {
        return;
      }
      const confirmed = window.confirm(`Move this image to trash?\\n\\n${image.absPath}`);
      if (!confirmed) {
        return;
      }
      const result = await deleteRequest("image", image.absPath);
      if (!result) {
        return;
      }
      const lightboxWasOpen = el.lightbox.classList.contains("open");
      removeImageFromState(image.absPath);
      render();
      if (lightboxWasOpen) {
        if (!state.visibleImages.length) {
          el.lightbox.classList.remove("open");
        } else {
          state.lightboxIndex = Math.min(state.lightboxIndex, state.visibleImages.length - 1);
          renderLightbox();
        }
      }
    }

    function runMatches(run) {
      if (state.root !== "all" && run.root !== state.root) {
        return false;
      }
      if (!state.query) {
        return true;
      }
      return run.search.includes(state.query) || run.images.some((image) => image.search.includes(state.query));
    }

    function filteredRuns() {
      const list = runs.filter(runMatches);
      if (state.sort === "name") {
        list.sort((a, b) => a.title.localeCompare(b.title));
      } else if (state.sort === "count") {
        list.sort((a, b) => b.count - a.count || a.title.localeCompare(b.title));
      } else if (state.sort === "root") {
        list.sort((a, b) => a.root.localeCompare(b.root) || a.title.localeCompare(b.title));
      } else if (state.sort === "date-oldest") {
        list.sort((a, b) => {
          const dated = Number(b.hasRunDate) - Number(a.hasRunDate);
          return dated || a.runDate - b.runDate || a.title.localeCompare(b.title);
        });
      } else if (state.sort === "modified-newest") {
        list.sort((a, b) => b.mtime - a.mtime || a.title.localeCompare(b.title));
      } else {
        list.sort((a, b) => {
          const dated = Number(b.hasRunDate) - Number(a.hasRunDate);
          return dated || b.runDate - a.runDate || a.title.localeCompare(b.title);
        });
      }
      return list;
    }

    function imagesForRun(run) {
      if (!state.query) {
        return run.images;
      }
      return run.images.filter((image) => image.search.includes(state.query) || run.search.includes(state.query));
    }

    function ensureSelection(list) {
      if (!list.length) {
        state.selectedRunId = null;
        return;
      }
      if (!state.selectedRunId || !list.some((run) => run.id === state.selectedRunId)) {
        state.selectedRunId = list[0].id;
        state.visibleLimit = batchSize;
      }
    }

    function renderRootFilter() {
      const roots = Array.from(new Set(runs.map((run) => run.root))).sort();
      el.rootFilter.innerHTML = [
        '<option value="all">All roots</option>',
        ...roots.map((root) => `<option value="${escapeHtml(root)}">${escapeHtml(root)}</option>`)
      ].join("");
    }

    function renderRunList(list) {
      el.runList.innerHTML = list.map((run) => {
        const active = run.id === state.selectedRunId ? " active" : "";
        const matching = state.query ? imagesForRun(run).length : run.count;
        return `
          <button class="run-button${active}" type="button" data-run-id="${escapeHtml(run.id)}">
            <span class="run-title">${escapeHtml(run.title)}</span>
            <span class="run-meta">
              <span class="run-date">${escapeHtml(run.hasRunDate ? run.runDateLabel : `Modified ${run.runDateLabel}`)}</span>
              <span>${matching} / ${run.count} images</span>
              <span>${escapeHtml(run.root)}</span>
            </span>
          </button>
        `;
      }).join("");
    }

    function renderSelectedRun(list) {
      const run = list.find((item) => item.id === state.selectedRunId);
      if (!run) {
        el.runTitle.textContent = "No run selected";
        el.runPath.textContent = "";
        el.runStats.textContent = "";
        el.openRunLink.href = "#";
        el.deleteRun.disabled = true;
        el.gallery.innerHTML = "";
        el.emptyState.hidden = false;
        el.showMore.hidden = true;
        state.visibleImages = [];
        return;
      }

      const images = imagesForRun(run);
      state.visibleImages = images;
      const shown = images.slice(0, state.visibleLimit);

      el.runTitle.textContent = run.title;
      el.runPath.textContent = run.path;
      el.runStats.textContent = [
        run.hasRunDate ? `run date ${run.runDateLabel}` : `modified ${run.runDateLabel}`,
        `${images.length} visible images`,
        `${run.count} total`,
        run.sizeLabel,
        run.hasRunDate ? `modified ${run.mtimeLabel}` : ""
      ].filter(Boolean).join(" · ");
      el.openRunLink.href = folderUrl(run);
      el.copyRunPath.onclick = () => copyText(run.absPath);
      el.deleteRun.disabled = !state.deleteAvailable;
      el.deleteRun.onclick = () => deleteRun(run);
      el.emptyState.hidden = images.length !== 0;

      el.gallery.innerHTML = shown.map((image, visibleIndex) => `
        <figure class="photo-card">
          <button class="card-delete delete-only" type="button" data-delete-image-index="${visibleIndex}" title="Delete image">Delete</button>
          <button class="photo-button" type="button" data-visible-index="${visibleIndex}" title="${escapeHtml(image.relPath)}">
            <img loading="lazy" decoding="async" src="${escapeHtml(image.src)}" alt="${escapeHtml(image.caption)}">
          </button>
          <figcaption>
            <strong title="${escapeHtml(image.caption)}">${escapeHtml(image.caption)}</strong>
            <span title="${escapeHtml(image.relPath)}">${escapeHtml(image.relPath)}</span>
          </figcaption>
        </figure>
      `).join("");

      if (images.length > state.visibleLimit) {
        el.showMore.hidden = false;
        el.showMore.textContent = `Show More (${state.visibleLimit} of ${images.length})`;
      } else {
        el.showMore.hidden = true;
      }
    }

    function render() {
      const list = filteredRuns();
      ensureSelection(list);
      el.summaryText.textContent = `${DATA.imageCount} images · ${DATA.runCount} runs · generated ${DATA.generatedAt}`;
      renderRunList(list);
      renderSelectedRun(list);
    }

    function selectedRun() {
      return runs.find((run) => run.id === state.selectedRunId) || null;
    }

    function openLightbox(index) {
      if (index < 0 || index >= state.visibleImages.length) {
        return;
      }
      state.lightboxIndex = index;
      renderLightbox();
      el.lightbox.classList.add("open");
    }

    function renderLightbox() {
      const run = selectedRun();
      const image = state.visibleImages[state.lightboxIndex];
      if (!run || !image) {
        return;
      }
      el.lightboxImage.src = image.src;
      el.lightboxImage.alt = image.caption;
      el.lightboxTitle.textContent = image.caption;
      el.lightboxCounter.textContent = `${state.lightboxIndex + 1} of ${state.visibleImages.length}`;
      el.lightboxRun.textContent = run.path;
      el.lightboxPath.textContent = image.absPath;
      el.lightboxFile.textContent = image.fileName;
      el.lightboxMeta.textContent = [image.sizeLabel, image.mtimeLabel].filter(Boolean).join(" · ");
      el.openImageLink.href = image.src;
      el.copyImagePath.onclick = () => copyText(image.absPath);
      el.deleteImage.disabled = !state.deleteAvailable;
      el.deleteImage.onclick = () => deleteImageEntry(image);
    }

    function moveLightbox(delta) {
      if (!el.lightbox.classList.contains("open")) {
        return;
      }
      const count = state.visibleImages.length;
      if (!count) {
        return;
      }
      state.lightboxIndex = (state.lightboxIndex + delta + count) % count;
      renderLightbox();
    }

    renderRootFilter();
    render();
    initDeleteApi().finally(render);

    el.searchInput.addEventListener("input", (event) => {
      state.query = event.target.value.trim().toLowerCase();
      state.visibleLimit = batchSize;
      render();
    });
    el.rootFilter.addEventListener("change", (event) => {
      state.root = event.target.value;
      state.visibleLimit = batchSize;
      render();
    });
    el.sortSelect.addEventListener("change", (event) => {
      state.sort = event.target.value;
      render();
    });
    el.runList.addEventListener("click", (event) => {
      const button = event.target.closest(".run-button");
      if (!button) {
        return;
      }
      state.selectedRunId = button.dataset.runId;
      state.visibleLimit = batchSize;
      render();
    });
    el.gallery.addEventListener("click", (event) => {
      const deleteButton = event.target.closest(".card-delete");
      if (deleteButton) {
        const index = Number(deleteButton.dataset.deleteImageIndex);
        deleteImageEntry(state.visibleImages[index]);
        return;
      }
      const button = event.target.closest(".photo-button");
      if (!button) {
        return;
      }
      openLightbox(Number(button.dataset.visibleIndex));
    });
    el.showMore.addEventListener("click", () => {
      state.visibleLimit += batchSize;
      render();
    });
    el.closeLightbox.addEventListener("click", () => el.lightbox.classList.remove("open"));
    el.lightbox.addEventListener("click", (event) => {
      if (event.target === el.lightbox) {
        el.lightbox.classList.remove("open");
      }
    });
    el.prevImage.addEventListener("click", () => moveLightbox(-1));
    el.nextImage.addEventListener("click", () => moveLightbox(1));
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        el.lightbox.classList.remove("open");
      } else if (event.key === "ArrowLeft") {
        moveLightbox(-1);
      } else if (event.key === "ArrowRight") {
        moveLightbox(1);
      }
    });
  </script>
</body>
</html>
"""


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    roots = [] if args.no_default_roots else default_roots()
    roots.extend(Path(root) for root in args.root)

    images = iter_image_files(
        roots,
        output_dir=output_dir,
        include_generated=args.include_generated,
        max_images=args.max_images,
    )
    groups = build_run_groups(images, stat_images=args.stat_images)
    runs = serialize_runs(groups)

    data = {
        "generatedAt": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "imageCount": sum(run["count"] for run in runs),
        "runCount": len(runs),
        "roots": [root_label(root.expanduser().resolve()) for root in roots if root.expanduser().exists()],
        "runs": runs,
    }

    data_js = "window.ARTIFACT_BROWSER_DATA = "
    data_js += json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    data_js += ";\n"
    (output_dir / "artifact-data.js").write_text(data_js, encoding="utf-8")
    (output_dir / "index.html").write_text(build_index_html(), encoding="utf-8")

    print(f"Wrote {data['imageCount']} images across {data['runCount']} runs")
    print(output_dir / "index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
