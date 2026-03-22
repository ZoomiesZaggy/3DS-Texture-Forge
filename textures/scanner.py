"""
File fingerprinting and texture scanning with confidence levels.

Strategy:
  1. Check magic bytes first (fast, high confidence).
  2. Try known parsers matched by magic or extension.
  3. Fall back to heuristic raw-texture detection only if nothing else matched.
  4. Every result carries a confidence: high / medium / low.
"""

import struct
import logging
from typing import List, Dict, Any, Optional, Tuple
from textures.decoder import (
    FORMAT_BPP, FORMAT_NAMES, FMT_ETC1, FMT_ETC1A4,
    calculate_texture_size, decode_texture_fast
)
from textures.bch import is_bch, is_cgfx, extract_bch_textures
from textures.bflim import is_bflim, parse_bflim
from textures.cgfx import extract_cgfx_textures
from textures.ctpk import is_ctpk, parse_ctpk
from textures.ctxb import is_ctxb, parse_ctxb
from textures.cmb import is_cmb, extract_cmb_textures
from textures.tex_capcom import is_capcom_tex, parse_capcom_tex_strict
from textures.shinen_tex import is_shinen_tex, parse_shinen_tex
from parsers.sarc import is_sarc, parse_sarc
from parsers.garc import is_garc, parse_garc, parse_garc_iter, garc_has_cgfx
from parsers.narc import is_narc, parse_narc
from parsers.zar import is_zar, parse_zar
from parsers.gar import is_gar, parse_gar
from parsers.darc import is_darc, parse_darc
from parsers.arc_capcom import is_capcom_arc, parse_capcom_arc
from parsers.arc_fe import is_fe_arc, parse_fe_arc
from parsers.lz import is_lz_compressed, decompress_lz
import numpy as np

logger = logging.getLogger(__name__)

STANDARD_DIMS = [8, 16, 32, 64, 128, 256, 512, 1024]

MAX_YAZ0_SIZE = 50 * 1024 * 1024  # 50 MB decompression limit


def is_yaz0(data: bytes) -> bool:
    """Check if data is Yaz0-compressed (used by .szs files)."""
    return len(data) >= 16 and data[:4] == b'Yaz0'


def yaz0_decompress(data: bytes) -> Optional[bytes]:
    """Decompress Yaz0 (LZ77 variant) data. Returns None on failure."""
    if not is_yaz0(data):
        return None
    decompressed_size = struct.unpack('>I', data[4:8])[0]
    if decompressed_size > MAX_YAZ0_SIZE:
        logger.warning(f"Yaz0: decompressed size {decompressed_size:,} exceeds limit")
        return None
    out = bytearray()
    src = 16
    while len(out) < decompressed_size and src < len(data):
        code = data[src]; src += 1
        for bit in range(7, -1, -1):
            if len(out) >= decompressed_size:
                break
            if code & (1 << bit):
                if src >= len(data):
                    break
                out.append(data[src]); src += 1
            else:
                if src + 1 >= len(data):
                    break
                b1 = data[src]; b2 = data[src + 1]; src += 2
                dist = ((b1 & 0x0F) << 8) | b2
                length = b1 >> 4
                if length == 0:
                    if src >= len(data):
                        break
                    length = data[src] + 0x12; src += 1
                else:
                    length += 2
                back = len(out) - dist - 1
                for j in range(length):
                    if len(out) >= decompressed_size:
                        break
                    out.append(out[back + j] if back + j >= 0 else 0)
    return bytes(out)


