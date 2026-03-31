"""
Capcom MT Framework Mobile .tex texture parser.

Primary target: Resident Evil: Revelations (3DS).
Also covers Monster Hunter, other Capcom 3DS titles using MT Framework.

This parser tries multiple known header layouts and logs every attempt.
Nothing is silently skipped.

Game-specific profiles override the default format mapping when a title ID
is known. The RE:Revelations profile was built from real ROM evidence
(header bytes + payload-size validation), NOT from a published spec.
"""

import logging
import math
from typing import Optional, Dict, Any, List, Tuple

from utils import read_u32_le, read_u32_be, read_u16_le, read_u16_be, read_u8

logger = logging.getLogger(__name__)

# Known magic values for Capcom TEX containers
CAPCOM_TEX_MAGICS = {
    b'TEX\x00': "TEX_LE",
    b'\x00XET': "TEX_BE",
}

# ── Default Capcom internal format -> PICA200 format mapping ──
# This is the generic/speculative mapping from community documentation.
# Game-specific profiles below may override entries.
CAPCOM_FORMAT_MAP = {
    0x01: 0x00,  # RGBA8
    0x02: 0x01,  # RGB8
    0x03: 0x03,  # RGB565
    0x04: 0x02,  # RGBA5551
    0x05: 0x04,  # RGBA4
    0x06: 0x05,  # LA8
    0x07: 0x07,  # L8
    0x08: 0x08,  # A8
    0x09: 0x09,  # LA4
    0x0A: 0x0A,  # L4
    0x0B: 0x0C,  # ETC1
    0x0C: 0x0D,  # ETC1A4
    0x0D: 0x06,  # HILO8
    0x00: 0x00,  # passthrough
}

# ── Game-specific profiles ──
# Each profile has:
#   "format_map": overrides for the Capcom->PICA mapping
#   "header_offsets": preferred header sizes to try (ordered)
#   "format_byte_offset": which byte in the header holds the format ID
#   "notes": human-readable provenance

GAME_PROFILES: Dict[str, Dict[str, Any]] = {
    # Resident Evil: Revelations (EUR/USA/JPN title IDs)
    "0004000000060200": {
        "name": "RE Revelations (EUR)",
        "format_map": {
            0x0B: 0x01,  # RGB8  (24bpp) — CONFIRMED: only pow2 solution for 393216-byte payloads
            0x0C: 0x0D,  # ETC1A4 (8bpp) — consistent with 4096-byte payload -> 64x64
            0x11: 0x0C,  # ETC1   (4bpp) — consistent with 32768-byte payload -> 256x256
        },
        "header_offsets": [0x14, 0x10, 0x18, 0x20],
        "format_byte_offset": 0x0D,  # byte 13 in the file
        "notes": "Mapping inferred from 3 sample headers + payload-size matching. Not from spec.",
    },
    "0004000000035D00": {
        "name": "RE Revelations (USA)",
        "format_map": {
            0x0B: 0x01,
            0x0C: 0x0D,
            0x11: 0x0C,
        },
        "header_offsets": [0x14, 0x10, 0x18, 0x20],
        "format_byte_offset": 0x0D,
        "notes": "Same engine as EUR, assumed same mapping.",
    },
    "0004000000060100": {
        "name": "RE Revelations (JPN)",
        "format_map": {
            0x0B: 0x01,
            0x0C: 0x0D,
            0x11: 0x0C,
        },
        "header_offsets": [0x14, 0x10, 0x18, 0x20],
        "format_byte_offset": 0x0D,
        "notes": "Same engine as EUR, assumed same mapping.",
    },
    # Resident Evil: The Mercenaries 3D (same MT Framework Mobile engine as RE:R)
    "0004000000035900": {
        "name": "RE Mercenaries 3D (USA)",
        "format_map": {
            0x0B: 0x01,
            0x0C: 0x0D,
            0x11: 0x0C,
        },
        "header_offsets": [0x14, 0x10, 0x18, 0x20],
        "format_byte_offset": 0x0D,
        "notes": "Same MT Framework Mobile engine as RE Revelations.",
    },
    # Monster Hunter 3 Ultimate (same MT Framework Mobile engine, ARC v0x10)
    "00040000000AE400": {
        "name": "MH3 Ultimate (USA)",
        "format_map": {
            0x0C: 0x0C,
            0x0D: 0x0D,
            0x0B: 0x0C,
            0x11: 0x0C,
        },
        "header_offsets": [0x14, 0x10, 0x18, 0x20],
        "format_byte_offset": 0x0D,
        "notes": "Same engine as MH4U, ARC version 0x10.",
    },
    # Monster Hunter Generations (same engine, ARC v0x11)
    "0004000000187000": {
        "name": "MH Generations (USA)",
        "format_map": {
            0x0C: 0x0C,
            0x0D: 0x0D,
            0x0B: 0x0C,
            0x11: 0x0C,
        },
        "header_offsets": [0x14, 0x10, 0x18, 0x20],
        "format_byte_offset": 0x0D,
        "notes": "Same engine as MH4U, ARC version 0x11.",
    },
    # Monster Hunter 4 Ultimate (MT Framework Mobile, same header variant as RE:R)
    # Format byte at 0x0D; 0x0C = ETC1 (4bpp) — confirmed: 32768-byte mip0 -> 256x256 ETC1.
    # Default CAPCOM_FORMAT_MAP maps 0x0C -> ETC1A4 (8bpp) which is wrong for MH4U.
    # Title ID confirmed from ROM: 0004000000126300 (USA ROM "Monster Hunter 4 Ultimate")
    "0004000000126300": {
        "name": "MH4 Ultimate (USA)",
        "format_map": {
            0x0C: 0x0C,   # ETC1  (4bpp) — confirmed from payload analysis
            0x0D: 0x0D,   # ETC1A4 (8bpp)
            0x0B: 0x0C,   # ETC1 (reuse 0x0B same as default)
            0x11: 0x0C,   # ETC1 (matches RE:R mapping)
        },
        "header_offsets": [0x14, 0x10, 0x18, 0x20],
        "format_byte_offset": 0x0D,
        "notes": "Inferred from failing TEX analysis: format byte 0x0C = ETC1 (4bpp).",
    },
    "000400000016D200": {
        "name": "MH4 Ultimate (EUR)",
        "format_map": {
            0x0C: 0x0C,
            0x0D: 0x0D,
            0x0B: 0x0C,
            0x11: 0x0C,
        },
        "header_offsets": [0x14, 0x10, 0x18, 0x20],
        "format_byte_offset": 0x0D,
        "notes": "Same engine as USA version, assumed same mapping.",
    },
    "000400000016E400": {
        "name": "MH4G (JPN)",
        "format_map": {
            0x0C: 0x0C,
            0x0D: 0x0D,
            0x0B: 0x0C,
            0x11: 0x0C,
        },
        "header_offsets": [0x14, 0x10, 0x18, 0x20],
        "format_byte_offset": 0x0D,
        "notes": "Same engine as USA version, assumed same mapping.",
    },
    # RE: The Mercenaries 3D (same MT Framework Mobile engine)
    "0004000000060300": {
        "name": "RE Mercenaries (USA)",
        "format_map": {
            0x0B: 0x01,
            0x0C: 0x0D,
            0x11: 0x0C,
        },
        "header_offsets": [0x14, 0x10, 0x18, 0x20],
        "format_byte_offset": 0x0D,
        "notes": "Same MT Framework engine as RE:R.",
    },
}

