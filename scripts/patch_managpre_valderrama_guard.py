#!/usr/bin/env python3
"""Patch MANAGPRE.EXE with Valderrama-safe guard and Stars text fallbacks.

Patch contract (MANAGPRE only):
- Keep the proven null-pointer defense at FUN_0066f1f0 (0x0066F208 crash guard).
- Add conservative lookup-result fallback for unresolved/invalid club names at
  FUN_004B5C20 tail hook (0x004B5C76):
  - team_id 0    -> "Unknown club"
  - team_id 4705 -> "Stars"
  - team_id 4706 -> "Free players"
- Add targeted search-window team-string normalization in FUN_00474870
  pre-sprintf path (0x0047494B), forcing a non-empty text for Stars/Free/Unknown.
- Add a local Stars fallback for the transfer-signing source-club branch
  (0x004B8C19 / 0x004B8EE5) when the special 9900/0x26AC path yields empty text.
- Add a local Stars fallback for the player-record/history line post-lookup gate
  (0x0043BD46) when the 9900/0x26AC history row resolves empty text.
- Add a local Stars fallback for the standard player-profile club slot
  (0x0043F20F) when the special 9900/0x26AC path yields empty text.
- Add a local Stars fallback for the personal signing notice event
  (0x004B31A8) so {S3} is populated for the special 9900/0x26AC path.
- Revert older global formatter experiments so the patch remains field-local.

This script intentionally avoids variable-length/data-file edits.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_EXE = REPO_ROOT / ".local" / "premier-manager-ninety-nine" / "MANAGPRE.EXE"
DEFAULT_OUTPUT_EXE = Path("/tmp") / "MANAGPRE.valderrama_guard.EXE"
IMAGE_BASE = 0x400000

TEAM_ID_STARS = 4705
TEAM_ID_FREE_PLAYERS = 4706
TEAM_ID_STARS_SPECIAL = 0x26AC
VALDERRAMA_PLAYER_RECORD_ID = 20864  # 0x5180 in indexed JUG98030.FDI

# Slack region at tail of .text (file-backed): 0x006E5092..0x006E51BF (302 bytes)
CAVE_BUNDLE_BASE_VA = 0x006E5092
CAVE_BUNDLE_SIZE = 302

# Keep these string addresses stable so legacy patched bytes remain compatible.
CAVE_EMPTY_STRING_VA = 0x006E5199
CAVE_STARS_STRING_VA = 0x006E519A
CAVE_FREE_STRING_VA = 0x006E51A0
CAVE_UNKNOWN_STRING_VA = 0x006E51AD

# Standard player-profile club-slot helper uses two nearby NOP pads.
CAVE_PROFILE_CLUB_STAGE0_VA = 0x00404A41
CAVE_PROFILE_CLUB_STAGE0_SIZE = 15
CAVE_PROFILE_CLUB_STAGE1_VA = 0x004049D4
CAVE_PROFILE_CLUB_STAGE1_SIZE = 12

# Spare tail-cave slot used for player-record Stars backfill.
CAVE_PLAYER_RECORD_HELPER_VA = 0x006E51E1
CAVE_PLAYER_RECORD_HELPER_SIZE = 31

# Personal signing notice event source-club fallback ({S3}) for special 9900/Stars path.
CAVE_SIGNING_NOTICE_STAGE0_VA = 0x006E4191
CAVE_SIGNING_NOTICE_STAGE0_SIZE = 15
CAVE_SIGNING_NOTICE_DEFAULT_VA = 0x006E41B2
CAVE_SIGNING_NOTICE_DEFAULT_SIZE = 14
CAVE_SIGNING_NOTICE_COMMON_VA = 0x006E41D2
CAVE_SIGNING_NOTICE_COMMON_SIZE = 14

# Formatter-local fallback for the observed "You have signed Valderrama of ." output.
CAVE_FORMATTER_S3_STAGE0_VA = 0x006E4251
CAVE_FORMATTER_S3_STAGE0_SIZE = 15
CAVE_FORMATTER_S3_STAGE1_VA = 0x006E42D1
CAVE_FORMATTER_S3_STAGE1_SIZE = 15
CAVE_FORMATTER_S3_STAGE2_VA = 0x006E42F5
CAVE_FORMATTER_S3_STAGE2_SIZE = 11

# Proof-only route to the real player record from the offer modal.
# Proof uses isolated .text caves so it does not collide with the real fix.
CAVE_PROOF_RECORD_STAGE0_VA = 0x006E4B01
CAVE_PROOF_RECORD_STAGE0_SIZE = 15
CAVE_PROOF_RECORD_STAGE1_VA = 0x006E42D1
CAVE_PROOF_RECORD_STAGE1_SIZE = 15

# Local NOP-sled cave in FUN_00499D00 kept available for rollback compatibility.
CAVE_LE_DE_WRAPPER_VA = 0x00499E91
CAVE_LE_DE_WRAPPER_SIZE = 15

# .text zero-cave used for transfer-signing Stars source fallback.
CAVE_SIGNING_SOURCE_HELPER_VA = 0x005FC92F
CAVE_SIGNING_SOURCE_HELPER_SIZE = 24

# Null guard cave remains at proven location.
CAVE_NULL_GUARD_VA = 0x006E51C0

# Secondary object-chain null guard for crash at 0x0064CFD6.
SECONDARY_CHAIN_GUARD_SITE_VA = 0x0064CFD6
SECONDARY_CHAIN_GUARD_SITE_LEN = 15
SECONDARY_CHAIN_GUARD_STAGE0_VA = 0x0064CFFA  # 6-byte local NOP cave
SECONDARY_CHAIN_GUARD_STAGE0_SIZE = 6
SECONDARY_CHAIN_GUARD_STAGE1_VA = 0x0064CE25  # 11-byte local NOP cave
SECONDARY_CHAIN_GUARD_STAGE1_SIZE = 11
SECONDARY_CHAIN_GUARD_STAGE2_VA = 0x0064D077  # 9-byte local NOP cave
SECONDARY_CHAIN_GUARD_STAGE2_SIZE = 9


@dataclass(frozen=True)
class DirectPatch:
    name: str
    site_va: int
    expected: bytes
    replacement: bytes
    alternates: tuple[bytes, ...] = ()


def _sha256(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _read_sections(pe_bytes: bytes) -> list[dict[str, int]]:
    if pe_bytes[:2] != b"MZ":
        raise ValueError("Input is not an MZ executable")
    pe_off = struct.unpack_from("<I", pe_bytes, 0x3C)[0]
    if pe_bytes[pe_off:pe_off + 4] != b"PE\x00\x00":
        raise ValueError("Input does not contain a valid PE header")

    section_count = struct.unpack_from("<H", pe_bytes, pe_off + 6)[0]
    opt_size = struct.unpack_from("<H", pe_bytes, pe_off + 20)[0]
    section_off = pe_off + 24 + opt_size
    sections: list[dict[str, int]] = []
    for i in range(section_count):
        off = section_off + i * 40
        virtual_size, virtual_address, raw_size, raw_ptr = struct.unpack_from("<IIII", pe_bytes, off + 8)
        sections.append(
            {
                "virtual_address": virtual_address,
                "virtual_size": virtual_size,
                "raw_ptr": raw_ptr,
                "raw_size": raw_size,
            }
        )
    return sections


def _va_to_file_offset(pe_bytes: bytes, va: int) -> int:
    rva = va - IMAGE_BASE
    for sec in _read_sections(pe_bytes):
        start = sec["virtual_address"]
        size = max(sec["virtual_size"], sec["raw_size"])
        end = start + size
        if start <= rva < end:
            return sec["raw_ptr"] + (rva - start)
    raise ValueError(f"VA 0x{va:08X} does not map to a file-backed section")


def _rel32(from_va: int, instr_len: int, to_va: int) -> bytes:
    rel = to_va - (from_va + instr_len)
    return struct.pack("<i", rel)


def _build_trampoline(src_va: int, dst_va: int, total_len: int) -> bytes:
    if total_len < 5:
        raise ValueError("Trampoline region must be at least 5 bytes")
    rel = dst_va - (src_va + 5)
    return b"\xE9" + struct.pack("<i", rel) + (b"\x90" * (total_len - 5))


def _build_call(src_va: int, dst_va: int) -> bytes:
    return b"\xE8" + _rel32(src_va, 5, dst_va)


def _build_null_text_guard_stub(*, cave_va: int, resume_va: int, fallback_text_va: int) -> bytes:
    """Replays overwritten setup and normalizes NULL text ptr to a fallback label."""
    out = bytearray()

    # Original bytes from 0x0066F1FB up to (but excluding) MOV AL,[ECX].
    out += bytes.fromhex("8b4c242033f68a472033d28be8")

    # test ecx,ecx
    out += b"\x85\xC9"

    # jnz continue
    jnz_pos = len(out)
    out += b"\x0F\x85" + b"\x00\x00\x00\x00"

    # mov ecx, fallback_text
    out += b"\xB9" + struct.pack("<I", fallback_text_va)

    continue_va = cave_va + len(out)

    # original faulting read
    out += b"\x8A\x01"

    # jmp resume
    jmp_resume_pos = len(out)
    out += b"\xE9" + b"\x00\x00\x00\x00"

    out[jnz_pos + 2: jnz_pos + 6] = _rel32(cave_va + jnz_pos, 6, continue_va)
    out[jmp_resume_pos + 1: jmp_resume_pos + 5] = _rel32(cave_va + jmp_resume_pos, 5, resume_va)
    return bytes(out)


def _build_old_null_guard_stub(*, cave_va: int, resume_va: int, null_target_va: int) -> bytes:
    """Legacy v1 guard accepted for idempotent upgrades."""
    out = bytearray()
    out += bytes.fromhex("8b4c242033f68a472033d28be8")
    out += b"\x85\xC9"
    jz_pos = len(out)
    out += b"\x0F\x84" + b"\x00\x00\x00\x00"
    out += b"\x8A\x01"
    jmp_pos = len(out)
    out += b"\xE9" + b"\x00\x00\x00\x00"
    out[jz_pos + 2: jz_pos + 6] = _rel32(cave_va + jz_pos, 6, null_target_va)
    out[jmp_pos + 1: jmp_pos + 5] = _rel32(cave_va + jmp_pos, 5, resume_va)
    return bytes(out)


def _build_secondary_chain_guard_dispatch(*, site_va: int, stage0_va: int) -> bytes:
    """Guard dispatcher at 0x0064CFD6 (15-byte overwrite window)."""
    out = bytearray()
    out += b"\x85\xED"  # test ebp,ebp
    jnz_pos = len(out)
    out += b"\x75\x00"  # jnz stage0
    out += b"\x8B\x94\x24\xA4\x00\x00\x00"  # mov edx,[esp+0xA4]
    out += b"\x90" * 4
    jnz_from = site_va + jnz_pos
    jnz_next = jnz_from + 2
    rel8 = stage0_va - jnz_next
    if not -128 <= rel8 <= 127:
        raise RuntimeError(f"Secondary guard jnz rel8 out of range: {rel8}")
    out[jnz_pos + 1] = rel8 & 0xFF
    if len(out) != SECONDARY_CHAIN_GUARD_SITE_LEN:
        raise RuntimeError(
            f"Secondary guard dispatch size mismatch ({len(out)} != {SECONDARY_CHAIN_GUARD_SITE_LEN})"
        )
    return bytes(out)


def _build_secondary_chain_guard_stage0(*, cave_va: int, stage1_va: int) -> bytes:
    """Stage0 stub: bridge from short JNZ to near JMP."""
    out = bytearray()
    out += b"\xE9" + _rel32(cave_va, 5, stage1_va)
    return bytes(out)


def _build_secondary_chain_guard_stage1(*, cave_va: int, stage2_va: int) -> bytes:
    """Stage1 stub: restore argument setup and jump to stage2 call stub."""
    out = bytearray()
    out += b"\x8B\x45\x00"  # mov eax,[ebp]
    out += b"\x51"  # push ecx
    out += b"\x55"  # push ebp
    out += b"\xE9" + _rel32(cave_va + len(out), 5, stage2_va)
    return bytes(out)


def _build_secondary_chain_guard_stage2(*, cave_va: int, resume_va: int) -> bytes:
    """Stage2 stub: perform original virtual call and jump back."""
    out = bytearray()
    out += b"\xFF\x50\x58"  # call dword ptr [eax+0x58]
    out += b"\xE9" + _rel32(cave_va + len(out), 5, resume_va)
    return bytes(out)


def _build_search_window_team_prepush_helper(
    *,
    cave_va: int,
    stars_va: int,
    free_va: int,
    unknown_va: int,
) -> bytes:
    """Prepare FUN_00474870 sprintf args with ID-aware team-name fallback.

    Hook contract at 0x0047494B:
    - Input:
      - EAX: team record pointer from FUN_004B5C20
      - ESI: player record pointer
    - Output:
      - Pushes team_name, [esi+0x0c], [esi+0x08] (original order), then RET.
    """
    out = bytearray()

    # Capture CALL return address so we can rebuild stack as:
    # [esp] return, [esp+4] arg3, [esp+8] arg2, [esp+12] arg1
    out += b"\x59"  # pop ecx

    out += b"\x66\x81\x7E\x18" + struct.pack("<H", TEAM_ID_STARS)
    je_stars_pos = len(out)
    out += b"\x74\x00"

    out += b"\x66\x81\x7E\x18" + struct.pack("<H", TEAM_ID_FREE_PLAYERS)
    je_free_pos = len(out)
    out += b"\x74\x00"

    out += b"\x66\x83\x7E\x18\x00"
    je_unknown_pos = len(out)
    out += b"\x74\x00"

    # Default branch: use looked-up team text if valid, otherwise Unknown.
    out += b"\x85\xC0"  # test eax,eax
    jz_unknown_2_pos = len(out)
    out += b"\x74\x00"
    out += b"\x8B\x40\x04"  # mov eax,[eax+0x04]
    out += b"\x85\xC0"  # test eax,eax
    jz_unknown_3_pos = len(out)
    out += b"\x74\x00"
    out += b"\x8A\x10"  # mov dl,[eax]
    out += b"\x84\xD2"  # test dl,dl
    jz_unknown_4_pos = len(out)
    out += b"\x74\x00"
    out += b"\x80\xFA\x2E"  # cmp dl,'.'
    jbe_unknown_5_pos = len(out)
    out += b"\x76\x00"
    out += b"\x80\xFA\x7A"  # cmp dl,'z'
    ja_unknown_6_pos = len(out)
    out += b"\x77\x00"
    jmp_have_1_pos = len(out)
    out += b"\xEB\x00"

    set_stars_va = cave_va + len(out)
    out += b"\xB8" + struct.pack("<I", stars_va)
    jmp_have_2_pos = len(out)
    out += b"\xEB\x00"

    set_free_va = cave_va + len(out)
    out += b"\xB8" + struct.pack("<I", free_va)
    jmp_have_3_pos = len(out)
    out += b"\xEB\x00"

    set_unknown_va = cave_va + len(out)
    out += b"\xB8" + struct.pack("<I", unknown_va)

    have_va = cave_va + len(out)
    out += b"\x8B\x56\x0C"  # mov edx,[esi+0x0c]
    out += b"\x50"  # push eax (arg1 team name)
    out += b"\x8B\x46\x08"  # mov eax,[esi+0x08]
    out += b"\x52"  # push edx (arg2)
    out += b"\x50"  # push eax (arg3)
    out += b"\x51"  # push ecx (saved return address)
    out += b"\xC3"  # ret

    out[je_stars_pos + 1] = (set_stars_va - (cave_va + je_stars_pos + 2)) & 0xFF
    out[je_free_pos + 1] = (set_free_va - (cave_va + je_free_pos + 2)) & 0xFF
    out[je_unknown_pos + 1] = (set_unknown_va - (cave_va + je_unknown_pos + 2)) & 0xFF
    out[jz_unknown_2_pos + 1] = (set_unknown_va - (cave_va + jz_unknown_2_pos + 2)) & 0xFF
    out[jz_unknown_3_pos + 1] = (set_unknown_va - (cave_va + jz_unknown_3_pos + 2)) & 0xFF
    out[jz_unknown_4_pos + 1] = (set_unknown_va - (cave_va + jz_unknown_4_pos + 2)) & 0xFF
    out[jbe_unknown_5_pos + 1] = (set_unknown_va - (cave_va + jbe_unknown_5_pos + 2)) & 0xFF
    out[ja_unknown_6_pos + 1] = (set_unknown_va - (cave_va + ja_unknown_6_pos + 2)) & 0xFF
    out[jmp_have_1_pos + 1] = (have_va - (cave_va + jmp_have_1_pos + 2)) & 0xFF
    out[jmp_have_2_pos + 1] = (have_va - (cave_va + jmp_have_2_pos + 2)) & 0xFF
    out[jmp_have_3_pos + 1] = (have_va - (cave_va + jmp_have_3_pos + 2)) & 0xFF

    return bytes(out)


def _build_search_formatter_call_wrapper(
    *,
    cave_va: int,
    original_formatter_va: int,
    unknown_va: int,
) -> bytes:
    """Wrapper for FUN_0049A0E0 formatter call at 0x0049A103.

    Calls original FUN_00499D00, then ensures destination buffer is non-empty.
    """
    out = bytearray()

    call_pos = len(out)
    out += b"\xE8" + b"\x00\x00\x00\x00"  # call original formatter
    out += b"\x85\xC0"  # test eax,eax
    jz_ret_pos = len(out)
    out += b"\x74\x00"
    out += b"\x80\x38\x00"  # cmp byte ptr [eax],0
    jnz_ret_pos = len(out)
    out += b"\x75\x00"
    out += b"\x68" + struct.pack("<I", unknown_va)  # push unknown
    out += b"\x50"  # push dest
    out += b"\xFF\x15" + struct.pack("<I", 0x006E6108)  # call dword ptr [lstrcpyA]
    ret_va = cave_va + len(out)
    out += b"\xC3"  # ret

    out[call_pos + 1: call_pos + 5] = _rel32(cave_va + call_pos, 5, original_formatter_va)
    out[jz_ret_pos + 1] = (ret_va - (cave_va + jz_ret_pos + 2)) & 0xFF
    out[jnz_ret_pos + 1] = (ret_va - (cave_va + jnz_ret_pos + 2)) & 0xFF

    return bytes(out)


def _build_signing_stars_source_helper(*, cave_va: int, stars_va: int) -> bytes:
    """Return EAX = player source-club text, defaulting empty special-branch text to Stars."""
    out = bytearray()

    out += b"\x8B\x54\x24\x14"  # mov edx,[esp+0x14] (caller [esp+0x10] after CALL pushes return)
    out += b"\x8B\x42\x10"  # mov eax,[edx+0x10]
    out += b"\x85\xC0"  # test eax,eax
    jz_set_pos = len(out)
    out += b"\x74\x00"
    out += b"\x80\x38\x00"  # cmp byte ptr [eax],0
    jnz_ret_pos = len(out)
    out += b"\x75\x00"

    set_stars_va = cave_va + len(out)
    out += b"\xB8" + struct.pack("<I", stars_va)  # mov eax,stars

    ret_va = cave_va + len(out)
    out += b"\xC3"

    out[jz_set_pos + 1] = (set_stars_va - (cave_va + jz_set_pos + 2)) & 0xFF
    out[jnz_ret_pos + 1] = (ret_va - (cave_va + jnz_ret_pos + 2)) & 0xFF
    return bytes(out)


def _build_player_record_stars_fill_helper(*, cave_va: int) -> bytes:
    """Fill the player-record/history buffer with Stars when the 9900 row resolved empty."""
    out = bytearray()

    out += b"\x80\x7C\x24\x0C\x00"  # cmp byte ptr [esp+0xc],0
    jnz_ret_pos = len(out)
    out += b"\x75\x00"
    out += b"\x81\x3E" + struct.pack("<I", 0x26AC)  # cmp dword ptr [esi],0x26ac
    jne_ret_pos = len(out)
    out += b"\x75\x00"
    out += b"\xC7\x44\x24\x0C" + struct.pack("<I", 0x72617453)  # mov dword ptr [esp+0xc],"Star"
    out += b"\x66\xC7\x44\x24\x10\x73\x00"  # mov word ptr [esp+0x10],"s\\0"

    ret_va = cave_va + len(out)
    out += b"\xC3"

    out[jnz_ret_pos + 1] = (ret_va - (cave_va + jnz_ret_pos + 2)) & 0xFF
    out[jne_ret_pos + 1] = (ret_va - (cave_va + jne_ret_pos + 2)) & 0xFF
    return bytes(out)



def _build_signing_notice_stages(
    *,
    stage0_va: int,
    default_va: int,
    common_va: int,
    stars_va: int,
    original_source_va: int,
    resume_va: int,
    force_stars: bool = False,
) -> tuple[bytes, bytes, bytes]:
    """Patch event 0x453 so the special 9900/Stars path supplies {S3}=Stars."""
    stage0 = bytearray()
    if force_stars:
        stage0 += b"\x68" + struct.pack("<I", stars_va)  # push Stars for {S3}
        stage0 += b"\xEB" + bytes([(common_va - (stage0_va + len(stage0) + 1)) & 0xFF])
    else:
        stage0 += b"\x81\x3E" + struct.pack("<I", TEAM_ID_STARS_SPECIAL)  # cmp dword ptr [esi],0x26ac
        jne_default_pos = len(stage0)
        stage0 += b"\x75\x00"
        stage0 += b"\x68" + struct.pack("<I", stars_va)  # push Stars for {S3}
        jmp_common_pos = len(stage0)
        stage0 += b"\xEB\x00"
        stage0[jne_default_pos + 1] = (default_va - (stage0_va + jne_default_pos + 2)) & 0xFF
        stage0[jmp_common_pos + 1] = (common_va - (stage0_va + jmp_common_pos + 2)) & 0xFF

    default = bytearray()
    default += b"\x53"  # push ebx (original null {S3})
    default += b"\xEB" + bytes([(common_va - (default_va + len(default) + 1)) & 0xFF])

    common = bytearray()
    common += b"\x50"  # push eax ({S2}, already computed by original LEA)
    common += b"\x8B\xCF"  # mov ecx,edi
    common += b"\xE8" + _rel32(common_va + len(common), 5, original_source_va)
    common += b"\xE9" + _rel32(common_va + len(common), 5, resume_va)
    return bytes(stage0), bytes(default), bytes(common)




def _build_formatter_s3_valderrama_stages(
    *,
    stage0_va: int,
    stage1_va: int,
    stage2_va: int,
    stars_va: int,
    original_push_va: int,
    original_skip_va: int,
) -> tuple[bytes, bytes, bytes]:
    """For {S3}, backfill Stars only when the event player id is Valderrama."""
    stage0 = bytearray()
    stage0 += b"\x8B\x45\x18"  # mov eax,[ebp+0x18] (original {S3})
    stage0 += b"\x85\xC0"  # test eax,eax
    jz_stage1_pos = len(stage0)
    stage0 += b"\x74\x00"  # null {S3}: inspect the player id
    stage0 += b"\xE9" + _rel32(stage0_va + len(stage0), 5, original_push_va)
    stage0[jz_stage1_pos + 1] = (stage1_va - (stage0_va + jz_stage1_pos + 2)) & 0xFF

    stage1 = bytearray()
    stage1 += b"\x81\x7D\x08" + struct.pack("<I", VALDERRAMA_PLAYER_RECORD_ID)
    je_stage2_pos = len(stage1)
    stage1 += b"\x74\x00"
    stage1 += b"\xE9" + _rel32(stage1_va + len(stage1), 5, original_skip_va)
    stage1[je_stage2_pos + 1] = (stage2_va - (stage1_va + je_stage2_pos + 2)) & 0xFF

    stage2 = bytearray()
    stage2 += b"\xB8" + struct.pack("<I", stars_va)  # mov eax,Stars
    stage2 += b"\xE9" + _rel32(stage2_va + len(stage2), 5, original_push_va)
    return bytes(stage0), bytes(stage1), bytes(stage2)


def _build_profile_club_stars_stage0(*, stage0_va: int, stage1_va: int) -> bytes:
    """Stage0 for the standard profile club-slot text fallback."""
    out = bytearray()
    out += b"\x8B\x47\x10"  # mov eax,[edi+0x10]
    out += b"\x85\xC0"  # test eax,eax
    jz_stage1_pos = len(out)
    out += b"\x74\x00"
    out += b"\x80\x38\x00"  # cmp byte ptr [eax],0
    jmp_stage1_pos = len(out)
    out += b"\xEB\x00"
    out += b"\x90" * (CAVE_PROFILE_CLUB_STAGE0_SIZE - len(out))

    rel8_jz = stage1_va - (stage0_va + jz_stage1_pos + 2)
    rel8_jmp = stage1_va - (stage0_va + jmp_stage1_pos + 2)
    if not -128 <= rel8_jz <= 127 or not -128 <= rel8_jmp <= 127:
        raise RuntimeError("Profile-club stage0 short branches are out of range")
    out[jz_stage1_pos + 1] = rel8_jz & 0xFF
    out[jmp_stage1_pos + 1] = rel8_jmp & 0xFF
    if len(out) != CAVE_PROFILE_CLUB_STAGE0_SIZE:
        raise RuntimeError("Profile-club stage0 size mismatch")
    return bytes(out)


def _build_profile_club_stars_stage1(*, stage1_va: int, stars_va: int, resume_va: int) -> bytes:
    """Stage1 for the standard profile club-slot text fallback."""
    out = bytearray()
    out += b"\x75\x05"  # jnz jmp_resume
    out += b"\xB8" + struct.pack("<I", stars_va)  # mov eax,stars
    out += b"\xE9" + _rel32(stage1_va + len(out), 5, resume_va)
    if len(out) != CAVE_PROFILE_CLUB_STAGE1_SIZE:
        raise RuntimeError("Profile-club stage1 size mismatch")
    return bytes(out)


def _build_proof_record_stage(*, cave_va: int, target_va: int, value: int, next_va: int) -> bytes:
    """Proof-only stage: write one byte flag, then jump to the next stage."""
    out = bytearray()
    out += b"\xC6\x05" + struct.pack("<I", target_va) + bytes((value & 0xFF,))
    out += b"\xE9" + _rel32(cave_va + len(out), 5, next_va)
    return bytes(out)


def _build_proof_record_stage_final(*, cave_va: int, target_va: int, value: int, open_record_va: int) -> bytes:
    """Proof-only final stage: write last mode byte, then open the player record."""
    out = bytearray()
    out += b"\xC6\x05" + struct.pack("<I", target_va) + bytes((value & 0xFF,))
    out += b"\xE8" + _rel32(cave_va + len(out), 5, open_record_va)
    out += b"\xC2\x04\x00"  # ret 4
    return bytes(out)


def _build_proof_search_row_open_block(*, site_va: int, resume_va: int) -> bytes:
    """Proof-only inline replacement for FUN_00497E40 selected-row open path.

    Uses the already-resolved selected player in EDI and derives the main app
    object from the search-window owner pointer in EBP (`EBP - 0x541C4`),
    then routes directly into the standard TACTICS/STATISTICS record screen.
    """
    out = bytearray()
    out += b"\x89\x3D" + struct.pack("<I", 0x007546E8)  # mov [0x7546e8],edi
    out += b"\x88\x1D" + struct.pack("<I", 0x0072F118)  # mov [0x72f118],bl
    out += b"\x88\x1D" + struct.pack("<I", 0x0072F11C)  # mov [0x72f11c],bl
    out += b"\x88\x1D" + struct.pack("<I", 0x0072F124)  # mov [0x72f124],bl
    out += b"\x88\x1D" + struct.pack("<I", 0x0072F128)  # mov [0x72f128],bl
    out += b"\x88\x1D" + struct.pack("<I", 0x0072F12C)  # mov [0x72f12c],bl
    out += b"\xC6\x05" + struct.pack("<I", 0x0072F120) + b"\x01"  # mov [0x72f120],1
    out += b"\x8D\x8D\x3C\xBE\xFA\xFF"  # lea ecx,[ebp-0x541c4]
    out += b"\xE8" + _rel32(site_va + len(out), 5, 0x0043DD30)
    out += b"\xE9" + _rel32(site_va + len(out), 5, resume_va)
    return bytes(out)


def _build_search_token_le_de_call_wrapper(*, cave_va: int, original_lookup_va: int) -> bytes:
    """Wrapper for 0x00499E0A call site ({LE}/{DE} token branch).

    Behavior:
    - call original FUN_004A4720
    - if EAX == NULL, fall back to pre-pushed team base-name pointer ([esp+0x10])
    - return EAX to caller
    """
    out = bytearray()

    call_pos = len(out)
    out += b"\xE8" + b"\x00\x00\x00\x00"  # call original lookup
    out += b"\x85\xC0"  # test eax,eax
    jnz_ret_pos = len(out)
    out += b"\x75\x00"
    out += b"\x8B\x44\x24\x10"  # mov eax,[esp+0x10]
    ret_va = cave_va + len(out)
    out += b"\xC3"

    out[call_pos + 1: call_pos + 5] = _rel32(cave_va + call_pos, 5, original_lookup_va)
    out[jnz_ret_pos + 1] = (ret_va - (cave_va + jnz_ret_pos + 2)) & 0xFF
    return bytes(out)


def _build_search_empty_template_fallback_helper(*, unknown_va: int) -> bytes:
    """FUN_0049A0E0 empty-template path helper.

    Writes "Unknown club" into caller output buffer and returns it.
    """
    out = bytearray()
    out += b"\x8B\x74\x24\x08"  # mov esi,[esp+0x8]
    out += b"\x68" + struct.pack("<I", unknown_va)  # push unknown string
    out += b"\x56"  # push esi
    out += b"\xFF\x15" + struct.pack("<I", 0x006E6108)  # call dword ptr [lstrcpyA]
    out += b"\x5E"  # pop esi
    out += b"\xC2\x08\x00"  # ret 8
    return bytes(out)


def _build_lookup_result_fallback_helper(
    *,
    cave_va: int,
    epilogue_va: int,
    unknown_rec_va: int,
    stars_rec_va: int,
    free_rec_va: int,
) -> bytes:
    """Helper for 0x004B5C20 tail result handling.

    Input registers at hook point:
    - EAX: candidate team-record pointer
    - EBX: requested team ID

    Behavior:
    - if candidate is NULL -> fallback mapping
    - if candidate ID matches AND candidate name pointer/text is valid -> keep EAX
    - else fallback records for unresolved IDs (0, 4705, 4706, 0x26AC special Stars path)
    - all unresolved IDs degrade to unknown-club record (never NULL)
    - always jump to original epilogue at 0x004B5C7D
    """
    out = bytearray()

    out += b"\x85\xC0"  # test eax,eax
    jz_fallback_pos = len(out)
    out += b"\x0F\x84" + b"\x00\x00\x00\x00"

    out += b"\x39\x58\x10"  # cmp dword ptr [eax+0x10],ebx
    jne_fallback_pos = len(out)
    out += b"\x0F\x85" + b"\x00\x00\x00\x00"

    out += b"\x8B\x50\x04"  # mov edx,[eax+0x04]
    out += b"\x85\xD2"  # test edx,edx
    jz_fallback_2_pos = len(out)
    out += b"\x0F\x84" + b"\x00\x00\x00\x00"

    out += b"\x8A\x0A"  # mov cl,[edx]
    out += b"\x84\xC9"  # test cl,cl
    jz_fallback_3_pos = len(out)
    out += b"\x0F\x8E" + b"\x00\x00\x00\x00"

    out += b"\x80\xF9\x2E"  # cmp cl,'.'
    jbe_fallback_4_pos = len(out)
    out += b"\x0F\x86" + b"\x00\x00\x00\x00"

    jmp_epilogue_match_pos = len(out)
    out += b"\xE9" + b"\x00\x00\x00\x00"

    fallback_va = cave_va + len(out)

    out += b"\x85\xDB"  # test ebx,ebx
    je_unknown_pos = len(out)
    out += b"\x74\x00"

    out += b"\x66\x81\xFB" + struct.pack("<H", TEAM_ID_STARS)
    je_stars_pos = len(out)
    out += b"\x74\x00"

    out += b"\x66\x81\xFB" + struct.pack("<H", TEAM_ID_FREE_PLAYERS)
    je_free_pos = len(out)
    out += b"\x74\x00"

    out += b"\x66\x81\xFB" + struct.pack("<H", TEAM_ID_STARS_SPECIAL)
    je_special_stars_pos = len(out)
    out += b"\x74\x00"

    jmp_set_unknown_pos = len(out)
    out += b"\xEB\x00"

    set_unknown_va = cave_va + len(out)
    out += b"\xB8" + struct.pack("<I", unknown_rec_va)
    jmp_epilogue_unknown_pos = len(out)
    out += b"\xEB\x00"

    set_stars_va = cave_va + len(out)
    out += b"\xB8" + struct.pack("<I", stars_rec_va)
    jmp_epilogue_stars_pos = len(out)
    out += b"\xEB\x00"

    set_free_va = cave_va + len(out)
    out += b"\xB8" + struct.pack("<I", free_rec_va)
    jmp_epilogue_free_pos = len(out)
    out += b"\xEB\x00"

    final_jump_va = cave_va + len(out)
    out += b"\xE9" + b"\x00\x00\x00\x00"

    out[jz_fallback_pos + 2: jz_fallback_pos + 6] = _rel32(cave_va + jz_fallback_pos, 6, fallback_va)
    out[jne_fallback_pos + 2: jne_fallback_pos + 6] = _rel32(cave_va + jne_fallback_pos, 6, fallback_va)
    out[jz_fallback_2_pos + 2: jz_fallback_2_pos + 6] = _rel32(cave_va + jz_fallback_2_pos, 6, fallback_va)
    out[jz_fallback_3_pos + 2: jz_fallback_3_pos + 6] = _rel32(cave_va + jz_fallback_3_pos, 6, fallback_va)
    out[jbe_fallback_4_pos + 2: jbe_fallback_4_pos + 6] = _rel32(cave_va + jbe_fallback_4_pos, 6, fallback_va)
    out[jmp_epilogue_match_pos + 1: jmp_epilogue_match_pos + 5] = _rel32(cave_va + jmp_epilogue_match_pos, 5, epilogue_va)

    for pos, target in (
        (je_unknown_pos, set_unknown_va),
        (je_stars_pos, set_stars_va),
        (je_free_pos, set_free_va),
        (je_special_stars_pos, set_stars_va),
        (jmp_set_unknown_pos, set_unknown_va),
        (jmp_epilogue_unknown_pos, final_jump_va),
        (jmp_epilogue_stars_pos, final_jump_va),
        (jmp_epilogue_free_pos, final_jump_va),
    ):
        rel8 = target - (cave_va + pos + 2)
        if not -128 <= rel8 <= 127:
            raise RuntimeError(f"lookup fallback short branch out of range: {rel8}")
        out[pos + 1] = rel8 & 0xFF

    out[final_jump_va - cave_va + 1: final_jump_va - cave_va + 5] = _rel32(final_jump_va, 5, epilogue_va)
    return bytes(out)

def _build_fake_team_record(*, name_ptr_va: int, team_id: int) -> bytes:
    """Minimal fake team record used for text-only fallback paths.

    Layout used by observed callers:
    - +0x04 : char* team-name pointer
    - +0x08 : char* auxiliary/team-name pointer used by transfer-event records
    - +0x10 : uint32 team_id
    """
    rec = bytearray(0x14)
    struct.pack_into("<I", rec, 0x04, int(name_ptr_va))
    struct.pack_into("<I", rec, 0x08, int(name_ptr_va))
    struct.pack_into("<I", rec, 0x10, int(team_id))
    return bytes(rec)


def _build_bundle() -> tuple[bytes, dict[str, int], bytes]:
    strings_blob = b"\x00Stars\x00Free players\x00Unknown club\x00"

    # String addresses are fixed contract points.
    string_addrs = {
        "empty": CAVE_EMPTY_STRING_VA,
        "stars": CAVE_STARS_STRING_VA,
        "free": CAVE_FREE_STRING_VA,
        "unknown": CAVE_UNKNOWN_STRING_VA,
    }

    # Build helpers once to lock lengths.
    search_tmp = _build_search_window_team_prepush_helper(
        cave_va=CAVE_BUNDLE_BASE_VA,
        stars_va=0,
        free_va=0,
        unknown_va=0,
    )

    lookup_tmp = _build_lookup_result_fallback_helper(
        cave_va=CAVE_BUNDLE_BASE_VA + len(search_tmp),
        epilogue_va=0x004B5C7D,
        unknown_rec_va=0,
        stars_rec_va=0,
        free_rec_va=0,
    )

    rec_base_va = CAVE_BUNDLE_BASE_VA + len(search_tmp) + len(lookup_tmp)
    unknown_rec_va = rec_base_va
    stars_rec_va = rec_base_va + 0x14
    free_rec_va = rec_base_va + 0x28

    search_real = _build_search_window_team_prepush_helper(
        cave_va=CAVE_BUNDLE_BASE_VA,
        stars_va=string_addrs["stars"],
        free_va=string_addrs["free"],
        unknown_va=string_addrs["unknown"],
    )

    lookup_real = _build_lookup_result_fallback_helper(
        cave_va=CAVE_BUNDLE_BASE_VA + len(search_real),
        epilogue_va=0x004B5C7D,
        unknown_rec_va=unknown_rec_va,
        stars_rec_va=stars_rec_va,
        free_rec_va=free_rec_va,
    )

    if len(search_tmp) != len(search_real) or len(lookup_tmp) != len(lookup_real):
        raise RuntimeError("Internal helper sizing mismatch")

    rec_unknown = _build_fake_team_record(name_ptr_va=string_addrs["unknown"], team_id=0)
    rec_stars = _build_fake_team_record(name_ptr_va=string_addrs["stars"], team_id=TEAM_ID_STARS)
    rec_free = _build_fake_team_record(name_ptr_va=string_addrs["free"], team_id=TEAM_ID_FREE_PLAYERS)

    prefix = search_real + lookup_real + rec_unknown + rec_stars + rec_free
    prefix_end_va = CAVE_BUNDLE_BASE_VA + len(prefix)
    pad_len = CAVE_EMPTY_STRING_VA - prefix_end_va
    if pad_len < 0:
        raise RuntimeError(
            f"Bundle overflow before fixed strings: end=0x{prefix_end_va:08X} > strings=0x{CAVE_EMPTY_STRING_VA:08X}"
        )

    bundle = prefix + (b"\x00" * pad_len) + strings_blob
    if len(bundle) > CAVE_BUNDLE_SIZE:
        raise RuntimeError(f"Bundle too large ({len(bundle)} > {CAVE_BUNDLE_SIZE})")
    if len(bundle) < CAVE_BUNDLE_SIZE:
        bundle += b"\x00" * (CAVE_BUNDLE_SIZE - len(bundle))

    legacy_bundle_prefixes = (
        bytes.fromhex("e8890bddff85c00f84140000008b4004"),
        bytes.fromhex("e889f6dbff85c00f84130000008a1084d20f840900000080fa2e0f8730000000"),
        bytes.fromhex("e889f6dbff85c00f84130000008a1084d20f8e0900000080fa2e0f8730000000"),
        bytes.fromhex("e889f6dbff85c00f84140000008a1080fa300f820900000080fa7a0f8630000000"),
        bytes.fromhex("0fb7c08b54241485d20f8412000000803a000f8409000000803a2e0f8740000000"),
        bytes.fromhex("0fb7c08b54241485d20f841a0000008a0284c00f84100000003c800f83080000003c2e0f874c000000"),
        bytes.fromhex("85c074118a1084d2740b80fa2e760680fa7a7701"),
        bytes.fromhex("66817e186112741466817e186212741366837e180074138b4004eb13"),
        bytes.fromhex("5966817e186112741c66817e186212741b66837e1800741b85c07417"),
        bytes.fromhex("5966817e186112742c66817e186212742b66837e1800742b85c07427"),
    )
    return bundle, string_addrs, legacy_bundle_prefixes


def _build_patch_plan(
    search_text_helper_va: int,
    lookup_helper_va: int,
    signing_source_helper_va: int,
    player_record_helper_va: int,
    profile_club_stage0_va: int,
    *,
    proof_open_record: bool,
) -> list[DirectPatch]:
    orig_search_call = bytes.fromhex("e8d5120400")
    orig_transfer_a = bytes.fromhex("e8d8b3fbff8b4004")
    orig_transfer_b = bytes.fromhex("e887a6fbff8b4004")

    old_tramp_search = _build_trampoline(0x00474946, 0x006E5092, len(orig_search_call))
    old_tramp_search_legacy8 = _build_trampoline(0x00474946, 0x006E5092, 8)
    old_tramp_transfer_a = _build_trampoline(0x004FA843, 0x006E50EB, len(orig_transfer_a))
    old_tramp_transfer_b = _build_trampoline(0x004FB594, 0x006E5142, len(orig_transfer_b))

    old_sign_call_a = _build_call(0x004B8C2E, 0x006E51E1)
    old_sign_call_b = _build_call(0x004B8EFA, 0x006E51E1)
    old_sign_call_a_v2 = _build_call(0x004B8C2E, 0x006E5092)
    old_sign_call_b_v2 = _build_call(0x004B8EFA, 0x006E5092)

    old_lookup_bytes = bytes.fromhex("395810740933c0")
    unpatched_lookup_bytes = bytes.fromhex("395810740233c0")
    old_lookup_trampoline = _build_trampoline(0x004B5C76, 0x006E50F4, len(unpatched_lookup_bytes))
    old_lookup_trampoline_v2 = _build_trampoline(0x004B5C76, 0x006E5108, len(unpatched_lookup_bytes))
    old_lookup_trampoline_v3 = _build_trampoline(0x004B5C76, 0x006E50E3, len(unpatched_lookup_bytes))
    old_lookup_trampoline_v4 = _build_trampoline(0x004B5C76, 0x006E50E4, len(unpatched_lookup_bytes))
    old_lookup_trampoline_v5 = _build_trampoline(0x004B5C76, 0x006E50CB, len(unpatched_lookup_bytes))

    old_null_guard_trampoline = _build_trampoline(0x0066F1FB, 0x006E51C0, 15)
    secondary_chain_dispatch = _build_secondary_chain_guard_dispatch(
        site_va=SECONDARY_CHAIN_GUARD_SITE_VA,
        stage0_va=SECONDARY_CHAIN_GUARD_STAGE0_VA,
    )

    old_hook_block = bytes.fromhex("e878ee2200e9efffffff9090")
    old_search_499d00_a = _build_call(0x00499DCF, search_text_helper_va) + (b"\x90" * 6)
    old_search_499d00_b = _build_call(0x00499DED, search_text_helper_va) + (b"\x90" * 2)
    old_token_hook_499e5b = _build_trampoline(0x00499E5B, CAVE_PLAYER_RECORD_HELPER_VA, 8)
    search_name_resolve_call_499dcf = _build_call(0x00499DCF, CAVE_PLAYER_RECORD_HELPER_VA) + (b"\x90" * 6)
    search_name_resolve_call_499ded = _build_call(0x00499DED, CAVE_PLAYER_RECORD_HELPER_VA) + (b"\x90" * 2)
    search_name_resolve_call_499e5b = _build_call(0x00499E5B, CAVE_PLAYER_RECORD_HELPER_VA) + b"\x50\xEB\x00"

    patches = [
        # Revert old experimental upstream list/profile trampolines.
        DirectPatch(
            name="restore_lookup_search_FUN_00474870",
            site_va=0x00474946,
            expected=orig_search_call,
            replacement=orig_search_call,
            alternates=(old_tramp_search, old_tramp_search_legacy8),
        ),
        DirectPatch(
            name="restore_lookup_transfer_FUN_004FA000",
            site_va=0x004FA843,
            expected=orig_transfer_a,
            replacement=orig_transfer_a,
            alternates=(old_tramp_transfer_a,),
        ),
        DirectPatch(
            name="restore_lookup_transfer_FUN_004FAC80",
            site_va=0x004FB594,
            expected=orig_transfer_b,
            replacement=orig_transfer_b,
            alternates=(old_tramp_transfer_b,),
        ),
        # Restore old helper-hooked AND instructions (idempotent upgrade path).
        DirectPatch(
            name="restore_signing_multiyear_hook_FUN_004b8b40",
            site_va=0x004B8C2E,
            expected=bytes.fromhex("25ffff0000"),
            replacement=bytes.fromhex("25ffff0000"),
            alternates=(old_sign_call_a, old_sign_call_a_v2),
        ),
        DirectPatch(
            name="restore_signing_multiyear_hook_FUN_004b8e20",
            site_va=0x004B8EFA,
            expected=bytes.fromhex("25ffff0000"),
            replacement=bytes.fromhex("25ffff0000"),
            alternates=(old_sign_call_b, old_sign_call_b_v2),
        ),
        # Restore source-wrapper calls to original function (remove RC1 wrappers).
        DirectPatch(
            name="restore_source_wrapper_FUN_004b8b40_multiyear",
            site_va=0x004B8C3D,
            expected=_build_call(0x004B8C3D, 0x004A4720),
            replacement=_build_call(0x004B8C3D, 0x004A4720),
            alternates=(_build_call(0x004B8C3D, 0x006E5092),),
        ),
        DirectPatch(
            name="restore_source_wrapper_FUN_004b8b40_oneyear",
            site_va=0x004B8C73,
            expected=_build_call(0x004B8C73, 0x004A4720),
            replacement=_build_call(0x004B8C73, 0x004A4720),
            alternates=(_build_call(0x004B8C73, 0x006E5092),),
        ),
        DirectPatch(
            name="restore_source_wrapper_FUN_004b8e20_multiyear",
            site_va=0x004B8F09,
            expected=_build_call(0x004B8F09, 0x004A4720),
            replacement=_build_call(0x004B8F09, 0x004A4720),
            alternates=(_build_call(0x004B8F09, 0x006E5092),),
        ),
        DirectPatch(
            name="restore_source_wrapper_FUN_004b8e20_oneyear",
            site_va=0x004B8F3F,
            expected=_build_call(0x004B8F3F, 0x004A4720),
            replacement=_build_call(0x004B8F3F, 0x004A4720),
            alternates=(_build_call(0x004B8F3F, 0x006E5092),),
        ),
        # Keep {LE}/{DE} lookup branch at original target.
        DirectPatch(
            name="restore_search_token_LE_DE_wrapper_call_FUN_00499d00",
            site_va=0x00499E0A,
            expected=_build_call(0x00499E0A, 0x004A4720),
            replacement=_build_call(0x00499E0A, 0x004A4720),
            alternates=(_build_call(0x00499E0A, CAVE_LE_DE_WRAPPER_VA),),
        ),
        # Restore previous 00499D00 token-branch experiments.
        DirectPatch(
            name="restore_search_token_branch_FUN_00499d00_A",
            site_va=0x00499DCF,
            expected=bytes.fromhex("8b400485c00f8496000000"),
            replacement=bytes.fromhex("8b400485c00f8496000000"),
            alternates=(old_search_499d00_a, search_name_resolve_call_499dcf),
        ),
        DirectPatch(
            name="restore_search_token_branch_FUN_00499d00_B",
            site_va=0x00499DED,
            expected=bytes.fromhex("8b400485c0747c"),
            replacement=bytes.fromhex("8b400485c0747c"),
            alternates=(old_search_499d00_b, search_name_resolve_call_499ded),
        ),
        DirectPatch(
            name="restore_search_token_branch_FUN_00499d00_C",
            site_va=0x00499E5B,
            expected=bytes.fromhex("8b400485c0740e50"),
            replacement=bytes.fromhex("8b400485c0740e50"),
            alternates=(old_token_hook_499e5b, search_name_resolve_call_499e5b),
        ),
        # Keep global formatter call at original target.
        DirectPatch(
            name="restore_search_formatter_call_FUN_0049a0e0",
            site_va=0x0049A103,
            expected=_build_call(0x0049A103, 0x00499D00),
            replacement=_build_call(0x0049A103, 0x00499D00),
            alternates=(_build_call(0x0049A103, CAVE_PLAYER_RECORD_HELPER_VA),),
        ),
        # Keep empty-template branch at original bytes.
        DirectPatch(
            name="restore_search_formatter_empty_template_branch_FUN_0049a0e0",
            site_va=0x0049A111,
            expected=bytes.fromhex("8b7424088bc6c606005ec20800"),
            replacement=bytes.fromhex("8b7424088bc6c606005ec20800"),
            alternates=(_build_trampoline(0x0049A111, CAVE_SIGNING_SOURCE_HELPER_VA, 13),),
        ),
        # Actual Search Player window path.
        DirectPatch(
            name="search_window_team_text_prepush_FUN_00474870",
            site_va=0x0047494B,
            expected=bytes.fromhex("8b40048b560c508b46085250"),
            replacement=_build_call(0x0047494B, search_text_helper_va) + (b"\x90" * 7),
        ),
        # Lookup-result fallback hook at FUN_004b5c20 tail.
        DirectPatch(
            name="lookup_result_fallback_FUN_004b5c20",
            site_va=0x004B5C76,
            expected=unpatched_lookup_bytes,
            replacement=_build_trampoline(0x004B5C76, lookup_helper_va, len(unpatched_lookup_bytes)),
            alternates=(
                old_lookup_bytes,
                old_lookup_trampoline,
                old_lookup_trampoline_v2,
                old_lookup_trampoline_v3,
                old_lookup_trampoline_v4,
                old_lookup_trampoline_v5,
            ),
        ),
        # Clean obsolete hook block bytes (idempotent).
        DirectPatch(
            name="clear_obsolete_lookup_hook_block",
            site_va=0x004B5C84,
            expected=bytes.fromhex("909090909090909090909090"),
            replacement=bytes.fromhex("909090909090909090909090"),
            alternates=(old_hook_block,),
        ),
        # Proven null-guard trampoline site.
        DirectPatch(
            name="defense_in_depth_textptr_normalize_FUN_0066f1f0",
            site_va=0x0066F1FB,
            expected=bytes.fromhex("8b4c242033f68a472033d28be88a01"),
            replacement=_build_trampoline(0x0066F1FB, CAVE_NULL_GUARD_VA, 15),
            alternates=(old_null_guard_trampoline,),
        ),
        # Secondary object-chain guard for pre-season crash in FUN_0064ce30.
        DirectPatch(
            name="secondary_chain_guard_FUN_0064ce30",
            site_va=SECONDARY_CHAIN_GUARD_SITE_VA,
            expected=bytes.fromhex("8b45005155ff50588b9424a4000000"),
            replacement=secondary_chain_dispatch,
        ),
        # Special transfer-signing source branch: empty 9900/Stars text -> "Stars".
        DirectPatch(
            name="signing_source_stars_branch_FUN_004b8b40",
            site_va=0x004B8C19,
            expected=bytes.fromhex("8b5424108b4210"),
            replacement=_build_call(0x004B8C19, signing_source_helper_va) + (b"\x90" * 2),
        ),
        DirectPatch(
            name="signing_source_stars_branch_FUN_004b8e20",
            site_va=0x004B8EE5,
            expected=bytes.fromhex("8b5424108b4210"),
            replacement=_build_call(0x004B8EE5, signing_source_helper_va) + (b"\x90" * 2),
        ),
        # Player-record/history line: empty 9900 row -> "Stars".
        DirectPatch(
            name="player_record_stars_fill_FUN_0043bd10",
            site_va=0x0043BD46,
            expected=bytes.fromhex("8a44240c84c0744a"),
            replacement=_build_call(0x0043BD46, player_record_helper_va) + (b"\x90" * 3),
            alternates=(_build_call(0x0043BD46, CAVE_LE_DE_WRAPPER_VA) + (b"\x90" * 3),),
        ),
        # Standard player-profile club slot: empty 9900/Stars text -> "Stars".
        DirectPatch(
            name="player_profile_club_slot_stars_FUN_0043f1ef",
            site_va=0x0043F20F,
            expected=bytes.fromhex("8b4710eb21"),
            replacement=_build_trampoline(0x0043F20F, profile_club_stage0_va, 5),
        ),
        # Personal signing notice event 0x453: fill {S3}=Stars for special 9900/Stars.
        DirectPatch(
            name="signing_notice_s3_stars_FUN_004b2fc0",
            site_va=0x004B31A8,
            expected=bytes.fromhex("53508bcfe84fedffff"),
            replacement=_build_trampoline(0x004B31A8, CAVE_SIGNING_NOTICE_STAGE0_VA, 9),
        ),
        # Formatter {S3}: null S3 + Valderrama player id -> "Stars".
        DirectPatch(
            name="formatter_s3_valderrama_stars_FUN_00499d00",
            site_va=0x00499DA1,
            expected=bytes.fromhex("8b451885c00f84c4000000"),
            replacement=_build_trampoline(0x00499DA1, CAVE_FORMATTER_S3_STAGE0_VA, 11),
        ),
    ]

    if proof_open_record:
        patches.append(
            DirectPatch(
                name="proof_offer_pane_entry_to_player_record",
                site_va=0x00442900,
                expected=bytes.fromhex("64a100000000"),
                replacement=_build_trampoline(0x00442900, CAVE_PROOF_RECORD_STAGE0_VA, 6),
            )
        )

    return patches


def apply_patch(
    *,
    input_exe: Path,
    output_exe: Path | None,
    in_place: bool,
    dry_run: bool,
    force: bool,
    make_backup: bool,
    proof_open_record: bool = False,
    proof_force_signing_notice_stars: bool = False,
) -> dict[str, Any]:
    input_bytes = input_exe.read_bytes()
    patched = bytearray(input_bytes)

    bundle, string_addrs, legacy_bundle_prefixes = _build_bundle()

    search_text_helper_va = CAVE_BUNDLE_BASE_VA
    search_text_helper_len = len(
        _build_search_window_team_prepush_helper(
            cave_va=CAVE_BUNDLE_BASE_VA,
            stars_va=string_addrs["stars"],
            free_va=string_addrs["free"],
            unknown_va=string_addrs["unknown"],
        )
    )
    signing_source_helper_va = CAVE_SIGNING_SOURCE_HELPER_VA
    lookup_helper_va = CAVE_BUNDLE_BASE_VA + search_text_helper_len
    player_record_helper_va = CAVE_PLAYER_RECORD_HELPER_VA
    profile_club_stage0_va = CAVE_PROFILE_CLUB_STAGE0_VA

    patches = _build_patch_plan(
        search_text_helper_va=search_text_helper_va,
        lookup_helper_va=lookup_helper_va,
        signing_source_helper_va=signing_source_helper_va,
        player_record_helper_va=player_record_helper_va,
        profile_club_stage0_va=profile_club_stage0_va,
        proof_open_record=proof_open_record,
    )

    rows: list[dict[str, Any]] = []

    # Write bundle cave region.
    bundle_off = _va_to_file_offset(input_bytes, CAVE_BUNDLE_BASE_VA)
    current_bundle = input_bytes[bundle_off: bundle_off + CAVE_BUNDLE_SIZE]

    all_zero = current_bundle == (b"\x00" * CAVE_BUNDLE_SIZE)
    all_cc = current_bundle == (b"\xCC" * CAVE_BUNDLE_SIZE)
    old_bundle_like = any(current_bundle.startswith(prefix) for prefix in legacy_bundle_prefixes)
    new_bundle = current_bundle == bundle

    if not force and not (all_zero or all_cc or old_bundle_like or new_bundle):
        raise RuntimeError(
            "Bundle cave bytes are not recognized (neither pristine nor known previous patch). "
            "Use --force only after manual verification."
        )

    patched[bundle_off: bundle_off + CAVE_BUNDLE_SIZE] = bundle
    rows.append(
        {
            "name": "write_shared_fallback_bundle_cave",
            "site_va": f"0x{CAVE_BUNDLE_BASE_VA:08X}",
            "site_file_offset": f"0x{bundle_off:08X}",
            "site_before": current_bundle[:64].hex(),
            "site_after": bundle[:64].hex(),
            "bytes_written": CAVE_BUNDLE_SIZE,
        }
    )

    # Apply direct patch sites.
    for spec in patches:
        site_off = _va_to_file_offset(input_bytes, spec.site_va)
        current_site = input_bytes[site_off: site_off + len(spec.expected)]
        allowed = {spec.expected, spec.replacement, *spec.alternates}
        if current_site not in allowed and not force:
            raise RuntimeError(
                f"Patch-site bytes do not match expected signature for {spec.name}. "
                "Use --force only after manual verification."
            )

        patched[site_off: site_off + len(spec.expected)] = spec.replacement
        rows.append(
            {
                "name": spec.name,
                "site_va": f"0x{spec.site_va:08X}",
                "site_file_offset": f"0x{site_off:08X}",
                "site_before": current_site.hex(),
                "site_after": spec.replacement.hex(),
            }
        )

    # Write transfer-signing Stars source helper cave.
    signing_source_helper = _build_signing_stars_source_helper(
        cave_va=CAVE_SIGNING_SOURCE_HELPER_VA,
        stars_va=string_addrs["stars"],
    )
    if len(signing_source_helper) > CAVE_SIGNING_SOURCE_HELPER_SIZE:
        raise RuntimeError(
            f"Signing-source helper overflow ({len(signing_source_helper)} > {CAVE_SIGNING_SOURCE_HELPER_SIZE})"
        )
    signing_source_blob = signing_source_helper + (
        b"\x00" * (CAVE_SIGNING_SOURCE_HELPER_SIZE - len(signing_source_helper))
    )
    signing_source_off = _va_to_file_offset(input_bytes, CAVE_SIGNING_SOURCE_HELPER_VA)
    current_signing_source = input_bytes[
        signing_source_off: signing_source_off + CAVE_SIGNING_SOURCE_HELPER_SIZE
    ]
    signing_source_is_empty = current_signing_source in {
        b"\x00" * CAVE_SIGNING_SOURCE_HELPER_SIZE,
        signing_source_blob,
    }
    if (not force) and (not signing_source_is_empty):
        raise RuntimeError(
            "Signing-source helper cave bytes are not recognized. "
            "Use --force only after manual verification."
        )
    patched[signing_source_off: signing_source_off + CAVE_SIGNING_SOURCE_HELPER_SIZE] = signing_source_blob
    rows.append(
        {
            "name": "write_signing_source_stars_helper_cave",
            "site_va": f"0x{CAVE_SIGNING_SOURCE_HELPER_VA:08X}",
            "site_file_offset": f"0x{signing_source_off:08X}",
            "site_before": current_signing_source.hex(),
            "site_after": signing_source_blob.hex(),
            "bytes_written": CAVE_SIGNING_SOURCE_HELPER_SIZE,
        }
    )

    # Write player-record/history Stars fill helper cave.
    player_record_helper = _build_player_record_stars_fill_helper(
        cave_va=CAVE_PLAYER_RECORD_HELPER_VA,
    )
    if len(player_record_helper) > CAVE_PLAYER_RECORD_HELPER_SIZE:
        raise RuntimeError(
            f"Player-record helper overflow ({len(player_record_helper)} > {CAVE_PLAYER_RECORD_HELPER_SIZE})"
        )
    player_record_blob = player_record_helper + (
        b"\x90" * (CAVE_PLAYER_RECORD_HELPER_SIZE - len(player_record_helper))
    )
    player_record_off = _va_to_file_offset(input_bytes, CAVE_PLAYER_RECORD_HELPER_VA)
    current_player_record = input_bytes[
        player_record_off: player_record_off + CAVE_PLAYER_RECORD_HELPER_SIZE
    ]
    player_record_is_empty = current_player_record in {
        b"\x00" * CAVE_PLAYER_RECORD_HELPER_SIZE,
        b"\xCC" * CAVE_PLAYER_RECORD_HELPER_SIZE,
        player_record_blob,
    }
    if (not force) and (not player_record_is_empty):
        raise RuntimeError(
            "Player-record helper cave bytes are not recognized. "
            "Use --force only after manual verification."
        )
    patched[player_record_off: player_record_off + CAVE_PLAYER_RECORD_HELPER_SIZE] = player_record_blob
    rows.append(
        {
            "name": "write_player_record_stars_helper_cave",
            "site_va": f"0x{CAVE_PLAYER_RECORD_HELPER_VA:08X}",
            "site_file_offset": f"0x{player_record_off:08X}",
            "site_before": current_player_record.hex(),
            "site_after": player_record_blob.hex(),
            "bytes_written": CAVE_PLAYER_RECORD_HELPER_SIZE,
        }
    )

    # Write personal signing notice {S3}=Stars helper stages.
    signing_notice_stage0, signing_notice_default, signing_notice_common = _build_signing_notice_stages(
        stage0_va=CAVE_SIGNING_NOTICE_STAGE0_VA,
        default_va=CAVE_SIGNING_NOTICE_DEFAULT_VA,
        common_va=CAVE_SIGNING_NOTICE_COMMON_VA,
        stars_va=string_addrs["stars"],
        original_source_va=0x004B1F00,
        resume_va=0x004B31B1,
        force_stars=proof_force_signing_notice_stars,
    )
    signing_notice_specs = (
        (
            "write_signing_notice_stage0_cave",
            CAVE_SIGNING_NOTICE_STAGE0_VA,
            CAVE_SIGNING_NOTICE_STAGE0_SIZE,
            signing_notice_stage0,
        ),
        (
            "write_signing_notice_default_cave",
            CAVE_SIGNING_NOTICE_DEFAULT_VA,
            CAVE_SIGNING_NOTICE_DEFAULT_SIZE,
            signing_notice_default,
        ),
        (
            "write_signing_notice_common_cave",
            CAVE_SIGNING_NOTICE_COMMON_VA,
            CAVE_SIGNING_NOTICE_COMMON_SIZE,
            signing_notice_common,
        ),
    )
    for name, cave_va, cave_size, cave_code in signing_notice_specs:
        if len(cave_code) > cave_size:
            raise RuntimeError(f"{name} overflow ({len(cave_code)} > {cave_size})")
        cave_blob = cave_code + (b"\xCC" * (cave_size - len(cave_code)))
        cave_off = _va_to_file_offset(input_bytes, cave_va)
        current_cave = input_bytes[cave_off: cave_off + cave_size]
        if (not force) and current_cave not in {b"\xCC" * cave_size, cave_blob}:
            raise RuntimeError(f"{name} cave bytes are not recognized. Use --force only after manual verification.")
        patched[cave_off: cave_off + cave_size] = cave_blob
        rows.append(
            {
                "name": name,
                "site_va": f"0x{cave_va:08X}",
                "site_file_offset": f"0x{cave_off:08X}",
                "site_before": current_cave.hex(),
                "site_after": cave_blob.hex(),
                "bytes_written": cave_size,
            }
        )

    # Write formatter-local {S3} fallback stages for Valderrama's signing notice.
    formatter_s3_stage0, formatter_s3_stage1, formatter_s3_stage2 = _build_formatter_s3_valderrama_stages(
        stage0_va=CAVE_FORMATTER_S3_STAGE0_VA,
        stage1_va=CAVE_FORMATTER_S3_STAGE1_VA,
        stage2_va=CAVE_FORMATTER_S3_STAGE2_VA,
        stars_va=string_addrs["stars"],
        original_push_va=0x00499E62,
        original_skip_va=0x00499E70,
    )
    formatter_s3_specs = (
        ("write_formatter_s3_stage0_cave", CAVE_FORMATTER_S3_STAGE0_VA, CAVE_FORMATTER_S3_STAGE0_SIZE, formatter_s3_stage0),
        ("write_formatter_s3_stage1_cave", CAVE_FORMATTER_S3_STAGE1_VA, CAVE_FORMATTER_S3_STAGE1_SIZE, formatter_s3_stage1),
        ("write_formatter_s3_stage2_cave", CAVE_FORMATTER_S3_STAGE2_VA, CAVE_FORMATTER_S3_STAGE2_SIZE, formatter_s3_stage2),
    )
    for name, cave_va, cave_size, cave_code in formatter_s3_specs:
        if len(cave_code) > cave_size:
            raise RuntimeError(f"{name} overflow ({len(cave_code)} > {cave_size})")
        cave_blob = cave_code + (b"\xCC" * (cave_size - len(cave_code)))
        cave_off = _va_to_file_offset(input_bytes, cave_va)
        current_cave = input_bytes[cave_off: cave_off + cave_size]
        if (not force) and current_cave not in {b"\xCC" * cave_size, cave_blob}:
            raise RuntimeError(f"{name} cave bytes are not recognized. Use --force only after manual verification.")
        patched[cave_off: cave_off + cave_size] = cave_blob
        rows.append(
            {
                "name": name,
                "site_va": f"0x{cave_va:08X}",
                "site_file_offset": f"0x{cave_off:08X}",
                "site_before": current_cave.hex(),
                "site_after": cave_blob.hex(),
                "bytes_written": cave_size,
            }
        )

    # Write standard player-profile club-slot Stars helper stages.
    profile_club_stage0 = _build_profile_club_stars_stage0(
        stage0_va=CAVE_PROFILE_CLUB_STAGE0_VA,
        stage1_va=CAVE_PROFILE_CLUB_STAGE1_VA,
    )
    profile_club_stage1 = _build_profile_club_stars_stage1(
        stage1_va=CAVE_PROFILE_CLUB_STAGE1_VA,
        stars_va=string_addrs["stars"],
        resume_va=0x0043F235,
    )
    profile_club_stage0_off = _va_to_file_offset(input_bytes, CAVE_PROFILE_CLUB_STAGE0_VA)
    current_profile_club_stage0 = input_bytes[
        profile_club_stage0_off: profile_club_stage0_off + CAVE_PROFILE_CLUB_STAGE0_SIZE
    ]
    allowed_profile_club_stage0 = {
        b"\x90" * CAVE_PROFILE_CLUB_STAGE0_SIZE,
        profile_club_stage0,
    }
    if (not force) and (current_profile_club_stage0 not in allowed_profile_club_stage0):
        raise RuntimeError(
            "Profile-club stage0 cave bytes are not recognized. "
            "Use --force only after manual verification."
        )
    patched[
        profile_club_stage0_off: profile_club_stage0_off + CAVE_PROFILE_CLUB_STAGE0_SIZE
    ] = profile_club_stage0
    rows.append(
        {
            "name": "write_profile_club_stars_stage0_cave",
            "site_va": f"0x{CAVE_PROFILE_CLUB_STAGE0_VA:08X}",
            "site_file_offset": f"0x{profile_club_stage0_off:08X}",
            "site_before": current_profile_club_stage0.hex(),
            "site_after": profile_club_stage0.hex(),
            "bytes_written": CAVE_PROFILE_CLUB_STAGE0_SIZE,
        }
    )
    profile_club_stage1_off = _va_to_file_offset(input_bytes, CAVE_PROFILE_CLUB_STAGE1_VA)
    current_profile_club_stage1 = input_bytes[
        profile_club_stage1_off: profile_club_stage1_off + CAVE_PROFILE_CLUB_STAGE1_SIZE
    ]
    allowed_profile_club_stage1 = {
        b"\x90" * CAVE_PROFILE_CLUB_STAGE1_SIZE,
        profile_club_stage1,
    }
    if (not force) and (current_profile_club_stage1 not in allowed_profile_club_stage1):
        raise RuntimeError(
            "Profile-club stage1 cave bytes are not recognized. "
            "Use --force only after manual verification."
        )
    patched[
        profile_club_stage1_off: profile_club_stage1_off + CAVE_PROFILE_CLUB_STAGE1_SIZE
    ] = profile_club_stage1
    rows.append(
        {
            "name": "write_profile_club_stars_stage1_cave",
            "site_va": f"0x{CAVE_PROFILE_CLUB_STAGE1_VA:08X}",
            "site_file_offset": f"0x{profile_club_stage1_off:08X}",
            "site_before": current_profile_club_stage1.hex(),
            "site_after": profile_club_stage1.hex(),
            "bytes_written": CAVE_PROFILE_CLUB_STAGE1_SIZE,
        }
    )

    if proof_open_record:
        proof_specs = [
            {
                "name": "write_proof_record_stage0_cave",
                "va": CAVE_PROOF_RECORD_STAGE0_VA,
                "size": CAVE_PROOF_RECORD_STAGE0_SIZE,
                "pad": b"\xCC",
                "blob": _build_proof_record_stage(
                    cave_va=CAVE_PROOF_RECORD_STAGE0_VA,
                    target_va=0x0072F128,
                    value=0,
                    next_va=CAVE_PROOF_RECORD_STAGE1_VA,
                ),
                "empty_bytes": {
                    b"\x00" * CAVE_PROOF_RECORD_STAGE0_SIZE,
                    b"\xCC" * CAVE_PROOF_RECORD_STAGE0_SIZE,
                },
            },
            {
                "name": "write_proof_record_stage1_cave",
                "va": CAVE_PROOF_RECORD_STAGE1_VA,
                "size": CAVE_PROOF_RECORD_STAGE1_SIZE,
                "pad": b"\x90",
                "blob": _build_proof_record_stage_final(
                    cave_va=CAVE_PROOF_RECORD_STAGE1_VA,
                    target_va=0x0072F120,
                    value=1,
                    open_record_va=0x0043DD30,
                ),
                "empty_bytes": {
                    b"\x90" * CAVE_PROOF_RECORD_STAGE1_SIZE,
                    b"\xCC" * CAVE_PROOF_RECORD_STAGE1_SIZE,
                },
            },
        ]
        for spec in proof_specs:
            if len(spec["blob"]) > spec["size"]:
                raise RuntimeError(
                    f"{spec['name']} overflow ({len(spec['blob'])} > {spec['size']})"
                )
            blob = spec["blob"] + (spec["pad"] * (spec["size"] - len(spec["blob"])))
            off = _va_to_file_offset(input_bytes, spec["va"])
            current = input_bytes[off: off + spec["size"]]
            allowed = set(spec["empty_bytes"])
            allowed.add(blob)
            if (not force) and (current not in allowed):
                raise RuntimeError(
                    f"{spec['name']} bytes are not recognized. "
                    "Use --force only after manual verification."
                )
            patched[off: off + spec["size"]] = blob
            rows.append(
                {
                    "name": spec["name"],
                    "site_va": f"0x{spec['va']:08X}",
                    "site_file_offset": f"0x{off:08X}",
                    "site_before": current.hex(),
                    "site_after": blob.hex(),
                    "bytes_written": spec["size"],
                }
            )

    # Write secondary-chain null-guard stage caves near FUN_0064ce30.
    secondary_stage0 = _build_secondary_chain_guard_stage0(
        cave_va=SECONDARY_CHAIN_GUARD_STAGE0_VA,
        stage1_va=SECONDARY_CHAIN_GUARD_STAGE1_VA,
    )
    if len(secondary_stage0) > SECONDARY_CHAIN_GUARD_STAGE0_SIZE:
        raise RuntimeError(
            f"Secondary guard stage0 overflow ({len(secondary_stage0)} > {SECONDARY_CHAIN_GUARD_STAGE0_SIZE})"
        )
    secondary_stage0_blob = secondary_stage0 + (
        b"\x90" * (SECONDARY_CHAIN_GUARD_STAGE0_SIZE - len(secondary_stage0))
    )
    secondary_stage0_off = _va_to_file_offset(input_bytes, SECONDARY_CHAIN_GUARD_STAGE0_VA)
    current_secondary_stage0 = input_bytes[
        secondary_stage0_off: secondary_stage0_off + SECONDARY_CHAIN_GUARD_STAGE0_SIZE
    ]
    secondary_stage0_empty = current_secondary_stage0 == (b"\x90" * SECONDARY_CHAIN_GUARD_STAGE0_SIZE)
    if (not force) and (not secondary_stage0_empty) and (current_secondary_stage0 != secondary_stage0_blob):
        raise RuntimeError(
            "Secondary guard stage0 cave bytes are not recognized. "
            "Use --force only after manual verification."
        )
    patched[
        secondary_stage0_off: secondary_stage0_off + SECONDARY_CHAIN_GUARD_STAGE0_SIZE
    ] = secondary_stage0_blob
    rows.append(
        {
            "name": "write_secondary_chain_guard_stage0_cave",
            "site_va": f"0x{SECONDARY_CHAIN_GUARD_STAGE0_VA:08X}",
            "site_file_offset": f"0x{secondary_stage0_off:08X}",
            "site_before": current_secondary_stage0.hex(),
            "site_after": secondary_stage0_blob.hex(),
            "bytes_written": SECONDARY_CHAIN_GUARD_STAGE0_SIZE,
        }
    )

    secondary_stage1 = _build_secondary_chain_guard_stage1(
        cave_va=SECONDARY_CHAIN_GUARD_STAGE1_VA,
        stage2_va=SECONDARY_CHAIN_GUARD_STAGE2_VA,
    )
    if len(secondary_stage1) > SECONDARY_CHAIN_GUARD_STAGE1_SIZE:
        raise RuntimeError(
            f"Secondary guard stage1 overflow ({len(secondary_stage1)} > {SECONDARY_CHAIN_GUARD_STAGE1_SIZE})"
        )
    secondary_stage1_blob = secondary_stage1 + (
        b"\x90" * (SECONDARY_CHAIN_GUARD_STAGE1_SIZE - len(secondary_stage1))
    )
    secondary_stage1_off = _va_to_file_offset(input_bytes, SECONDARY_CHAIN_GUARD_STAGE1_VA)
    current_secondary_stage1 = input_bytes[
        secondary_stage1_off: secondary_stage1_off + SECONDARY_CHAIN_GUARD_STAGE1_SIZE
    ]
    secondary_stage1_empty = current_secondary_stage1 == (b"\x90" * SECONDARY_CHAIN_GUARD_STAGE1_SIZE)
    if (not force) and (not secondary_stage1_empty) and (current_secondary_stage1 != secondary_stage1_blob):
        raise RuntimeError(
            "Secondary guard stage1 cave bytes are not recognized. "
            "Use --force only after manual verification."
        )
    patched[
        secondary_stage1_off: secondary_stage1_off + SECONDARY_CHAIN_GUARD_STAGE1_SIZE
    ] = secondary_stage1_blob
    rows.append(
        {
            "name": "write_secondary_chain_guard_stage1_cave",
            "site_va": f"0x{SECONDARY_CHAIN_GUARD_STAGE1_VA:08X}",
            "site_file_offset": f"0x{secondary_stage1_off:08X}",
            "site_before": current_secondary_stage1.hex(),
            "site_after": secondary_stage1_blob.hex(),
            "bytes_written": SECONDARY_CHAIN_GUARD_STAGE1_SIZE,
        }
    )

    secondary_stage2 = _build_secondary_chain_guard_stage2(
        cave_va=SECONDARY_CHAIN_GUARD_STAGE2_VA,
        resume_va=0x0064CFDA,
    )
    if len(secondary_stage2) > SECONDARY_CHAIN_GUARD_STAGE2_SIZE:
        raise RuntimeError(
            f"Secondary guard stage2 overflow ({len(secondary_stage2)} > {SECONDARY_CHAIN_GUARD_STAGE2_SIZE})"
        )
    secondary_stage2_blob = secondary_stage2 + (
        b"\x90" * (SECONDARY_CHAIN_GUARD_STAGE2_SIZE - len(secondary_stage2))
    )
    secondary_stage2_off = _va_to_file_offset(input_bytes, SECONDARY_CHAIN_GUARD_STAGE2_VA)
    current_secondary_stage2 = input_bytes[
        secondary_stage2_off: secondary_stage2_off + SECONDARY_CHAIN_GUARD_STAGE2_SIZE
    ]
    secondary_stage2_empty = current_secondary_stage2 == (b"\x90" * SECONDARY_CHAIN_GUARD_STAGE2_SIZE)
    secondary_stage2_legacy = bytes.fromhex("ff5058e966ffffff90")
    if (
        (not force)
        and (not secondary_stage2_empty)
        and (current_secondary_stage2 != secondary_stage2_blob)
        and (current_secondary_stage2 != secondary_stage2_legacy)
    ):
        raise RuntimeError(
            "Secondary guard stage2 cave bytes are not recognized. "
            "Use --force only after manual verification."
        )
    patched[
        secondary_stage2_off: secondary_stage2_off + SECONDARY_CHAIN_GUARD_STAGE2_SIZE
    ] = secondary_stage2_blob
    rows.append(
        {
            "name": "write_secondary_chain_guard_stage2_cave",
            "site_va": f"0x{SECONDARY_CHAIN_GUARD_STAGE2_VA:08X}",
            "site_file_offset": f"0x{secondary_stage2_off:08X}",
            "site_before": current_secondary_stage2.hex(),
            "site_after": secondary_stage2_blob.hex(),
            "bytes_written": SECONDARY_CHAIN_GUARD_STAGE2_SIZE,
        }
    )

    # Write null-guard cave stub.
    null_stub = _build_null_text_guard_stub(
        cave_va=CAVE_NULL_GUARD_VA,
        resume_va=0x0066F20A,
        fallback_text_va=string_addrs["empty"],
    )
    prev_null_stub_unknown = _build_null_text_guard_stub(
        cave_va=CAVE_NULL_GUARD_VA,
        resume_va=0x0066F20A,
        fallback_text_va=string_addrs["unknown"],
    )
    old_null_stub = _build_old_null_guard_stub(
        cave_va=CAVE_NULL_GUARD_VA,
        resume_va=0x0066F20A,
        null_target_va=0x0066F243,
    )

    null_off = _va_to_file_offset(input_bytes, CAVE_NULL_GUARD_VA)
    current_null = input_bytes[null_off: null_off + len(null_stub)]
    old_prefix_ok = current_null.startswith(old_null_stub) and all(
        b == 0 for b in current_null[len(old_null_stub):]
    )

    allowed_null = {b"\x00" * len(null_stub), null_stub, prev_null_stub_unknown}
    if (current_null not in allowed_null) and (not old_prefix_ok) and (not force):
        raise RuntimeError(
            "Null-guard cave bytes are not empty/known. "
            "Use --force only after manual verification."
        )

    patched[null_off: null_off + len(null_stub)] = null_stub
    rows.append(
        {
            "name": "write_null_guard_cave",
            "site_va": f"0x{CAVE_NULL_GUARD_VA:08X}",
            "site_file_offset": f"0x{null_off:08X}",
            "site_before": current_null.hex(),
            "site_after": null_stub.hex(),
            "bytes_written": len(null_stub),
        }
    )

    output_bytes = bytes(patched)

    target_out: Path
    if in_place:
        target_out = input_exe
    else:
        target_out = output_exe or DEFAULT_OUTPUT_EXE

    backup_path: Path | None = None
    if not dry_run:
        target_out.parent.mkdir(parents=True, exist_ok=True)
        if in_place and make_backup:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = target_out.with_name(f"{target_out.name}.bak_valderrama_upstream_{stamp}")
            shutil.copy2(target_out, backup_path)
        target_out.write_bytes(output_bytes)

    return {
        "input_exe": str(input_exe),
        "output_exe": str(target_out),
        "backup_exe": str(backup_path) if backup_path else None,
        "dry_run": bool(dry_run),
        "patch_count": len(rows),
        "patches": rows,
        "addresses": {
            "bundle_base": f"0x{CAVE_BUNDLE_BASE_VA:08X}",
            "bundle_size": CAVE_BUNDLE_SIZE,
            "search_text_helper": f"0x{search_text_helper_va:08X}",
            "lookup_helper": f"0x{lookup_helper_va:08X}",
            "signing_source_helper": f"0x{signing_source_helper_va:08X}",
            "player_record_helper": f"0x{player_record_helper_va:08X}",
            "profile_club_stage0": f"0x{CAVE_PROFILE_CLUB_STAGE0_VA:08X}",
            "profile_club_stage1": f"0x{CAVE_PROFILE_CLUB_STAGE1_VA:08X}",
            "signing_notice_stage0": f"0x{CAVE_SIGNING_NOTICE_STAGE0_VA:08X}",
            "signing_notice_default": f"0x{CAVE_SIGNING_NOTICE_DEFAULT_VA:08X}",
            "signing_notice_common": f"0x{CAVE_SIGNING_NOTICE_COMMON_VA:08X}",
            "formatter_s3_stage0": f"0x{CAVE_FORMATTER_S3_STAGE0_VA:08X}",
            "formatter_s3_stage1": f"0x{CAVE_FORMATTER_S3_STAGE1_VA:08X}",
            "formatter_s3_stage2": f"0x{CAVE_FORMATTER_S3_STAGE2_VA:08X}",
            "null_guard": f"0x{CAVE_NULL_GUARD_VA:08X}",
            "proof_record_stage0": f"0x{CAVE_PROOF_RECORD_STAGE0_VA:08X}",
            "proof_record_stage1": f"0x{CAVE_PROOF_RECORD_STAGE1_VA:08X}",
            "secondary_chain_guard_site": f"0x{SECONDARY_CHAIN_GUARD_SITE_VA:08X}",
            "secondary_chain_guard_stage0": f"0x{SECONDARY_CHAIN_GUARD_STAGE0_VA:08X}",
            "secondary_chain_guard_stage1": f"0x{SECONDARY_CHAIN_GUARD_STAGE1_VA:08X}",
            "secondary_chain_guard_stage2": f"0x{SECONDARY_CHAIN_GUARD_STAGE2_VA:08X}",
            "empty": f"0x{string_addrs['empty']:08X}",
            "stars": f"0x{string_addrs['stars']:08X}",
            "free": f"0x{string_addrs['free']:08X}",
            "unknown": f"0x{string_addrs['unknown']:08X}",
        },
        "sha256": {
            "input": _sha256(input_bytes),
            "output": _sha256(output_bytes),
        },
        "notes": [
            "MANAGPRE-only patch. No database edits.",
            "FUN_0066f1f0 keeps the proven null text-pointer guard (NULL -> empty string).",
            "FUN_0064ce30 now guards the secondary object-chain virtual call when EBP is NULL.",
            "FUN_00474870 pre-sprintf path now force-normalizes Search Player by Name team text by team_id.",
            "FUN_004b5c20 tail now rejects invalid candidate name pointers before fallback mapping.",
            "Transfer search windows reuse FUN_004B5C20 fallback and now receive the fake Stars team record.",
            "Fake Stars/Free/Unknown team records now populate both +0x04 and +0x08 text slots; FUN_004a5590 transfer-event creation reads +0x08 for the source-club string.",
            "Special transfer-signing 9900/Stars source branch now backfills empty text as 'Stars'.",
            "Player-record/history post-lookup gate now backfills the 9900/Stars row as 'Stars'.",
            "Standard player-profile club slot now backfills empty 9900/Stars text as 'Stars'.",
            "Personal signing notice event 0x453 now fills {S3} with 'Stars' for the special 9900/Stars player path.",
            "Formatter {S3} now backfills 'Stars' only for null-S3 Valderrama signing-notice renders.",
            "Global formatter hooks remain restored to original bytes; this patch stays caller-local.",
            "Legacy experimental upstream list trampolines are reverted to original bytes.",
            *(
                [
                    "Proof-only mode repoints the offer-pane constructor into FUN_0043DD30 to open the real player record.",
                ]
                if proof_open_record
                else []
            ),
            *(
                [
                    "Proof-only mode forces event 0x453 {S3} to 'Stars' at FUN_004b2fc0.",
                ]
                if proof_force_signing_notice_stars
                else []
            ),
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Patch MANAGPRE.EXE with Valderrama-safe null guard + source-club fallbacks"
    )
    parser.add_argument("--input-exe", default=str(DEFAULT_INPUT_EXE), help="Path to source MANAGPRE.EXE")
    parser.add_argument(
        "--output-exe",
        default=str(DEFAULT_OUTPUT_EXE),
        help="Output path (ignored with --in-place)",
    )
    parser.add_argument("--in-place", action="store_true", help="Patch input file in place")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report only")
    parser.add_argument("--force", action="store_true", help="Ignore signature checks")
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Disable auto-backup when using --in-place",
    )
    parser.add_argument("--json-output", help="Optional report output path")
    parser.add_argument(
        "--proof-open-record",
        action="store_true",
        help="Proof-only: route offer-modal command 0x583 into the standard player record screen",
    )
    parser.add_argument(
        "--proof-force-signing-notice-stars",
        action="store_true",
        help="Proof-only: force event 0x453 {S3} to Stars at FUN_004b2fc0",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_exe = Path(args.input_exe)
    output_exe = None if args.in_place else Path(args.output_exe)
    report = apply_patch(
        input_exe=input_exe,
        output_exe=output_exe,
        in_place=bool(args.in_place),
        dry_run=bool(args.dry_run),
        force=bool(args.force),
        make_backup=not bool(args.no_backup),
        proof_open_record=bool(args.proof_open_record),
        proof_force_signing_notice_stars=bool(args.proof_force_signing_notice_stars),
    )
    text = json.dumps(report, indent=2)
    if args.json_output:
        out = Path(args.json_output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