class FileFingerprint:
    """Fingerprint of a single file from RomFS."""
    def __init__(self, path: str, data: bytes):
        self.path = path
        self.size = len(data)
        self.ext = ""
        if "." in path:
            self.ext = "." + path.rsplit(".", 1)[-1].lower()

        self.magic4 = data[:4] if len(data) >= 4 else b""
        self.detected_type: Optional[str] = None
        self.confidence = "none"
        self._classify(data)

    def _classify(self, data: bytes):
        """Classify file type by magic bytes."""
        if len(data) < 4:
            return

        if is_yaz0(data):
            self.detected_type = "yaz0"
            self.confidence = "high"
        elif self.ext in (".lz", ".cmp", ".chres", ".chtex", ".zrc") and is_lz_compressed(data, self.path):
            self.detected_type = "nintendo_lz"
            self.confidence = "high"
        elif is_garc(data):
            self.detected_type = "garc"
            self.confidence = "high"
        elif is_sarc(data):
            self.detected_type = "sarc"
            self.confidence = "high"
        elif is_narc(data):
            self.detected_type = "narc"
            self.confidence = "high"
        elif is_zar(data):
            self.detected_type = "zar"
            self.confidence = "high"
        elif is_gar(data):
            self.detected_type = "gar"
            self.confidence = "high"
        elif is_darc(data):
            self.detected_type = "darc"
            self.confidence = "high"
        elif is_capcom_arc(data):
            self.detected_type = "capcom_arc"
            self.confidence = "high"
        elif is_fe_arc(data):
            self.detected_type = "fe_arc"
            self.confidence = "high"
        elif is_ctxb(data):
            self.detected_type = "ctxb"
            self.confidence = "high"
        elif is_ctpk(data):
            self.detected_type = "ctpk"
            self.confidence = "high"
        elif is_bch(data):
            self.detected_type = "bch"
            self.confidence = "high"
        elif is_cgfx(data):
            self.detected_type = "cgfx"
            self.confidence = "high"
        elif is_bflim(data):
            self.detected_type = "bflim"
            self.confidence = "high"
        elif is_shinen_tex(data):
            self.detected_type = "shinen_tex"
            self.confidence = "high"
        elif is_capcom_tex(data):
            self.detected_type = "capcom_tex"
            self.confidence = "high"
        elif self.ext == ".tex":
            self.detected_type = "capcom_tex"
            self.confidence = "medium"
        elif self.ext in (".bch", ".bcres"):
            self.detected_type = "bch"
            self.confidence = "medium"
        elif self.ext == ".bflim":
            self.detected_type = "bflim"
            self.confidence = "medium"
        elif self.ext == ".ctpk":
            self.detected_type = "ctpk"
            self.confidence = "medium"
        elif self.ext == ".arc":
            self.detected_type = "sarc"
            self.confidence = "medium"
        elif self.ext == ".sarc":
            self.detected_type = "sarc"
            self.confidence = "medium"
        elif self.ext == ".zar":
            self.detected_type = "zar"
            self.confidence = "medium"
        elif self.ext in (".gar", ".lzs"):
            self.detected_type = "gar"
            self.confidence = "medium"
        elif self.ext == ".ctxb":
            self.detected_type = "ctxb"
            self.confidence = "medium"
        elif self.ext == ".cmb":
            self.detected_type = "cmb"
            self.confidence = "medium"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "size": self.size,
            "ext": self.ext,
            "magic": self.magic4.hex() if self.magic4 else "",
            "detected_type": self.detected_type,
            "confidence": self.confidence,
        }


def fingerprint_file(data: bytes, file_path: str) -> FileFingerprint:
    """Create a fingerprint for a file."""
    return FileFingerprint(file_path, data)


def identify_texture_format(data: bytes, file_path: str = "") -> Optional[str]:
    """Identify the texture container format of a file."""
    fp = fingerprint_file(data, file_path)
    return fp.detected_type