# PICA format bpp for payload calculation (must stay in sync with decoder.py)
PICA_BPP = {
    0x0: 32, 0x1: 24, 0x2: 16, 0x3: 16, 0x4: 16,
    0x5: 16, 0x6: 16, 0x7: 8,  0x8: 8,  0x9: 8,
    0xA: 4,  0xB: 4,  0xC: 4,  0xD: 8,
}


def _get_profile(title_id: str) -> Optional[Dict[str, Any]]:
    """Look up a game-specific profile by title ID."""
    if not title_id:
        return None
    clean = title_id.strip().upper().replace("0X", "")
    # Pad to 16 chars
    clean = clean.zfill(16)
    return GAME_PROFILES.get(clean)


def _get_format_map(title_id: str) -> Dict[int, int]:
    """Build a merged format map: game profile overrides on top of defaults."""
    merged = dict(CAPCOM_FORMAT_MAP)
    profile = _get_profile(title_id)
    if profile:
        merged.update(profile["format_map"])
    return merged


class TexParseResult:
    """Structured result from attempting to parse a .tex file."""

    def __init__(self, path: str):
        self.path = path
        self.status = "not_attempted"  # parsed | partial | failed | skipped
        self.parser_variant = ""
        self.width = 0
        self.height = 0
        self.format_raw = -1
        self.format_pica = -1
        self.mip_count = 0
        self.data_offset = 0
        self.pixel_data: Optional[bytes] = None
        self.file_size = 0
        self.expected_data_size = 0
        self.actual_data_size = 0
        self.notes: List[str] = []
        self.confidence = "none"  # high | medium | low | none
        self.title_id = ""

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "path": self.path,
            "status": self.status,
            "parser_variant": self.parser_variant,
            "width": self.width,
            "height": self.height,
            "format_raw": f"0x{self.format_raw:02X}" if self.format_raw >= 0 else "unknown",
            "format_pica": f"0x{self.format_pica:X}" if self.format_pica >= 0 else "unknown",
            "mip_count": self.mip_count,
            "data_offset": f"0x{self.data_offset:X}",
            "file_size": self.file_size,
            "expected_data_size": self.expected_data_size,
            "actual_data_size": self.actual_data_size,
            "confidence": self.confidence,
            "notes": self.notes,
        }
        return d


