"""
File fingerprinting and texture scanning with confidence levels.

Strategy:
  1. Check magic bytes first (fast, high confidence).
  2. Try known parsers matched by magic or extension.
  3. Fall back to heuristic raw-texture detection only if nothing else matched.
  4. Every result carries a confidence: high / medium / low.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from textures.decoder import (
    FORMAT_BPP, FORMAT_NAMES, FMT_ETC1, FMT_ETC1A4,
    calculate_texture_size, decode_texture_fast
)
from textures.bch import is_bch, is_cgfx, extract_bch_textures
from textures.bflim import is_bflim, parse_bflim
from textures.ctpk import is_ctpk, parse_ctpk
from textures.tex_capcom import is_capcom_tex, parse_capcom_tex_strict
import numpy as np

logger = logging.getLogger(__name__)

STANDARD_DIMS = [8, 16, 32, 64, 128, 256, 512, 1024]


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

        if is_ctpk(data):
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
    if fp.detected_type == "ctpk":
        textures = _extract_ctpk(data, file_path)
    elif fp.detected_type in ("bch", "cgfx"):
        textures = _extract_bch(data, file_path)
    elif fp.detected_type == "bflim":
        textures = _extract_bflim(data, file_path)
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
        return [result]
    return []


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