def extract_textures_with_confidence(
    data: bytes,
    file_path: str,
    scan_all: bool = False,
    title_id: str = "",
) -> Tuple[List[Dict[str, Any]], FileFingerprint]:
    """
    Extract textures from a file, returning results with confidence levels.
    Returns (texture_list, fingerprint).
    Each texture dict includes 'confidence' and 'parser_used' keys.
    """
    fp = fingerprint_file(data, file_path)
    textures = []

    # --- Known parsers, ordered by fingerprint match ---
    if fp.detected_type == "yaz0":
        textures = _extract_yaz0(data, file_path, scan_all=scan_all, title_id=title_id)
    elif fp.detected_type == "nintendo_lz":
        textures = _extract_nintendo_lz(data, file_path, scan_all=scan_all, title_id=title_id)
    elif fp.detected_type == "garc":
        textures = _extract_garc(data, file_path, scan_all=scan_all, title_id=title_id)
    elif fp.detected_type == "zar":
        textures = _extract_zar(data, file_path, scan_all=scan_all, title_id=title_id)
    elif fp.detected_type == "gar":
        textures = _extract_gar(data, file_path, scan_all=scan_all, title_id=title_id)
    elif fp.detected_type == "darc":
        textures = _extract_darc(data, file_path, scan_all=scan_all, title_id=title_id)
    elif fp.detected_type == "capcom_arc":
        textures = _extract_capcom_arc(data, file_path, title_id=title_id)
    elif fp.detected_type == "fe_arc":
        textures = _extract_fe_arc(data, file_path, title_id=title_id)
    elif fp.detected_type == "sarc":
        textures = _extract_sarc(data, file_path, scan_all=scan_all, title_id=title_id)
    elif fp.detected_type == "narc":
        textures = _extract_narc(data, file_path, scan_all=scan_all, title_id=title_id)
    elif fp.detected_type == "ctxb":
        textures = _extract_ctxb(data, file_path)
    elif fp.detected_type == "cmb":
        textures = _extract_cmb(data, file_path)
    elif fp.detected_type == "ctpk":
        textures = _extract_ctpk(data, file_path)
    elif fp.detected_type == "cgfx":
        textures = _extract_cgfx(data, file_path)
    elif fp.detected_type == "bch":
        textures = _extract_bch(data, file_path)
    elif fp.detected_type == "bflim":
        textures = _extract_bflim(data, file_path)
    elif fp.detected_type == "shinen_tex":
        textures = _extract_shinen_tex(data, file_path)
    elif fp.detected_type == "capcom_tex":
        textures = _extract_capcom(data, file_path, title_id=title_id)

    if textures:
        return textures, fp

    # --- Scan for embedded containers ---
    if scan_all or not fp.detected_type:
        embedded = _scan_for_embedded_containers(data, file_path)
        if embedded:
            return embedded, fp

    # --- Heuristic raw texture guess (lowest confidence) ---
    if scan_all and not textures:
        raw = _try_as_raw_texture(data, file_path)
        if raw:
            return raw, fp

    return textures, fp


def _unwrap_pokemon_container(data: bytes) -> Optional[bytes]:
    """Unwrap Pokemon GR/PC/PT container formats to extract inner BCH data.

    Pokemon ORAS/XY uses thin wrapper formats around BCH files:
      PC (Pokemon/Character model): BCH at fixed offset 0x80
      PT (Pokemon Texture): BCH at fixed offset 0x80
      GR (Map model): BCH offset stored at +0x04
    Returns the inner BCH data, or None if not a recognized wrapper.
    """
    if len(data) < 0x84:
        return None
    magic2 = data[:2]
    if magic2 in (b'PC', b'PT'):
        if data[0x80:0x84] == b'BCH\x00':
            return data[0x80:]
    elif magic2 == b'GR':
        bch_off = struct.unpack_from('<I', data, 4)[0]
        if 0 < bch_off < len(data) and data[bch_off:bch_off + 4] == b'BCH\x00':
            return data[bch_off:]
    return None