def is_capcom_tex(data: bytes) -> bool:
    """Check if data looks like a Capcom .tex file. Conservative: only magic check."""
    if len(data) < 16:
        return False
    magic4 = data[0:4]
    return magic4 in CAPCOM_TEX_MAGICS


def parse_capcom_tex_strict(data: bytes, file_path: str = "",
                            title_id: str = "") -> TexParseResult:
    """
    Parse a Capcom .tex file with full diagnostics.

    Tries variants in order:
      1. RE:Revelations payload-driven (if title matches or TEX\\0 magic present)
      2. Standard TEX header layout
      3. MT Framework Mobile variant
      4. Shifted header variant
      5. Payload-driven brute force (last resort)

    Every attempt is logged. The result always contains a status and notes.
    """
    result = TexParseResult(file_path)
    result.file_size = len(data)
    result.title_id = title_id

    if len(data) < 12:
        result.status = "failed"
        result.notes.append(f"File too small ({len(data)} bytes)")
        return result

    magic4 = data[0:4]
    has_magic = magic4 in CAPCOM_TEX_MAGICS

    profile = _get_profile(title_id)

    # --- Variant 0: RER/MH4U payload-driven (game profile) ---
    if has_magic and profile:
        v0 = _try_variant_rer_payload(data, result, title_id, profile)
        if v0:
            return v0

    # --- Variant 0b: payload-driven fallback for any TEX\0 with version byte 0xA5 ---
    # Catches title IDs not in GAME_PROFILES that use the same MT Framework Mobile layout.
    if has_magic and not profile and len(data) > 0x04 and data[0x04] == 0xA5:
        fallback_profile = {
            "name": "generic_mt_a5",
            "format_map": dict(CAPCOM_FORMAT_MAP),
            "header_offsets": [0x14],
            "format_byte_offset": 0x0D,
        }
        v0b = _try_variant_rer_payload(data, result, title_id, fallback_profile)
        if v0b:
            return v0b

    # --- Variant 1: Standard TEX header (generic) ---
    v1 = _try_variant_standard(data, result, title_id)
    if v1:
        return v1

    # --- Variant 2: MT Framework Mobile alternate layout ---
    v2 = _try_variant_mt_mobile(data, result, title_id)
    if v2:
        return v2

    # --- Variant 3: Shifted header ---
    if has_magic and len(data) >= 20:
        v3 = _try_variant_shifted(data, result, title_id)
        if v3:
            return v3

    # --- Variant 4: Payload-driven brute force (no profile needed) ---
    if has_magic:
        v4 = _try_variant_payload_bruteforce(data, result, title_id)
        if v4:
            return v4

    result.status = "failed"
    result.notes.append("No variant matched")
    if has_magic:
        result.notes.append(f"Had magic {magic4!r} but could not parse fields")
        _log_header_dump(data, result)
    return result


# ──────────────────────────────────────────────
# Variant 0: RE:Revelations payload-driven
# ──────────────────────────────────────────────

