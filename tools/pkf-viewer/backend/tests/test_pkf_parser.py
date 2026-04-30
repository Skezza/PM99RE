from __future__ import annotations

from pathlib import Path
import struct

from backend.pkf_parser import FIELD_OFFSET, FIELD_STRIDE, palette_colors, parse_pkf_file


def bmp_payload(width: int = 2, height: int = 2) -> bytes:
    palette = bytes([0, 0, 0, 0]) * 256
    pixels = bytes([0, 1, 2, 3])
    size = 14 + 40 + len(palette) + len(pixels)
    header = bytearray()
    header += b"BM"
    header += struct.pack("<I", size)
    header += b"\x00\x00\x00\x00"
    header += struct.pack("<I", 14 + 40 + len(palette))
    header += struct.pack("<IiiHHIIiiII", 40, width, height, 1, 8, 0, len(pixels), 0, 0, 256, 256)
    return bytes(header) + palette + pixels


def os2_bmp_payload(width: int = 3, height: int = 2) -> bytes:
    pixels = bytes([0, 1, 2, 0]) * height
    size = 14 + 12 + len(pixels)
    header = bytearray()
    header += b"BM"
    header += struct.pack("<I", size)
    header += b"\x00\x00\x00\x00"
    header += struct.pack("<I", 14 + 12)
    header += struct.pack("<IHHHH", 12, width, height, 1, 8)
    return bytes(header) + pixels


def gif_payload() -> bytes:
    return b"GIF89a" + struct.pack("<HH", 3, 4) + b"\x00\x00\x00;"


def pal_payload() -> bytes:
    colors = bytes([255, 0, 0, 0, 0, 255, 0, 0])
    data = struct.pack("<HH", 0x0300, 2) + colors
    return b"RIFF" + struct.pack("<I", 4 + 8 + len(data)) + b"PAL " + b"data" + struct.pack("<I", len(data)) + data


def p3d_payload() -> bytes:
    return b"\xfe\xff\x7f\xffBox0\x00" + struct.pack("<fff", 1.0, 2.0, 3.0)


def synthetic_pkf(path: Path) -> None:
    payloads = [bmp_payload(), gif_payload(), pal_payload(), p3d_payload()]
    first_payload = 0x5B2
    data = bytearray(first_payload)
    cursor = first_payload
    for index, payload in enumerate(payloads):
        field = FIELD_OFFSET + index * FIELD_STRIDE
        struct.pack_into("<III", data, field, cursor, len(payload), 1)
        descriptor = bytes([index + 1]) * 0x1A
        data[field + 12 : field + 12 + len(descriptor)] = descriptor
        data.extend(payload)
        cursor += len(payload)
    path.write_bytes(bytes(data))


def test_parse_synthetic_pkf(tmp_path: Path) -> None:
    pkf_path = tmp_path / "Sample.pkf"
    synthetic_pkf(pkf_path)

    parsed = parse_pkf_file(pkf_path, root=tmp_path)

    assert parsed.relative_path == "Sample.pkf"
    assert parsed.selected_table_count == 1
    assert parsed.selected_entry_count == 4
    assert parsed.payload_kind_counts == {
        "BMP": 1,
        "GIF": 1,
        "P3D-like binary": 1,
        "RIFF/PAL": 1,
    }
    assert parsed.p3d_family_counts == {"fe...records@4": 1}
    assert parsed.tables[0].records[0].payload.bmp_width == 2
    assert parsed.tables[0].records[1].payload.gif_width == 3
    assert parsed.tables[0].records[2].payload.riff_type == "PAL "
    p3d = parsed.tables[0].records[3].payload
    assert p3d.p3d_magic_hex == "0xff7ffffe"
    assert p3d.p3d_magic_class == "P3D named resource"
    assert p3d.p3d_marker_field_count == 2
    assert p3d.p3d_family == "fe...records@4"
    assert p3d.p3d_label == "Box0"
    assert p3d.p3d_first_ascii_offset == 4
    assert p3d.p3d_record_start_offset == 4
    assert p3d.p3d_optional_header_flag is None
    assert p3d.p3d_optional_header_dwords_hex is None
    assert p3d.p3d_optional_header_floats is None
    assert p3d.p3d_printable_runs == ["Box0"]
    assert p3d.p3d_ascii_run_count == 1
    assert p3d.p3d_longest_ascii_run_length == 4
    assert p3d.p3d_first_dwords_hex[:2] == ["0xff7ffffe", "0x30786f42"]
    assert p3d.p3d_first_inner_marker_hex is None
    assert p3d.p3d_first_inner_marker_field_count is None
    assert p3d.p3d_stream_bytes_after_header == len(p3d_payload()) - 4
    assert p3d.p3d_chunk128_floor_count == 0
    assert p3d.p3d_chunk128_trailing_bytes == len(p3d_payload()) - 4
    assert p3d.p3d_chunk128_loader_iterations == 1
    assert p3d.p3d_chunk_name_samples == []
    assert p3d.p3d_float32_finite_sample_count is not None
    assert p3d.p3d_float32_plausible_sample_count is not None
    assert p3d.p3d_zero16_block_count == 0
    assert p3d.p3d_size_bucket == "<1 KiB"


def test_palette_colors() -> None:
    colors = palette_colors(pal_payload())
    assert colors == [
        {"index": 0, "r": 255, "g": 0, "b": 0, "flags": 0},
        {"index": 1, "r": 0, "g": 255, "b": 0, "flags": 0},
    ]


def test_os2_bmp_dimensions(tmp_path: Path) -> None:
    pkf_path = tmp_path / "Os2Bmp.pkf"
    payloads = [os2_bmp_payload()] * 4
    first_payload = 0x5B2
    data = bytearray(first_payload)
    cursor = first_payload
    for index, payload in enumerate(payloads):
        field = FIELD_OFFSET + index * FIELD_STRIDE
        struct.pack_into("<III", data, field, cursor, len(payload), 1)
        data.extend(payload)
        cursor += len(payload)
    pkf_path.write_bytes(bytes(data))

    parsed = parse_pkf_file(pkf_path, root=tmp_path)

    payload = parsed.tables[0].records[0].payload
    assert payload.kind == "BMP"
    assert payload.bmp_width == 3
    assert payload.bmp_height == 2
    assert payload.bmp_bpp == 8