def _extract_garc(data: bytes, file_path: str,
                   scan_all: bool = False,
                   title_id: str = "") -> List[Dict[str, Any]]:
    """Extract textures from inner files within a GARC archive.

    Uses streaming iteration to handle large GARCs (1GB+) without
    loading all inner files into memory at once. Processes:
      - Direct texture containers (CGFX, BCH, CTPK, BFLIM)
      - LZ-compressed entries (decompress, then check for textures)
      - Pokemon wrapper formats (PC, PT, GR → unwrap to inner BCH)
    """
    if not is_garc(data):
        return []

    # Check if this GARC contains any CGFX files. If so, skip BCH files
    # entirely — the real textures are in CGFX, and the BCH heuristic
    # parser produces massive false positives on 3D model data.
    has_cgfx = garc_has_cgfx(data)

    textures = []
    processed = 0
    for inner_name, inner_data in parse_garc_iter(data):
        if len(inner_data) < 8:
            continue

        ext = inner_name.rsplit('.', 1)[-1].lower() if '.' in inner_name else ''

        # Direct texture container formats
        if ext in ('cgfx', 'bch', 'ctpk', 'bflim', 'sarc'):
            if ext == 'bch' and has_cgfx:
                continue
            inner_path = f"{file_path}>{inner_name}"
            inner_textures, _ = extract_textures_with_confidence(
                inner_data, inner_path, scan_all=False, title_id=title_id,
            )
            for tex in inner_textures:
                tex["source_file"] = inner_path
                tex["garc_parent"] = file_path
            textures.extend(inner_textures)
            processed += 1

        elif ext == 'bin':
            # Try LZ decompression for .bin files (common in Pokemon GARCs)
            work = inner_data
            is_compressed = False
            if inner_data[0] in (0x10, 0x11) and len(inner_data) > 16:
                try:
                    dec = decompress_lz(inner_data)
                    if dec and len(dec) >= 8:
                        work = dec
                        is_compressed = True
                except Exception:
                    continue

            # Check for Pokemon wrapper formats (PC/PT/GR → BCH inside)
            unwrapped = _unwrap_pokemon_container(work)
            if unwrapped is not None:
                suffix = "[lz]" if is_compressed else ""
                inner_path = f"{file_path}>{inner_name}{suffix}[unwrap]"
                inner_textures, _ = extract_textures_with_confidence(
                    unwrapped, inner_path, scan_all=False, title_id=title_id,
                )
                for tex in inner_textures:
                    tex["source_file"] = inner_path
                    tex["garc_parent"] = file_path
                textures.extend(inner_textures)
                processed += 1
            elif work[:4] in (b'BCH\x00', b'CGFX', b'CTPK'):
                # LZ-compressed texture container (no wrapper)
                suffix = "[lz]" if is_compressed else ""
                inner_path = f"{file_path}>{inner_name}{suffix}"
                inner_textures, _ = extract_textures_with_confidence(
                    work, inner_path, scan_all=False, title_id=title_id,
                )
                for tex in inner_textures:
                    tex["source_file"] = inner_path
                    tex["garc_parent"] = file_path
                textures.extend(inner_textures)
                processed += 1

        # Progress indicator for large GARCs
        if processed > 0 and processed % 500 == 0:
            logger.info(f"GARC {file_path}: processed {processed} files, {len(textures)} textures so far...")

    if textures:
        logger.info(f"GARC {file_path}: {processed} files processed, {len(textures)} textures")
    return textures


def _extract_yaz0(data: bytes, file_path: str,
                   scan_all: bool = False,
                   title_id: str = "") -> List[Dict[str, Any]]:
    """Decompress Yaz0 data and extract textures from the inner content."""
    decompressed = yaz0_decompress(data)
    if decompressed is None:
        return []
    logger.info(f"Yaz0 {file_path}: {len(data):,} -> {len(decompressed):,} bytes")
    # Recursively extract from the decompressed content
    inner_path = f"{file_path}>decompressed"
    textures, _ = extract_textures_with_confidence(
        decompressed, inner_path, scan_all=scan_all, title_id=title_id,
    )
    return textures


def _extract_nintendo_lz(data: bytes, file_path: str,
                          scan_all: bool = False,
                          title_id: str = "") -> List[Dict[str, Any]]:
    """Decompress Nintendo LZ data and extract textures from the inner content."""
    decompressed = decompress_lz(data)
    if decompressed is None:
        return []
    logger.info(f"LZ {file_path}: {len(data):,} -> {len(decompressed):,} bytes")
    # Strip .lz/.cmp extension to reveal inner filename for better classification
    inner_path = file_path
    lower = file_path.lower()
    if lower.endswith('.lz') or lower.endswith('.cmp'):
        inner_path = file_path[:-len('.lz')] if lower.endswith('.lz') else file_path[:-len('.cmp')]
    inner_path = f"{inner_path}[decompressed]"
    # Recursively extract from the decompressed content
    textures, _ = extract_textures_with_confidence(
        decompressed, inner_path, scan_all=scan_all, title_id=title_id,
    )
    return textures