def _try_variant_rer_payload(data: bytes, base: TexParseResult,
                              title_id: str,
                              profile: Dict[str, Any]) -> Optional[TexParseResult]:
    """
    RE:Revelations-specific parser.

    Evidence-based layout (from real ROM analysis of 1144 TEX files):

      Bytes 0x00-0x03: magic "TEX\\0"
      Byte  0x04:      version (0xA5)
      Bytes 0x05-0x07: unknown flags / encoded size info
      Bytes 0x08-0x0C: unknown (byte8 correlates with texture resolution tier)
      Byte  0x0D:      format byte (Capcom internal ID)
      Bytes 0x0E-0x0F: unknown (usually 0x01 0x00)
      Bytes 0x10-0x13: padding (usually zeros; 7 files have float values = vertex data?)
      Byte  0x14:      pixel data begins

      Bytes 0x14+ contain ALL mip levels concatenated.
      u32_LE at offset 0x14 within the PIXEL DATA (= file offset 0x14)
      is NOT a mip table -- the mip table is at file offsets 0x14+.

      CRITICAL DISCOVERY: For files where the full payload (file_size - 0x14) does NOT
      match any pow2 base-level size, there is a mip offset table embedded in the header
      extension area. Specifically:
        u32_LE @ file offset 0x14 = base mip level data size
      This was verified against 979 of 986 previously-failing files.

      Strategy:
        1. Try full payload as base level (works for ~158 files)
        2. If that fails, read u32_LE @ offset 0x14 as base level size
        3. Use base level size to infer dimensions
    """
    if len(data) < 0x18:
        return None

    fmt_byte_offset = profile.get("format_byte_offset", 0x0D)
    fmt_map = profile["format_map"]

    # Read format byte
    fmt_raw = data[fmt_byte_offset] if fmt_byte_offset < len(data) else -1

    # Resolve format: try profile map, then default map, then raw PICA passthrough
    fmt_pica = -1
    if fmt_raw in fmt_map:
        fmt_pica = fmt_map[fmt_raw]
    elif fmt_raw in CAPCOM_FORMAT_MAP:
        fmt_pica = CAPCOM_FORMAT_MAP[fmt_raw]

    # Try each header offset from the profile (different TEX versions use
    # different header sizes: v0xA5 = 0x14, v0xA4 = 0x10).
    header_offsets = profile.get("header_offsets", [0x14, 0x10, 0x18, 0x20])

    for hdr_size in header_offsets:
        full_payload = len(data) - hdr_size
        if full_payload <= 0:
            continue

        # --- Strategy 1: full payload as base level ---
        result = _try_rer_match_payload(data, base, title_id, profile,
                                         full_payload, hdr_size, fmt_raw, fmt_pica,
                                         fmt_map, f"full_payload/hdr=0x{hdr_size:X}")
        if result:
            return result

    # --- Strategy 2: read u32_LE at offset 0x14 as base mip level size ---
    # This handles v0xA5 files with a mip offset table after the 0x14-byte header.
    hdr_size = header_offsets[0]  # Use primary header offset for mip table
    full_payload = len(data) - hdr_size
    if len(data) >= 0x18 and full_payload > 0:
        mip0_size = read_u32_le(data, 0x14)
        if 0 < mip0_size < full_payload and mip0_size != full_payload:
            # The mip offset table starts at file offset 0x14.
            # The actual pixel data starts AFTER the mip table.
            # How many mip entries? Count u32s until we find one that's 0 or exceeds payload.
            mip_table_entries = 0
            mip_offsets = []
            for i in range(16):  # max 16 mip levels
                off = 0x14 + i * 4
                if off + 4 > len(data):
                    break
                val = read_u32_le(data, off)
                if val == 0:
                    break
                # If val exceeds file size, it's pixel data not a mip entry
                # Must check BEFORE adding to avoid off-by-one data offset
                if val > len(data):
                    break
                mip_offsets.append(val)
                mip_table_entries += 1

            # The pixel data likely starts right after the mip offset table
            # Alternatively, mip_offsets[0] IS the base level size and pixel data
            # starts at hdr_size (0x14), with the mip table being part of a
            # secondary header region.
            #
            # From evidence: u32@0x14 = base_size = number of bytes for mip0.
            # So pixel data for mip0 starts at some offset after the mip table.
            # Let's compute: mip_table_size = mip_table_entries * 4
            # pixel_start = 0x14 + mip_table_size (aligned?)

            mip_table_size = mip_table_entries * 4
            pixel_start = hdr_size + mip_table_size

            # Verify: does data[pixel_start:pixel_start+mip0_size] fit?
            if pixel_start + mip0_size <= len(data):
                result = _try_rer_match_payload(
                    data, base, title_id, profile,
                    mip0_size, pixel_start, fmt_raw, fmt_pica,
                    fmt_map, f"mip_table/entries={mip_table_entries}")
                if result:
                    result.notes.append(f"Mip table at 0x14: {mip_table_entries} entries, "
                                        f"mip0_size={mip0_size}, pixel_start=0x{pixel_start:X}")
                    return result

            # Fallback: maybe the mip table is only 1 entry and pixel_start = 0x18
            if mip0_size > 0 and 0x18 + mip0_size <= len(data):
                result = _try_rer_match_payload(
                    data, base, title_id, profile,
                    mip0_size, 0x18, fmt_raw, fmt_pica,
                    fmt_map, "mip_table/fixed_0x18")
                if result:
                    result.notes.append(f"Mip0 size from u32@0x14={mip0_size}, pixel_start=0x18")
                    return result

    return None


