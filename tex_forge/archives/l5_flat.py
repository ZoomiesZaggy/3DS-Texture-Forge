"""Level-5 flat-file archive (Fantasy Life and friends).

Format:
    +0x00 entry_count u32
    +0x04 padding (0)
    +0x08 entry_count * u32  -- absolute file offsets
    Each entry's size = next_offset - this_offset, last entry runs to EOF.

Most entries are LZ11-compressed; the pipeline scanner re-runs on each
decompressed chunk to find CGFX/BCH/CTPK inside.
"""

from __future__ import annotations

import logging
import struct
from typing import Iterator

from tex_forge.archives.registry import register_archive
from tex_forge.core.types import ArchiveEntry

logger = logging.getLogger(__name__)

_MAX_ENTRY = 50 * 1024 * 1024
_MAX_ENTRIES = 200_000

# Texture container magics that Level-5 entries carry, either at the start of a
# decompressed entry or embedded a little way in (Level-5 wraps the real
# container inside a resource header, e.g. CGFX at +0x100 / +0x180). This is the
# exact set the v1 extractor scanned for; matching it reproduces v1's counts.
_TEX_CONTAINER_MAGICS = (b"BCH\x00", b"CGFX", b"CTPK", b"CTXB")
# Level-5 resource headers put the container within the first few hundred bytes;
# v1 scanned the first 0x1000 and that was sufficient for Fantasy Life.
_EMBED_SCAN_LIMIT = 0x1000
# Raw Nintendo LZ stream leading bytes (LZ10 / LZ11 / LZ13-extended).
_LZ_LEAD_BYTES = (0x10, 0x11, 0x13)


def _is_l5_flat(data: bytes) -> bool:
    if len(data) < 16:
        return False
    if struct.unpack_from("<I", data, 4)[0] != 0:
        return False
    n = struct.unpack_from("<I", data, 0)[0]
    if not (10 <= n <= _MAX_ENTRIES):
        return False
    table_end = 8 + n * 4
    if table_end > len(data):
        return False
    first = struct.unpack_from("<I", data, 8)[0]
    return table_end <= first < len(data)


def _iter(data: bytes) -> Iterator[ArchiveEntry]:
    if not _is_l5_flat(data):
        return
    n = struct.unpack_from("<I", data, 0)[0]

    offsets = []
    for i in range(n):
        eo = 8 + i * 4
        if eo + 4 > len(data):
            break
        offsets.append(struct.unpack_from("<I", data, eo)[0])
    if not offsets:
        return

    for i, start in enumerate(offsets):
        end = offsets[i + 1] if i + 1 < len(offsets) else len(data)
        size = end - start
        if size <= 0 or start >= len(data) or size > _MAX_ENTRY:
            continue
        yield ArchiveEntry(name=f"entry_{i:05d}.bin", data=bytes(data[start:start + size]))


def _entry_to_container(name: str, raw: bytes) -> ArchiveEntry:
    """Turn one raw flat-archive entry into a texture-container entry.

    Level-5 entries are usually raw-Nintendo-LZ compressed and, once
    decompressed, hold a texture container either at offset 0 or embedded a few
    hundred bytes in behind a resource header. The v1 pipeline decompressed each
    entry and scanned the first 0x1000 bytes for CGFX/BCH/CTPK/CTXB; the v2
    refactor dropped that scan (the generic scanner only probes for embedded
    magics under --scan-all), which is why Fantasy Life regressed to 0 textures.
    This restores it inside the archive plugin so the yielded entry starts on a
    container the texture dispatch already understands.

    Returns the container entry, or None if this entry carries no texture.
    """
    if len(raw) < 8:
        return None

    work = raw
    suffix = ""
    if raw[0] in _LZ_LEAD_BYTES:
        # Lazy import: avoids an archives -> compression import cycle at load.
        from tex_forge.compression import try_decompress
        try:
            res = try_decompress(raw)
        except Exception:
            res = None
        if res is not None and res.data and len(res.data) >= 8:
            work = res.data
            suffix = "[lz]"

    # Direct container at the start of the (decompressed) entry.
    if work[:4] in _TEX_CONTAINER_MAGICS:
        return ArchiveEntry(name=f"{name}{suffix}", data=bytes(work))

    # Container embedded behind a Level-5 resource header. Scan the first
    # 0x1000 bytes on 4-byte boundaries and take the first hit (as v1 did).
    limit = min(len(work) - 4, _EMBED_SCAN_LIMIT)
    off = 0
    while off < limit:
        if work[off:off + 4] in _TEX_CONTAINER_MAGICS:
            return ArchiveEntry(name=f"{name}{suffix}[+0x{off:X}]",
                                data=bytes(work[off:]))
        off += 4
    return None


@register_archive("l5_flat", priority=55, note="Level-5 flat archive (Fantasy Life)")
class _L5Flat:
    @staticmethod
    def detect(data: bytes) -> bool:
        return _is_l5_flat(data)

    @staticmethod
    def iter_entries(data: bytes) -> Iterator[ArchiveEntry]:
        try:
            for raw_entry in _iter(data):
                container = _entry_to_container(raw_entry.name, raw_entry.data)
                if container is not None:
                    yield container
        except Exception as e:
            logger.warning("Level-5 flat parse error: %s", e)