def _extract_zar(data: bytes, file_path: str,
                  scan_all: bool = False,
                  title_id: str = "") -> List[Dict[str, Any]]:
    """Extract textures from inner files within a ZAR archive."""
    inner_files = parse_zar(data)
    if not inner_files:
        return []

    textures = []
    for inner_name, inner_data in inner_files:
        if len(inner_data) < 8:
            continue
        # Only process texture-related inner files
        ext = inner_name.rsplit('.', 1)[-1].lower() if '.' in inner_name else ''
        if ext not in ('ctxb', 'cmb', 'cgfx', 'bch', 'ctpk', 'bflim', 'zsi'):
            continue
        # For .cmb files, try CMB texture extraction directly
        if ext == 'cmb':
            inner_path = f"{file_path}>{inner_name}"
            cmb_textures = _extract_cmb(inner_data, inner_path)
            for tex in cmb_textures:
                tex["source_file"] = inner_path
                tex["zar_parent"] = file_path
            textures.extend(cmb_textures)
            continue
        inner_path = f"{file_path}>{inner_name}"
        inner_textures, inner_fp = extract_textures_with_confidence(
            inner_data, inner_path, scan_all=False, title_id=title_id,
        )
        for tex in inner_textures:
            tex["source_file"] = inner_path
            tex["zar_parent"] = file_path
        textures.extend(inner_textures)

    if textures:
        logger.info(f"ZAR {file_path}: {len(inner_files)} inner files, {len(textures)} textures")
    return textures


def _extract_gar(data: bytes, file_path: str,
                  scan_all: bool = False,
                  title_id: str = "") -> List[Dict[str, Any]]:
    """Extract textures from inner files within a GAR archive."""
    textures = []
    for idx, inner_name, inner_data in parse_gar(data):
        if len(inner_data) < 8:
            continue
        inner_path = f"{file_path}>{inner_name}"
        inner_textures, _ = extract_textures_with_confidence(
            inner_data, inner_path, scan_all=False, title_id=title_id,
        )
        for tex in inner_textures:
            tex["source_file"] = inner_path
        textures.extend(inner_textures)

    if textures:
        logger.info(f"GAR {file_path}: {len(textures)} textures")
    return textures


def _extract_darc(data: bytes, file_path: str,
                   scan_all: bool = False,
                   title_id: str = "") -> List[Dict[str, Any]]:
    """Extract textures from inner files within a darc archive."""
    textures = []
    for inner_name, inner_data in parse_darc(data):
        if len(inner_data) < 8:
            continue
        inner_path = f"{file_path}>{inner_name}"
        inner_textures, _ = extract_textures_with_confidence(
            inner_data, inner_path, scan_all=False, title_id=title_id,
        )
        for tex in inner_textures:
            tex["source_file"] = inner_path
            tex["darc_parent"] = file_path
        textures.extend(inner_textures)

    if textures:
        logger.info(f"darc {file_path}: {len(textures)} textures")
    return textures


def _extract_capcom_arc(data: bytes, file_path: str,
                        title_id: str = "") -> List[Dict[str, Any]]:
    """Extract TEX textures from a Capcom MT Framework ARC archive."""
    textures = []
    for fname, tex_data in parse_capcom_arc(data):
        inner_path = f"{file_path}>{fname}"
        results = _extract_capcom(tex_data, inner_path, title_id=title_id)
        for r in results:
            r["source_file"] = inner_path
            r["arc_parent"] = file_path
        textures.extend(results)

    if textures:
        logger.info(f"Capcom ARC {file_path}: {len(textures)} textures")
    return textures


def _extract_fe_arc(data: bytes, file_path: str,
                    title_id: str = "") -> List[Dict[str, Any]]:
    """Extract CTPK textures from a Fire Emblem IS ARC archive."""
    textures = []
    for idx, inner_name, inner_data in parse_fe_arc(data):
        inner_path = f"{file_path}>{inner_name}"
        results = _extract_ctpk(inner_data, inner_path)
        for r in results:
            r["source_file"] = inner_path
            r["fe_arc_parent"] = file_path
        textures.extend(results)

    if textures:
        logger.info(f"FE ARC {file_path}: {len(textures)} textures")
    return textures


def _extract_cmb(data: bytes, file_path: str) -> List[Dict[str, Any]]:
    """Extract textures embedded in a CMB model file."""
    results = extract_cmb_textures(data)
    for r in results:
        offset = r.get("data_offset", 0)
        size = r.get("data_size", 0)
        if size > 0 and offset + size <= len(data):
            r["data"] = data[offset:offset + size]
        elif offset < len(data):
            r["data"] = data[offset:]
        r["source_file"] = file_path
        r["confidence"] = "high"
        r["parser_used"] = "cmb"
    return results