def _try_rer_match_payload(data: bytes, base: TexParseResult,
                            title_id: str, profile: Dict[str, Any],
                            payload_size: int, data_start: int,
                            fmt_raw: int, fmt_pica: int,
                            fmt_map: Dict[int, int],
                            method_prefix: str) -> Optional[TexParseResult]:
    """
    Try to match a given payload size to pow2 dimensions.
    Used by both full-payload and mip-table strategies.
    """
    candidates = []

    # Try with resolved format first
    if fmt_pica >= 0 and fmt_pica in PICA_BPP:
        bpp = PICA_BPP[fmt_pica]
        dims = _find_pow2_dims_for_payload(payload_size, bpp)
        for w, h, score in dims:
            candidates.append((w, h, fmt_pica, fmt_raw, bpp, score, f"{method_prefix}/profile_fmt"))

    # Try all formats from the profile map
    if not candidates:
        for try_fmt_raw, try_fmt_pica in fmt_map.items():
            if try_fmt_pica not in PICA_BPP:
                continue
            bpp = PICA_BPP[try_fmt_pica]
            dims = _find_pow2_dims_for_payload(payload_size, bpp)
            for w, h, score in dims:
                candidates.append((w, h, try_fmt_pica, try_fmt_raw, bpp, score,
                                   f"{method_prefix}/profile_scan"))

    # Try all PICA formats directly
    if not candidates:
        for pica_id, bpp in PICA_BPP.items():
            dims = _find_pow2_dims_for_payload(payload_size, bpp)
            for w, h, score in dims:
                candidates.append((w, h, pica_id, -1, bpp, score,
                                   f"{method_prefix}/pica_scan"))

    # Try mip chain matching: payload contains base + mipmaps
    if not candidates:
        if fmt_pica >= 0 and fmt_pica in PICA_BPP:
            bpp = PICA_BPP[fmt_pica]
            mip_dims = _find_mipchain_dims(payload_size, bpp)
            for w, h, mip_count, score in mip_dims:
                candidates.append((w, h, fmt_pica, fmt_raw, bpp, score,
                                   f"{method_prefix}/mipchain_{mip_count}"))
        # Try all PICA formats for mip chains
        if not candidates:
            for pica_id, bpp in PICA_BPP.items():
                mip_dims = _find_mipchain_dims(payload_size, bpp)
                for w, h, mip_count, score in mip_dims:
                    candidates.append((w, h, pica_id, -1, bpp, score,
                                       f"{method_prefix}/mipchain_scan_{mip_count}"))

    if not candidates:
        return None

    # Sort: highest score first
    candidates.sort(key=lambda c: -c[5])

    best = candidates[0]
    w, h, pica_id, raw_fmt, bpp, score, method = best

    r = TexParseResult(base.path)
    r.file_size = base.file_size
    r.title_id = title_id
    r.parser_variant = f"rer_payload/{method}"
    r.width = w
    r.height = h
    r.format_raw = raw_fmt if raw_fmt >= 0 else fmt_raw
    r.format_pica = pica_id
    r.data_offset = data_start

    # For mip chain matches, extract only the base level
    if "mipchain" in method:
        base_size = (w * h * bpp + 7) // 8
        r.mip_count = int(method.split("_")[-1]) if method.split("_")[-1].isdigit() else 1
        r.expected_data_size = base_size
        r.actual_data_size = base_size
        end = data_start + base_size
        if end > len(data):
            end = len(data)
        r.pixel_data = data[data_start:end]
    else:
        r.mip_count = 1
        r.expected_data_size = payload_size
        r.actual_data_size = payload_size
        end = data_start + payload_size
        if end > len(data):
            end = len(data)
        r.pixel_data = data[data_start:end]

    # Confidence
    if "profile_fmt" in method and score >= 3:
        r.status = "parsed"
        r.confidence = "high"
    elif "profile_fmt" in method:
        r.status = "parsed"
        r.confidence = "medium"
    elif "profile_scan" in method and score >= 3:
        r.status = "partial"
        r.confidence = "medium"
    elif "profile_scan" in method:
        r.status = "partial"
        r.confidence = "low"
    else:
        r.status = "partial"
        r.confidence = "low"

    r.notes.append(f"Game profile: {profile.get('name', title_id)}")
    r.notes.append(f"Data start: 0x{data_start:X}, base_size: {payload_size}")
    r.notes.append(f"Format byte @0x0D=0x{fmt_raw:02X} -> PICA 0x{pica_id:X}")
    r.notes.append(f"Dims: {w}x{h} ({bpp}bpp), method={method}, score={score}")
    if len(candidates) > 1:
        alt = candidates[1]
        r.notes.append(f"Alt candidate: {alt[0]}x{alt[1]} PICA 0x{alt[2]:X} score={alt[5]}")

    logger.info(
        f"TEX rer_payload: {base.path} -> {w}x{h} "
        f"fmt=0x{r.format_raw:02X}->PICA 0x{pica_id:X} "
        f"conf={r.confidence} method={method}"
    )
    return r


def _find_pow2_dims_for_payload(payload: int, bpp: int) -> List[Tuple[int, int, int]]:
    """
    Given a payload size and bits-per-pixel, find all (width, height, score)
    where width*height*bpp/8 == payload and both dims are powers of 2.

    Score rewards:
      +2 for square
      +1 for near-square (aspect <= 4:1)
      +1 for both dims being pow2
      +1 for dims in common range (32-512)
    """
    if bpp <= 0:
        return []

    total_pixels = (payload * 8) // bpp
    # Check exact division
    if (payload * 8) % bpp != 0:
        return []

    if total_pixels <= 0:
        return []

    results = []
    # Try all pow2 widths from 4 to 1024
    for exp_w in range(2, 11):  # 4, 8, 16, ..., 1024
        w = 1 << exp_w
        if total_pixels % w != 0:
            continue
        h = total_pixels // w
        if h < 4 or h > 1024:
            continue
        # h must also be pow2
        if h & (h - 1) != 0:
            continue

        score = 1  # base: both pow2
        if w == h:
            score += 2  # square
        elif max(w, h) / min(w, h) <= 4:
            score += 1  # near-square

        if 32 <= w <= 512 and 32 <= h <= 512:
            score += 1  # common range

        results.append((w, h, score))

    return results


