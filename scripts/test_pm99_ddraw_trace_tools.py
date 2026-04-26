from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SUMMARIZER_PATH = REPO_ROOT / "scripts" / "summarize_pm99_ddraw_trace.py"
PATCHER_PATH = REPO_ROOT / "scripts" / "patch_pm99_transferable_compat.py"


def load_summarizer():
    spec = importlib.util.spec_from_file_location("summarize_pm99_ddraw_trace", SUMMARIZER_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_summarizer_identifies_first_failed_hresult(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifact"
    artifact_dir.mkdir()
    (artifact_dir / "pm99-ddraw.log").write_text(
        "\n".join(
            [
                "[1][tid=9] DirectDrawCreate real hr=0x00000000 ok real=0x1",
                "[2][tid=9] IDirectDraw::SetCooperativeLevel hwnd=0x2 flags=0x13 hr=0x00000000 ok",
                "[3][tid=9] IDirectDraw::SetDisplayMode width=640 height=480 bpp=16 hr=0x88760078 fail",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summarizer = load_summarizer()
    events = summarizer.find_trace_lines((artifact_dir / "pm99-ddraw.log").read_text(encoding="utf-8"))
    summary = summarizer.classify_trace(events)

    assert summary["last_success"]["call"] == "IDirectDraw::SetCooperativeLevel hwnd=0x2 flags=0x13"
    assert summary["first_failure"]["call"] == "IDirectDraw::SetDisplayMode width=640 height=480 bpp=16"
    assert summary["first_failure"]["hresult"] == "0x88760078"


def test_summarizer_flags_huge_surface_dimensions(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifact"
    artifact_dir.mkdir()
    (artifact_dir / "pm99-ddraw.log").write_text(
        "[1][tid=9] IDirectDraw4::CreateSurface input size=124 flags=0x00001007 "
        "width=4294967252 height=4294967252 pitch=0 backbuffers=0 caps=0x00002840 "
        "caps2=0x00000000 pixelflags=0x00000040 rgbbits=16\n",
        encoding="utf-8",
    )

    summarizer = load_summarizer()
    events = summarizer.find_trace_lines((artifact_dir / "pm99-ddraw.log").read_text(encoding="utf-8"))
    summary = summarizer.classify_trace(events)

    assert summary["first_anomaly"]["anomaly"] == "huge_surface_dimension"
    assert summary["first_anomaly"]["surface_width"] == 4294967252


def test_summarizer_extracts_modal_text_from_runner_summary(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifact"
    artifact_dir.mkdir()
    (artifact_dir / "pm99-ddraw.log").write_text("", encoding="utf-8")
    (artifact_dir / "summary.json").write_text(
        json.dumps(
            {
                "final_screen_classification": {
                    "probes": [
                        {
                            "raw_text": (
                                "MANAGPRE\nApplication cannot start.\n"
                                "Please try again or reinstall\nOK\n"
                            )
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    output_path = tmp_path / "summary.json"
    result = subprocess.run(
        ["python3", str(SUMMARIZER_PATH), str(artifact_dir), "--output", str(output_path)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["modal_text"] == ["Application cannot start."]


def test_summarizer_writes_json_output(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifact"
    artifact_dir.mkdir()
    (artifact_dir / "pm99-ddraw.log").write_text(
        "[1][tid=9] DirectDrawEnumerateA hr=0x00000000 ok\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "summary.json"

    result = subprocess.run(
        ["python3", str(SUMMARIZER_PATH), str(artifact_dir), "--output", str(output_path)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["trace_log_present"] is True
    assert payload["trace"]["last_success"]["hresult"] == "0x00000000"


def test_transferable_compat_requires_explicit_patch_set(tmp_path: Path) -> None:
    fake_exe = tmp_path / "MANAGPRE.EXE"
    fake_exe.write_bytes(b"not a real pe")

    result = subprocess.run(
        ["python3", str(PATCHER_PATH), str(fake_exe), "--dry-run"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "no patches selected" in result.stderr


def test_transferable_compat_windowed_write_requires_ack(tmp_path: Path) -> None:
    fake_exe = tmp_path / "MANAGPRE.EXE"
    fake_exe.write_bytes(b"not a real pe")

    result = subprocess.run(
        ["python3", str(PATCHER_PATH), str(fake_exe), "--patch-set", "windowed"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "windowed patch set is a rejected experiment" in result.stderr