def _extract_ctxb(data: bytes, file_path: str) -> List[Dict[str, Any]]:
    """Extract textures from a CTXB file."""
    results = parse_ctxb(data)
    for r in results:
        offset = r.get("data_offset", 0)
        size = r.get("data_size", 0)
        if size > 0 and offset + size <= len(data):
            r["data"] = data[offset:offset + size]
        elif offset < len(data):
            r["data"] = data[offset:]
        r["source_file"] = file_path
        r["confidence"] = "high"
        r["parser_used"] = "ctxb"
    return results


def _extract_cgfx(data: bytes, file_path: str) -> List[Dict[str, Any]]:
    """Extract textures from a CGFX file using the dedicated parser."""
    results = extract_cgfx_textures(data)
    for r in results:
        offset = r.get("data_offset", 0)
        size = r.get("data_size", 0)
        if size > 0 and offset + size <= len(data):
            r["data"] = data[offset:offset + size]
        elif offset < len(data):
            r["data"] = data[offset:]
        r["source_file"] = file_path
        r["confidence"] = "high"
        r["parser_used"] = "cgfx"
    return results


def _extract_sarc(data: bytes, file_path: str,
                   scan_all: bool = False,
                   title_id: str = "") -> List[Dict[str, Any]]:
    """Extract textures from inner files within a SARC archive."""
    inner_files = parse_sarc(data)
    if not inner_files:
        return []

    textures = []
    for inner_name, inner_data in inner_files:
        if len(inner_data) < 8:
            continue
        # Recursively extract textures from inner files
        inner_path = f"{file_path}/{inner_name}"
        inner_textures, inner_fp = extract_textures_with_confidence(
            inner_data, inner_path, scan_all=scan_all, title_id=title_id,
        )
        for tex in inner_textures:
            tex["source_file"] = inner_path
            tex["sarc_parent"] = file_path
        textures.extend(inner_textures)

    if textures:
        logger.info(f"SARC {file_path}: {len(inner_files)} inner files, {len(textures)} textures")
    return textures


def _extract_narc(data: bytes, file_path: str,
                   scan_all: bool = False,
                   title_id: str = "") -> List[Dict[str, Any]]:
    """Extract textures from inner files within a NARC archive."""
    inner_files = parse_narc(data)
    if not inner_files:
        return []

    textures = []
    for inner_name, inner_data in inner_files:
        if len(inner_data) < 8:
            continue
        inner_path = f"{file_path}>narc_{inner_name}"
        inner_textures, inner_fp = extract_textures_with_confidence(
            inner_data, inner_path, scan_all=scan_all, title_id=title_id,
        )
        for tex in inner_textures:
            tex["source_file"] = inner_path
            tex["narc_parent"] = file_path
        textures.extend(inner_textures)

    if textures:
        logger.info(f"NARC {file_path}: {len(inner_files)} inner files, {len(textures)} textures")
    return textures


def _extract_ctpk(data: bytes, file_path: str) -> List[Dict[str, Any]]:
    results = parse_ctpk(data)
    for r in results:
        offset = r.get("data_offset", 0)
        size = r.get("data_size", 0)
        if offset + size <= len(data):
            r["data"] = data[offset:offset + size]
        else:
            r["data"] = data[offset:]
        r["source_file"] = file_path
        r["confidence"] = "high"
        r["parser_used"] = "ctpk"
    return results


def _extract_bch(data: bytes, file_path: str) -> List[Dict[str, Any]]:
    results = extract_bch_textures(data)
    for r in results:
        offset = r.get("data_offset", 0)
        size = r.get("data_size", 0)
        if size > 0 and offset + size <= len(data):
            r["data"] = data[offset:offset + size]
        elif offset < len(data):
            est = calculate_texture_size(r.get("width", 0), r.get("height", 0), r.get("format", 0))
            r["data"] = data[offset:offset + est]
        r["source_file"] = file_path
        r["confidence"] = "medium"  # BCH parser is heuristic-based
        r["parser_used"] = "bch"
    return results


def _extract_bflim(data: bytes, file_path: str) -> List[Dict[str, Any]]:
    result = parse_bflim(data)
    if result:
        result["source_file"] = file_path
        result["confidence"] = "high"
        result["parser_used"] = "bflim"
        # Store crop info if display differs from decode dimensions
        dw = result.get("display_width", 0)
        dh = result.get("display_height", 0)
        if dw and dh and (dw != result["width"] or dh != result["height"]):
            result["crop_width"] = dw
            result["crop_height"] = dh
        return [result]
    return []