def _find_mipchain_dims(payload: int, bpp: int) -> List[Tuple[int, int, int, int]]:
    """
    Given a payload that may contain a full mip chain, find (width, height, mip_count, score).

    For each pow2 base dimension, compute the cumulative mip chain size and check
    if it matches the payload. Returns matches sorted by score (best first).
    """
    if bpp <= 0:
        return []

    results = []
    for exp_w in range(3, 11):  # 8 to 1024
        w = 1 << exp_w
        for exp_h in range(3, 11):  # 8 to 1024
            h = 1 << exp_h
            # Compute mip chain: sum of all mip levels from (w,h) down to (8,8) or smaller
            total = 0
            mw, mh = w, h
            mip_count = 0
            while mw >= 4 and mh >= 4:
                mip_size = (mw * mh * bpp + 7) // 8
                total += mip_size
                mip_count += 1
                if total == payload:
                    score = 1
                    if w == h:
                        score += 2
                    elif max(w, h) / min(w, h) <= 4:
                        score += 1
                    if 32 <= w <= 512 and 32 <= h <= 512:
                        score += 1
                    if mip_count >= 3:
                        score += 1  # Prefer multi-level chains
                    results.append((w, h, mip_count, score))
                    break
                if total > payload:
                    break
                mw >>= 1
                mh >>= 1

    results.sort(key=lambda x: -x[3])
    return results


# ──────────────────────────────────────────────
# Variant 1: Standard TEX header (generic)
# ──────────────────────────────────────────────

def _try_variant_standard(data: bytes, base: TexParseResult,
                           title_id: str = "") -> Optional[TexParseResult]:
    """
    Standard Capcom TEX layout:
      0x00: magic (4 bytes)
      0x04: version/flags (2 bytes)
      0x06: width (2 bytes, LE)
      0x08: height (2 bytes, LE)
      0x0A: mip count (1 byte)
      0x0B: format (1 byte)
      0x0C: data offset (4 bytes, LE)
    """
    if len(data) < 16:
        return None

    magic4 = data[0:4]
    if magic4 not in CAPCOM_TEX_MAGICS:
        return None

    r = TexParseResult(base.path)
    r.file_size = base.file_size
    r.parser_variant = "standard_tex"

    version = read_u16_le(data, 0x04)
    width = read_u16_le(data, 0x06)
    height = read_u16_le(data, 0x08)
    mip_count = read_u8(data, 0x0A)
    fmt_raw = read_u8(data, 0x0B)

    r.notes.append(f"magic={magic4!r}, version=0x{version:04X}")

    if not _dims_valid(width, height):
        r.notes.append(f"Dims invalid in standard layout: {width}x{height}")
        return None

    fmt_map = _get_format_map(title_id)
    fmt_pica = fmt_map.get(fmt_raw, fmt_raw if fmt_raw <= 0xD else -1)
    if fmt_pica < 0 or fmt_pica > 0xD:
        r.notes.append(f"Unknown format byte 0x{fmt_raw:02X}")
        return None

    from textures.decoder import calculate_texture_size
    data_offset_field = read_u32_le(data, 0x0C)
    if data_offset_field == 0 or data_offset_field >= len(data):
        data_offset_field = 0x10
        r.notes.append(f"data_offset field was 0 or OOB, defaulting to 0x10")

    expected = calculate_texture_size(width, height, fmt_pica)
    actual_avail = len(data) - data_offset_field

    r.width = width
    r.height = height
    r.format_raw = fmt_raw
    r.format_pica = fmt_pica
    r.mip_count = max(1, mip_count)
    r.data_offset = data_offset_field
    r.expected_data_size = expected
    r.actual_data_size = actual_avail

    if actual_avail < expected * 3 // 4:
        r.status = "partial"
        r.confidence = "low"
        r.notes.append(f"Data too small: have {actual_avail}, need ~{expected}")
        r.pixel_data = data[data_offset_field:]
    else:
        r.status = "parsed"
        r.confidence = "high"
        r.pixel_data = data[data_offset_field:data_offset_field + expected]

    logger.info(
        f"TEX standard: {base.path} -> {width}x{height} "
        f"fmt=0x{fmt_raw:02X}->PICA 0x{fmt_pica:X} mips={mip_count} "
        f"conf={r.confidence}"
    )
    return r


# ──────────────────────────────────────────────
# Variant 2: MT Framework Mobile
# ──────────────────────────────────────────────

