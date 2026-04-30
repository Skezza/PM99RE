#!/usr/bin/env python3
"""Fetch redistributable emulator payloads for local browser experiments.

This intentionally does not fetch Windows disk images or PM99 binaries.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "pm99-browser-research"
V86_BIOS_BASE = "https://raw.githubusercontent.com/copy/v86/master/bios/"
BOXEDWINE_RELEASE_API = "https://api.github.com/repos/danoon2/Boxedwine/releases/latest"


def download(url: str, output: Path, *, quiet: bool = False) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=120) as response, output.open("wb") as fh:
        total = int(response.headers.get("content-length") or 0)
        done = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if total and not quiet:
                print(f"download {output.name}: {done}/{total}", flush=True)


def copy_v86_runtime() -> list[str]:
    source = ROOT / "node_modules" / "v86"
    if not source.exists():
        raise FileNotFoundError(
            "node_modules/v86 is missing. Run `npm install` in tools/pm99-in-a-browser first."
        )

    copied: list[str] = []
    destinations = (
        ROOT / "vendor" / "v86",
        ROOT / "v86" / "vendor",
    )
    for out in destinations:
        out.mkdir(parents=True, exist_ok=True)
        for src_rel, dst_name in (
            ("build/libv86.js", "libv86.js"),
            ("build/v86.wasm", "v86.wasm"),
            ("LICENSE", "LICENSE.v86"),
            ("Readme.md", "README.v86.md"),
        ):
            dst = out / dst_name
            shutil.copy2(source / src_rel, dst)
            copied.append(str(dst.relative_to(ROOT)))
    return copied


def fetch_v86_bios() -> list[str]:
    out = ROOT / "v86" / "assets" / "bios"
    fetched: list[str] = []
    for name in ("seabios.bin", "vgabios.bin"):
        dst = out / name
        download(V86_BIOS_BASE + name, dst, quiet=True)
        fetched.append(str(dst.relative_to(ROOT)))
    return fetched


def latest_boxedwine_web_asset() -> tuple[str, str]:
    request = Request(BOXEDWINE_RELEASE_API, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:
        data = json.load(response)
    for asset in data.get("assets", []):
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if "web" in name.lower() and name.lower().endswith(".zip") and url:
            return name, url
    raise RuntimeError("Could not find a BoxedWine Web zip in the latest GitHub release")


def fetch_boxedwine() -> list[str]:
    name, url = latest_boxedwine_web_asset()
    cache = ROOT / "vendor" / "boxedwine" / name
    if not cache.exists() or cache.stat().st_size < 1_000_000:
        download(url, cache)

    extracted = ROOT / "vendor" / "boxedwine" / cache.stem
    if extracted.exists():
        shutil.rmtree(extracted)
    with zipfile.ZipFile(cache) as zf:
        zf.extractall(extracted)

    # Use the single-threaded build by default so Python's simple HTTP server
    # can launch it without cross-origin isolation headers.
    source = extracted / "SingleThreaded"
    if not source.exists():
        raise FileNotFoundError(f"BoxedWine release did not contain {source.relative_to(ROOT)}")

    vendor_out = ROOT / "boxedwine" / "vendor"
    rootfs_out = ROOT / "boxedwine" / "assets" / "rootfs"
    vendor_out.mkdir(parents=True, exist_ok=True)
    rootfs_out.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    for filename in (
        "boxedwine.html",
        "boxedwine.js",
        "boxedwine.wasm",
        "boxedwine-shell.js",
        "boxedwine.css",
    ):
        dst = vendor_out / filename
        shutil.copy2(source / filename, dst)
        copied.append(str(dst.relative_to(ROOT)))

    root_dst = rootfs_out / "boxedwine-root.zip"
    shutil.copy2(source / "boxedwine.zip", root_dst)
    copied.append(str(root_dst.relative_to(ROOT)))

    vendor_root_dst = vendor_out / "boxedwine-root.zip"
    shutil.copy2(source / "boxedwine.zip", vendor_root_dst)
    copied.append(str(vendor_root_dst.relative_to(ROOT)))

    app_zip = ROOT / "boxedwine" / "assets" / "apps" / "pm99-app.zip"
    vendor_app = vendor_out / "pm99-app.zip"
    if app_zip.exists() or app_zip.is_symlink():
        if vendor_app.exists() or vendor_app.is_symlink():
            vendor_app.unlink()
        vendor_app.symlink_to(Path("../assets/apps/pm99-app.zip"))
        copied.append(str(vendor_app.relative_to(ROOT)))

    readme = extracted / "readme.txt"
    if readme.exists():
        dst = vendor_out / f"README.{cache.stem}.txt"
        shutil.copy2(readme, dst)
        copied.append(str(dst.relative_to(ROOT)))

    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-v86", action="store_true", help="do not copy/fetch v86 runtime assets")
    parser.add_argument("--skip-boxedwine", action="store_true", help="do not download/extract BoxedWine Web")
    args = parser.parse_args()

    paths: list[str] = []
    if not args.skip_v86:
        paths.extend(copy_v86_runtime())
        paths.extend(fetch_v86_bios())
    if not args.skip_boxedwine:
        paths.extend(fetch_boxedwine())

    for rel in paths:
        print(rel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