def _extract_shinen_tex(data: bytes, file_path: str) -> List[Dict[str, Any]]:
    """Extract textures from a Shin'en TEX CTR file (with optional CMPR decompression)."""
    results = parse_shinen_tex(data)
    for r in results:
        r["source_file"] = file_path
        r["confidence"] = "high"
        r["parser_used"] = "shinen_tex"
    return results


def _extract_capcom(data: bytes, file_path: str,
                    title_id: str = "") -> List[Dict[str, Any]]:
    from textures.tex_capcom import parse_capcom_tex_strict
    pr = parse_capcom_tex_strict(data, file_path, title_id=title_id)
    if pr.status in ("parsed", "partial") and pr.pixel_data:
        return [{
            "format": pr.format_pica,
            "width": pr.width,
            "height": pr.height,
            "data": pr.pixel_data,
            "mip_count": pr.mip_count,
            "name": "",
            "source_file": file_path,
            "confidence": pr.confidence,
            "parser_used": f"capcom_tex/{pr.parser_variant}",
            "capcom_parse_notes": pr.notes,
        }]
    return []


def _scan_for_embedded_containers(data: bytes, file_path: str) -> List[Dict[str, Any]]:
    """Scan for known magic bytes embedded within a larger file."""
    textures = []

    magic_checks = [
        (b"CTPK", _extract_ctpk),
        (b"BCH\x00", _extract_bch),
        (b"CGFX", _extract_bch),
    ]

    for magic, extractor in magic_checks:
        offset = 0
        while offset < len(data) - len(magic):
            idx = data.find(magic, offset)
            if idx < 0:
                break
            try:
                sub = data[idx:]
                results = extractor(sub, file_path)
                for r in results:
                    r["sub_offset"] = idx
                    # Downgrade confidence for embedded containers
                    if r.get("confidence") == "high":
                        r["confidence"] = "medium"
                    r["parser_used"] = r.get("parser_used", "") + f"@embedded+0x{idx:X}"
                textures.extend(results)
            except Exception as e:
                logger.debug(f"Embedded {magic!r} at 0x{idx:X} failed: {e}")
            offset = idx + 4

    return textures


def _try_as_raw_texture(data: bytes, file_path: str) -> List[Dict[str, Any]]:
    """Heuristic: try interpreting raw data as a PICA200 texture."""
    data_size = len(data)

    for fmt_id, bpp in FORMAT_BPP.items():
        if bpp == 0:
            continue
        for w in STANDARD_DIMS:
            for h in STANDARD_DIMS:
                expected = calculate_texture_size(w, h, fmt_id)
                if expected == 0:
                    continue
                if abs(data_size - expected) > 256:
                    continue
                if _validate_raw(data[:expected], w, h, fmt_id):
                    reason = (
                        f"File size {data_size} ~= expected {expected} for "
                        f"{FORMAT_NAMES.get(fmt_id, '?')} {w}x{h}; "
                        f"decoded image has non-trivial pixel variance"
                    )
                    return [{
                        "format": fmt_id,
                        "width": w,
                        "height": h,
                        "data": data[:expected],
                        "data_offset": 0,
                        "data_size": expected,
                        "source_file": file_path,
                        "name": f"raw_{FORMAT_NAMES.get(fmt_id, 'UNK')}_{w}x{h}",
                        "mip_count": 1,
                        "confidence": "low",
                        "parser_used": "raw_heuristic",
                        "heuristic_reason": reason,
                    }]
    return []


def _validate_raw(data: bytes, w: int, h: int, fmt: int) -> bool:
    try:
        result = decode_texture_fast(data, w, h, fmt)
        if result is None:
            return False
        flat = result.reshape(-1, 4)
        if np.all(flat == 0):
            return False
        for ch in range(3):
            if float(np.std(flat[:, ch].astype(np.float32))) > 5.0:
                return True
        return False
    except Exception:
        return False


def scan_file_for_textures(data: bytes, file_path: str = "",
                           min_w: int = 4, min_h: int = 4,
                           max_w: int = 1024, max_h: int = 1024) -> List[Dict[str, Any]]:
    """Legacy API: scan a file for textures (fallback scanner)."""
    textures, _ = extract_textures_with_confidence(data, file_path, scan_all=True)
    return textures