def _try_variant_mt_mobile(data: bytes, base: TexParseResult,
                            title_id: str = "") -> Optional[TexParseResult]:
    """
    MT Framework Mobile variant:
      0x00: constant/version (4 bytes)
      0x04: format (1 byte)
      0x05: mip count (1 byte)
      0x06: width (2 bytes)
      0x08: height (2 bytes)
      0x0A: padding (2 bytes)
      0x0C: data size (4 bytes)
      0x10+: pixel data
    """
    if len(data) < 16:
        return None

    r = TexParseResult(base.path)
    r.file_size = base.file_size
    r.parser_variant = "mt_mobile"

    fmt_raw = read_u8(data, 0x04)
    mip_count = read_u8(data, 0x05)
    width = read_u16_le(data, 0x06)
    height = read_u16_le(data, 0x08)

    if not _dims_valid(width, height):
        return None
    if mip_count == 0 or mip_count > 16:
        return None

    fmt_map = _get_format_map(title_id)
    fmt_pica = fmt_map.get(fmt_raw, fmt_raw if fmt_raw <= 0xD else -1)
    if fmt_pica < 0 or fmt_pica > 0xD:
        return None

    from textures.decoder import calculate_texture_size
    expected = calculate_texture_size(width, height, fmt_pica)
    actual_avail = len(data) - 0x10

    if expected == 0 or actual_avail < expected // 2:
        return None

    r.width = width
    r.height = height
    r.format_raw = fmt_raw
    r.format_pica = fmt_pica
    r.mip_count = max(1, mip_count)
    r.data_offset = 0x10
    r.expected_data_size = expected
    r.actual_data_size = actual_avail
    r.pixel_data = data[0x10:0x10 + expected]
    r.status = "parsed"
    r.confidence = "medium"
    r.notes.append("Matched MT Framework Mobile layout")

    logger.info(
        f"TEX mt_mobile: {base.path} -> {width}x{height} "
        f"fmt=0x{fmt_raw:02X}->PICA 0x{fmt_pica:X} conf={r.confidence}"
    )
    return r


# ──────────────────────────────────────────────
# Variant 3: Shifted header
# ──────────────────────────────────────────────

def _try_variant_shifted(data: bytes, base: TexParseResult,
                          title_id: str = "") -> Optional[TexParseResult]:
    """
    Shifted variant: magic at 0x00, but fields shifted by +4 from standard.
      0x00: magic (4 bytes)
      0x04: unknown (4 bytes)
      0x08: version/flags (2 bytes)
      0x0A: width (2 bytes)
      0x0C: height (2 bytes)
      0x0E: mip count (1 byte)
      0x0F: format (1 byte)
      0x10: data offset (4 bytes)
    """
    if len(data) < 20:
        return None

    r = TexParseResult(base.path)
    r.file_size = base.file_size
    r.parser_variant = "shifted_tex"

    width = read_u16_le(data, 0x0A)
    height = read_u16_le(data, 0x0C)
    mip_count = read_u8(data, 0x0E)
    fmt_raw = read_u8(data, 0x0F)

    if not _dims_valid(width, height):
        return None

    fmt_map = _get_format_map(title_id)
    fmt_pica = fmt_map.get(fmt_raw, fmt_raw if fmt_raw <= 0xD else -1)
    if fmt_pica < 0 or fmt_pica > 0xD:
        return None

    from textures.decoder import calculate_texture_size
    data_offset_field = read_u32_le(data, 0x10)
    if data_offset_field == 0 or data_offset_field >= len(data):
        data_offset_field = 0x14

    expected = calculate_texture_size(width, height, fmt_pica)
    actual_avail = len(data) - data_offset_field

    if expected == 0 or actual_avail < expected // 2:
        return None

    r.width = width
    r.height = height
    r.format_raw = fmt_raw
    r.format_pica = fmt_pica
    r.mip_count = max(1, mip_count)
    r.data_offset = data_offset_field
    r.expected_data_size = expected
    r.actual_data_size = actual_avail
    r.pixel_data = data[data_offset_field:data_offset_field + expected]
    r.status = "parsed"
    r.confidence = "medium"
    r.notes.append("Matched shifted header layout (magic + 4-byte gap)")

    logger.info(
        f"TEX shifted: {base.path} -> {width}x{height} "
        f"fmt=0x{fmt_raw:02X} conf={r.confidence}"
    )
    return r


# ──────────────────────────────────────────────
# Variant 4: Payload-driven brute force (no profile)
# ──────────────────────────────────────────────

