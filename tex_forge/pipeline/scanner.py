"""Classify a file by magic bytes / extension and route it to the right plugin.

Replaces v1's `textures/scanner.py` -- ~1300 lines of if/elif fingerprinting
collapsed into:

    classify_file(data, path) -> FilePeek
        Returns FilePeek with detected_type set if any plugin matches.

    extract_textures(data, path, title_id, scan_all) -> Iterator[Texture]
        Top-level entry: walks compression -> archive recursion -> texture
        extraction, then optionally falls back to embedded-magic scanning
        and the raw heuristic.
"""

from __future__ import annotations

import logging
from typing import Iterator, Optional

from tex_forge.archives.registry import detect_archive
from tex_forge.compression.registry import try_decompress
from tex_forge.core.types import FilePeek, Texture
from tex_forge.textures.containers import bflim as _bflim_plugin  # noqa: F401  ensure registered
from tex_forge.textures.registry import detect_texture

logger = logging.getLogger(__name__)

# Magic bytes recognised as "definitely worth looking inside" -- used by the
# decompression fast-reject filter to avoid wasting time on .cmp files that
# decompress to non-texture content.
KNOWN_TEXTURE_MAGICS = frozenset({
    b"BCH\x00", b"CGFX", b"CTPK", b"SARC", b"NARC", b"darc",
    b"Yaz0",    b"ZAR\x01", b"GAR\x02", b"ARC\x00", b"TEX\x00",
    b"ctxb",    b"jIMG", b"CPK ", b"ARC0", b"GFAC", b"GDB1",
})
BFLIM_FOOTERS = (b"FLIM", b"CLIM")


def classify_file(data: bytes, path: str) -> FilePeek:
    """Classify a RomFS file by its magic bytes / extension.

    detected_type values come from the registry plugin names: "garc",
    "sarc", "bch", etc., plus "compressed" if a decompression codec
    matches the leading bytes.
    """
    ext = ""
    if "." in path:
        ext = "." + path.rsplit(".", 1)[-1].lower()
    magic4 = data[:4] if len(data) >= 4 else b""
    peek = FilePeek(path=path, size=len(data), ext=ext, magic4=magic4)

    if len(data) < 4:
        return peek

    # Archive magic check
    a = detect_archive(data)
    if a is not None:
        peek.detected_type = a.name
        peek.confidence = "high"
        return peek

    # Texture magic check -- includes BFLIM footer detection
    t = detect_texture(data)
    if t is not None:
        peek.detected_type = t.name
        peek.confidence = "high"
        return peek

    # Compression magic check (don't attempt to decompress here -- expensive)
    from tex_forge.compression.registry import iter_codecs
    for c in iter_codecs():
        try:
            if c.detect(data):
                peek.detected_type = "compressed:" + c.name
                peek.confidence = "high" if ext in (".lz", ".cmp") else "medium"
                return peek
        except Exception:
            continue

    # Extension-based fallback (lower confidence)
    EXT_MAP = {
        ".bch": "bch", ".bcres": "bch",
        ".cgfx": "cgfx",
        ".ctpk": "ctpk", ".cptk": "ctpk",
        ".ctxb": "ctxb",
        ".cmb": "cmb",
        ".bflim": "bflim", ".bclim": "bflim",
        ".tex": "capcom_tex",
        ".texturegdb": "gdb1",
        ".jtex": "jimg",
        ".sarc": "sarc", ".arc": "sarc",
        ".zar": "zar",
        ".gar": "gar", ".lzs": "gar",
        ".garc": "garc",
        ".narc": "narc",
        ".cpk": "cpk",
        ".fa": "arc0",
    }
    if ext in EXT_MAP:
        peek.detected_type = EXT_MAP[ext]
        peek.confidence = "medium"
        return peek

    return peek


def _has_texture_payload(data: bytes) -> bool:
    """Cheap reject for decompressed payloads -- skip if no texture magic."""
    if len(data) < 4:
        return False
    if data[:4] in KNOWN_TEXTURE_MAGICS:
        return True
    if len(data) >= 0x28 and data[-0x28:-0x24] in BFLIM_FOOTERS:
        return True
    return False


def extract_textures(
    data: bytes,
    path: str,
    *,
    title_id: str = "",
    scan_all: bool = False,
    depth: int = 0,
) -> Iterator[Texture]:
    """Walk a file: decompression -> archive recursion -> texture extraction.

    Yields one Texture per decoded image found. Recurses into archives via
    extract_textures(inner_data, path>inner_name, ...).

    The depth guard prevents pathological cases where an archive would
    recurse into itself indefinitely (e.g. a CPK with a self-referential
    entry). Reasonable depth is 8 -- ROM > NCCH > RomFS > GARC > .bin > LZ
    > inner CGFX > texture.
    """
    if depth > 8:
        logger.warning("recursion depth %d exceeded at %s", depth, path)
        return
    if len(data) < 4:
        return

    peek = classify_file(data, path)

    # --- Compression: decompress, fast-reject, then recurse -----------------
    if peek.detected_type and peek.detected_type.startswith("compressed:"):
        codec_name = peek.detected_type.split(":", 1)[1]
        result = try_decompress(data, hint=codec_name)
        if result is None:
            return
        if not _has_texture_payload(result.data):
            return
        # Strip a trailing .lz / .cmp from the path for cleaner inner names.
        inner_path = path
        for stripped in (".lz", ".cmp"):
            if inner_path.lower().endswith(stripped):
                inner_path = inner_path[:-len(stripped)]
                break
        yield from extract_textures(result.data, inner_path + "[decompressed]",
                                    title_id=title_id, scan_all=scan_all,
                                    depth=depth + 1)
        return

    # --- Archive: iterate inner files and recurse on each --------------------
    arch = detect_archive(data)
    if arch is not None:
        for entry in arch.plugin.iter_entries(data):
            if len(entry.data) < 4:
                continue
            inner_path = f"{path}>{entry.name}"
            yield from extract_textures(entry.data, inner_path,
                                        title_id=title_id, scan_all=scan_all,
                                        depth=depth + 1)
        return

    # --- Texture container: emit textures directly ---------------------------
    tex = detect_texture(data)
    if tex is not None:
        yield from tex.plugin.iter_textures(data, path)
        return

    # --- Embedded-magic scan (last resort, only when explicitly requested) ---
    if scan_all:
        yield from _scan_embedded(data, path)


def _scan_embedded(data: bytes, path: str) -> Iterator[Texture]:
    """Look for known texture magics embedded inside an unrecognized file.

    A weaker fallback than v1's full embedded scanner; we only do this when
    scan_all is True because false positives are common in 3D model data.
    """
    for magic in (b"CTPK", b"BCH\x00", b"CGFX"):
        idx = data.find(magic)
        if idx <= 0:
            continue
        sub = data[idx:idx + min(len(data) - idx, 4 * 1024 * 1024)]
        plugin = detect_texture(sub)
        if plugin is None:
            continue
        for tex in plugin.plugin.iter_textures(sub, f"{path}@embedded+0x{idx:X}"):
            tex.confidence = "low"  # embedded matches are inherently low-confidence
            yield tex
        break  # one magic at a time; stop after first hit
