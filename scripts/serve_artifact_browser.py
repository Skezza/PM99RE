#!/usr/bin/env python3
"""Serve the local PM99 artifact browser with a recoverable delete API."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import mimetypes
import os
import shutil
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socket import socket
from typing import Any
from urllib.parse import parse_qs, urlparse


REPO = Path(__file__).resolve().parents[1]
DEFAULT_BROWSER_DIR = REPO / "work" / "artifact_browser"
DEFAULT_TRASH_DIR = REPO / "work" / "artifact_browser_trash"
DATA_PREFIX = "window.ARTIFACT_BROWSER_DATA = "


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Serve work/artifact_browser with a local delete-to-trash API."
    )
    parser.add_argument(
        "--browser-dir",
        default=str(DEFAULT_BROWSER_DIR),
        help="Directory containing index.html and artifact-data.js.",
    )
    parser.add_argument(
        "--trash-dir",
        default=str(DEFAULT_TRASH_DIR),
        help="Directory where deleted images/runs are moved.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host.")
    parser.add_argument("--port", type=int, default=8765, help="Preferred port.")
    return parser.parse_args()


def find_port(host: str, preferred: int) -> int:
    for port in range(preferred, preferred + 100):
        with socket() as probe:
            try:
                probe.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"No free port found from {preferred} to {preferred + 99}")


def load_browser_data(data_path: Path) -> dict[str, Any]:
    text = data_path.read_text(encoding="utf-8").strip()
    if not text.startswith(DATA_PREFIX):
        raise ValueError(f"Unexpected data format in {data_path}")
    payload = text[len(DATA_PREFIX) :]
    if payload.endswith(";"):
        payload = payload[:-1]
    return json.loads(payload)


def write_browser_data(data_path: Path, data: dict[str, Any]) -> None:
    data["imageCount"] = sum(int(run.get("count", 0)) for run in data.get("runs", []))
    data["runCount"] = len(data.get("runs", []))
    text = DATA_PREFIX + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n"
    data_path.write_text(text, encoding="utf-8")


def normalized(path: str | Path) -> Path:
    return Path(path).expanduser().absolute()


def display_path(path: Path) -> str:
    try:
        return f"repo/{path.relative_to(REPO).as_posix()}"
    except ValueError:
        try:
            return f"~/{path.relative_to(Path.home()).as_posix()}"
        except ValueError:
            return str(path)


def safe_relative(path: Path) -> Path:
    for base in (REPO, Path.home()):
        try:
            return path.relative_to(base)
        except ValueError:
            pass
    parts = [part for part in path.parts if part not in (path.anchor, os.sep)]
    return Path(*parts)


def unique_target(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    for index in range(2, 1000):
        candidate = parent / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not allocate unique trash path for {path}")


class ArtifactIndex:
    def __init__(self, browser_dir: Path, trash_dir: Path) -> None:
        self.browser_dir = browser_dir.absolute()
        self.data_path = self.browser_dir / "artifact-data.js"
        self.trash_dir = trash_dir.absolute()
        self.data = load_browser_data(self.data_path)
        self.trash_dir.mkdir(parents=True, exist_ok=True)

    def reload(self) -> None:
        self.data = load_browser_data(self.data_path)

    def save(self) -> None:
        write_browser_data(self.data_path, self.data)

    def find_run(self, path: Path) -> dict[str, Any] | None:
        target = str(path)
        for run in self.data.get("runs", []):
            if str(normalized(run.get("absPath", ""))) == target:
                return run
        return None

    def find_image(self, path: Path) -> tuple[dict[str, Any], list[Any]] | None:
        target = str(path)
        for run in self.data.get("runs", []):
            run_dir = normalized(run.get("absPath", ""))
            for image in run.get("images", []):
                image_path = run_dir / image[2]
                if str(image_path.absolute()) == target:
                    return run, image
        return None

    def move_to_trash(self, path: Path) -> Path | None:
        if path in (REPO, Path.home(), self.browser_dir, self.trash_dir):
            raise ValueError(f"Refusing to move unsafe path: {path}")
        if not path.exists():
            return None

        timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = unique_target(self.trash_dir / timestamp / safe_relative(path))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
        return target

    def delete_run(self, path: Path) -> dict[str, Any]:
        run = self.find_run(path)
        if run is None:
            raise FileNotFoundError("Run is not in the current artifact index")

        moved_to = self.move_to_trash(path)
        self.data["runs"] = [
            item for item in self.data.get("runs", []) if item.get("id") != run.get("id")
        ]
        self.save()
        return {
            "kind": "run",
            "removedImages": int(run.get("count", 0)),
            "trashDisplay": display_path(moved_to) if moved_to else "already missing",
        }

    def delete_image(self, path: Path) -> dict[str, Any]:
        found = self.find_image(path)
        if found is None:
            raise FileNotFoundError("Image is not in the current artifact index")

        run, image = found
        moved_to = self.move_to_trash(path)
        run["images"] = [item for item in run.get("images", []) if item is not image]
        run["count"] = len(run["images"])
        if run["count"] == 0:
            self.data["runs"] = [
                item for item in self.data.get("runs", []) if item.get("id") != run.get("id")
            ]
        self.save()
        return {
            "kind": "image",
            "removedImages": 1,
            "trashDisplay": display_path(moved_to) if moved_to else "already missing",
        }

    def delete(self, kind: str, path_value: str) -> dict[str, Any]:
        path = normalized(path_value)
        self.reload()
        if kind == "run":
            return self.delete_run(path)
        if kind == "image":
            return self.delete_image(path)
        raise ValueError(f"Unsupported delete kind: {kind}")


def make_handler(index: ArtifactIndex, browser_dir: Path) -> type[SimpleHTTPRequestHandler]:
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(browser_dir), **kwargs)

        def log_message(self, format: str, *args: Any) -> None:
            print(f"{self.address_string()} - {format % args}")

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_indexed_image(self, path_value: str) -> None:
            path = normalized(path_value)
            index.reload()
            if index.find_image(path) is None:
                self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Image is not in the current artifact index"})
                return
            if not path.is_file():
                self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Image file is missing"})
                return

            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(path.stat().st_size))
            self.end_headers()
            with path.open("rb") as source:
                shutil.copyfileobj(source, self.wfile)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/status":
                self.send_json(
                    HTTPStatus.OK,
                    {
                        "deleteEnabled": True,
                        "trashDir": str(index.trash_dir),
                        "trashDisplay": display_path(index.trash_dir),
                    },
                )
                return
            if parsed.path == "/api/image":
                query = parse_qs(parsed.query)
                self.send_indexed_image(query.get("path", [""])[0])
                return
            super().do_GET()

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/api/delete":
                self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Unknown endpoint"})
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 65536:
                    raise ValueError("Request body is too large")
                body = self.rfile.read(length)
                payload = json.loads(body.decode("utf-8"))
                result = index.delete(str(payload.get("kind", "")), str(payload.get("path", "")))
                self.send_json(HTTPStatus.OK, {"ok": True, **result})
            except FileNotFoundError as error:
                self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": str(error)})
            except Exception as error:
                self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(error)})

    return Handler


def main() -> int:
    args = parse_args()
    browser_dir = Path(args.browser_dir).expanduser().absolute()
    trash_dir = Path(args.trash_dir).expanduser().absolute()
    if not (browser_dir / "index.html").exists():
        raise SystemExit(f"Browser index not found: {browser_dir / 'index.html'}")
    if not (browser_dir / "artifact-data.js").exists():
        raise SystemExit(f"Browser data not found: {browser_dir / 'artifact-data.js'}")

    port = find_port(args.host, args.port)
    index = ArtifactIndex(browser_dir, trash_dir)
    handler = make_handler(index, browser_dir)
    server = ThreadingHTTPServer((args.host, port), handler)
    print(f"Serving artifact browser at http://{args.host}:{port}/")
    print(f"Delete trash: {trash_dir}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