def _try_variant_payload_bruteforce(data: bytes, base: TexParseResult,
                                     title_id: str = "") -> Optional[TexParseResult]:
    """
    Last resort for TEX files with valid magic but unknown header layout.

    Strategy:
      - Try header sizes: 0x10, 0x14, 0x18, 0x20
      - For each, compute payload = file_size - header_size
      - Try all PICA formats and find (w, h) pow2 pairs that match payload exactly
      - Score and pick best
    """
    for hdr_size in [0x14, 0x10, 0x18, 0x20]:
        if hdr_size >= len(data):
            continue

        payload = len(data) - hdr_size
        if payload <= 0:
            continue

        candidates = []
        for pica_id, bpp in PICA_BPP.items():
            dims = _find_pow2_dims_for_payload(payload, bpp)
            for w, h, score in dims:
                # Bonus for common game formats
                if pica_id in (0xC, 0xD):  # ETC1, ETC1A4
                    score += 1
                candidates.append((w, h, pica_id, bpp, score))

        if not candidates:
            continue

        candidates.sort(key=lambda c: -c[4])
        best = candidates[0]
        w, h, pica_id, bpp, score = best

        r = TexParseResult(base.path)
        r.file_size = base.file_size
        r.parser_variant = f"payload_bruteforce/hdr=0x{hdr_size:X}"
        r.width = w
        r.height = h
        r.format_raw = -1
        r.format_pica = pica_id
        r.mip_count = 1
        r.data_offset = hdr_size
        r.expected_data_size = payload
        r.actual_data_size = payload
        r.pixel_data = data[hdr_size:hdr_size + payload]
        r.status = "partial"
        r.confidence = "low"
        r.notes.append(f"Brute-force payload match: hdr=0x{hdr_size:X}, payload={payload}")
        r.notes.append(f"Best: {w}x{h} PICA 0x{pica_id:X} ({bpp}bpp) score={score}")
        if len(candidates) > 1:
            alt = candidates[1]
            r.notes.append(f"Alt: {alt[0]}x{alt[1]} PICA 0x{alt[2]:X} score={alt[4]}")
        _log_header_dump(data, r)

        logger.info(
            f"TEX bruteforce: {base.path} -> {w}x{h} "
            f"PICA 0x{pica_id:X} conf=low hdr=0x{hdr_size:X}"
        )
        return r

    return None


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _dims_valid(w: int, h: int) -> bool:
    if w < 4 or h < 4 or w > 1024 or h > 1024:
        return False
    if w % 4 != 0 or h % 4 != 0:
        return False
    return True


def _is_pow2(v: int) -> bool:
    return v > 0 and (v & (v - 1)) == 0


def _log_header_dump(data: bytes, result: TexParseResult):
    """Dump the first 32 bytes of a file for debugging."""
    dump = data[:min(32, len(data))]
    hex_str = " ".join(f"{b:02X}" for b in dump)
    result.notes.append(f"Header bytes: {hex_str}")


# ──────────────────────────────────────────────
# Legacy API (backward compat with main.py)
# ──────────────────────────────────────────────

def parse_capcom_tex(data: bytes, title_id: str = "") -> Optional[Dict[str, Any]]:
    """Legacy wrapper: parse and return dict or None."""
    result = parse_capcom_tex_strict(data, "", title_id=title_id)
    if result.status not in ("parsed", "partial"):
        return None
    if result.pixel_data is None:
        return None
    return {
        "format": result.format_pica,
        "width": result.width,
        "height": result.height,
        "data": result.pixel_data,
        "mip_count": result.mip_count,
        "name": "",
        "parser_variant": result.parser_variant,
        "confidence": result.confidence,
    }


def scan_capcom_textures(data: bytes, file_path: str,
                         title_id: str = "") -> List[Dict[str, Any]]:
    """Scan for Capcom textures in a file (handles multi-tex archives)."""
    textures = []

    # Try as single file first
    result = parse_capcom_tex_strict(data, file_path, title_id=title_id)
    if result.status in ("parsed", "partial") and result.pixel_data:
        textures.append({
            "format": result.format_pica,
            "width": result.width,
            "height": result.height,
            "data": result.pixel_data,
            "mip_count": result.mip_count,
            "name": "",
            "source_file": file_path,
            "parser_variant": result.parser_variant,
            "confidence": result.confidence,
        })
        return textures

    # Scan for embedded TEX magic
    for magic in CAPCOM_TEX_MAGICS:
        offset = 0
        while offset < len(data) - 16:
            idx = data.find(magic, offset)
            if idx < 0:
                break
            sub = data[idx:]
            sub_result = parse_capcom_tex_strict(sub, f"{file_path}+0x{idx:X}",
                                                  title_id=title_id)
            if sub_result.status in ("parsed", "partial") and sub_result.pixel_data:
                textures.append({
                    "format": sub_result.format_pica,
                    "width": sub_result.width,
                    "height": sub_result.height,
                    "data": sub_result.pixel_data,
                    "mip_count": sub_result.mip_count,
                    "name": "",
                    "source_file": file_path,
                    "sub_offset": idx,
                    "parser_variant": sub_result.parser_variant,
                    "confidence": sub_result.confidence,
                })
            offset = idx + 4

    return textures
