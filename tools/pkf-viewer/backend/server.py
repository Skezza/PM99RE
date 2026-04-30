"""Local API for the standalone SIMULDAT PKF viewer."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, replace
import os
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from .pkf_parser import PkfFile, palette_colors, parse_pkf_file, record_payload_bytes


def annotate_duplicate_payloads(files: list[PkfFile]) -> list[PkfFile]:
    counts: Counter[str] = Counter()
    for file in files:
        for table in file.tables:
            for record in table.records:
                counts[record.payload.sha256_16] += 1

    annotated: list[PkfFile] = []
    for file in files:
        tables = []
        for table in file.tables:
            records = []
            for record in table.records:
                duplicate_count = counts[record.payload.sha256_16]
                payload = replace(
                    record.payload,
                    duplicate_payload_count=duplicate_count if duplicate_count > 1 else None,
                )
                records.append(replace(record, payload=payload))
            tables.append(replace(table, records=records))
        annotated.append(replace(file, tables=tables))
    return annotated


def default_simuldat_root() -> Path:
    env_root = os.environ.get("PM99_SIMULDAT_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[3]
    return (repo_root / ".local" / "iso" / "Simuldat").resolve()


class PkfRepository:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = Lock()
        self._files: list[PkfFile] = []
        self._paths: list[Path] = []
        self._loaded = False
        self._last_error: str | None = None

    def refresh(self) -> None:
        with self._lock:
            self._files = []
            self._paths = []
            self._last_error = None
            if not self.root.exists():
                self._loaded = True
                self._last_error = f"SIMULDAT root not found: {self.root}"
                return
            paths = sorted(path for path in self.root.rglob("*") if path.is_file() and path.suffix.lower() == ".pkf")
            for path in paths:
                self._files.append(parse_pkf_file(path, root=self.root))
                self._paths.append(path)
            self._files = annotate_duplicate_payloads(self._files)
            self._loaded = True

    def ensure_loaded(self) -> None:
        if not self._loaded:
            self.refresh()

    def summary(self) -> dict[str, object]:
        self.ensure_loaded()
        payload_kind_counts: dict[str, int] = {}
        p3d_family_counts: dict[str, int] = {}
        for file in self._files:
            for kind, count in file.payload_kind_counts.items():
                payload_kind_counts[kind] = payload_kind_counts.get(kind, 0) + count
            for family, count in file.p3d_family_counts.items():
                p3d_family_counts[family] = p3d_family_counts.get(family, 0) + count
        return {
            "root": str(self.root),
            "exists": self.root.exists(),
            "error": self._last_error,
            "pkf_count": len(self._files),
            "total_bytes": sum(file.size for file in self._files),
            "table_count": sum(file.selected_table_count for file in self._files),
            "entry_count": sum(file.selected_entry_count for file in self._files),
            "payload_kind_counts": dict(sorted(payload_kind_counts.items())),
            "p3d_family_counts": dict(sorted(p3d_family_counts.items())),
        }

    def list_files(self) -> list[dict[str, object]]:
        self.ensure_loaded()
        return [
            {
                "id": index,
                "relative_path": file.relative_path,
                "size": file.size,
                "size_hex": file.size_hex,
                "selected_table_count": file.selected_table_count,
                "selected_entry_count": file.selected_entry_count,
                "indexed_payload_coverage_ratio": file.indexed_payload_coverage_ratio,
                "payload_kind_counts": file.payload_kind_counts,
                "bmp_dimension_counts": file.bmp_dimension_counts,
                "p3d_family_counts": file.p3d_family_counts,
            }
            for index, file in enumerate(self._files)
        ]

    def get_file(self, pkf_id: int) -> PkfFile:
        self.ensure_loaded()
        if pkf_id < 0 or pkf_id >= len(self._files):
            raise HTTPException(status_code=404, detail="Unknown PKF id")
        return self._files[pkf_id]

    def get_path(self, pkf_id: int) -> Path:
        self.ensure_loaded()
        if pkf_id < 0 or pkf_id >= len(self._paths):
            raise HTTPException(status_code=404, detail="Unknown PKF id")
        return self._paths[pkf_id]


repository = PkfRepository(default_simuldat_root())
app = FastAPI(title="PM99 SIMULDAT PKF Viewer", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def record_for(file: PkfFile, table_index: int, slot_index: int):
    if table_index < 0 or table_index >= len(file.tables):
        raise HTTPException(status_code=404, detail="Unknown table")
    table = file.tables[table_index]
    if slot_index < 0 or slot_index >= len(table.records):
        raise HTTPException(status_code=404, detail="Unknown record")
    return table.records[slot_index]


@app.get("/api/summary")
def get_summary() -> dict[str, object]:
    return repository.summary()


@app.post("/api/refresh")
def refresh() -> dict[str, object]:
    repository.refresh()
    return repository.summary()


@app.get("/api/pkfs")
def list_pkfs() -> list[dict[str, object]]:
    return repository.list_files()


@app.get("/api/pkfs/{pkf_id}")
def get_pkf(pkf_id: int) -> dict[str, object]:
    payload = asdict(repository.get_file(pkf_id))
    payload.pop("path", None)
    return payload


@app.get("/api/pkfs/{pkf_id}/records/{table_index}/{slot_index}/preview")
def preview_record(pkf_id: int, table_index: int, slot_index: int) -> Response:
    file = repository.get_file(pkf_id)
    record = record_for(file, table_index, slot_index)
    if record.payload.kind == "BMP":
        media_type = "image/bmp"
    elif record.payload.kind == "GIF":
        media_type = "image/gif"
    else:
        raise HTTPException(status_code=404, detail="Record is not a previewable image")
    content = record_payload_bytes(repository.get_path(pkf_id), record)
    return Response(content=content, media_type=media_type)


@app.get("/api/pkfs/{pkf_id}/records/{table_index}/{slot_index}/palette")
def get_palette(pkf_id: int, table_index: int, slot_index: int) -> dict[str, object]:
    file = repository.get_file(pkf_id)
    record = record_for(file, table_index, slot_index)
    if record.payload.kind != "RIFF/PAL":
        raise HTTPException(status_code=404, detail="Record is not a RIFF/PAL palette")
    payload = record_payload_bytes(repository.get_path(pkf_id), record)
    return {"colors": palette_colors(payload)}
