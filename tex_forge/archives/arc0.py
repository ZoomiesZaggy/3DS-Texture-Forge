"""Level-5 ARC0 / XFSA -- Layton, Yo-Kai Watch, Layton vs PW.

Level-5's main archive format. Decoding the actual entry table requires
custom decompression of the metadata sections, which is fiddly -- the v1
codebase chose a pragmatic alternative that we keep here:

  Scan the data section for known texture-container magics (BCH / CGFX /
  CTPK / IMGC) and yield each found blob with a synthetic name. We also
  scan XPCK sub-containers for Level-5-style LZ10 headers (method byte
  encoded as `(val & 7) == 1`, decompressed size in `val >> 3`) and try
  to decompress those into texture containers too.

This trades some completeness (we miss IMGC / .xi files we can't decode
yet) for robustness across all Level-5 titles without per-game tuning.
"""

from __future__ import annotations

import logging
import struct
from typing import Iterator

from tex_forge.archives.registry import register_archive
from tex_forge.compression.lz_nintendo import decompress_lz
from tex_forge.core.types import ArchiveEntry

logger = logging.getLogger(__name__)

ARC0_MAGIC = b"ARC0"
XFSA_MAGIC = b"XFSA"
XPCK_MAGIC = b"XPCK"
_TEXTURE_MAGICS = (b"BCH\x00", b"CGFX", b"CTPK", b"IMGC")
_MIN_BLOB = 64


def _is_arc0(data: bytes) -> bool:
    return len(data) >= 8 and data[:4] in (ARC0_MAGIC, XFSA_MAGIC)


def _l5_lz10(data: bytes) -> bytes:
    """Try Level-5's own LZ10 header convention.

    First 4 bytes encode (method:3, decomp_size:29). Method 1 = standard LZ10
    bitstream. We rebuild a Nintendo LZ10 header and dispatch.
    """
    if len(data) < 8:
        return b""
    val = struct.unpack_from("<I", data, 0)[0]
    method = val & 7
    if method != 1:
        return b""
    dec_size = val >> 3
    if dec_size == 0 or dec_size > 16 * 1024 * 1024:
        return b""

    if dec_size <= 0xFFFFFF:
        hdr = bytes([0x10]) + struct.pack("<I", dec_size)[:3]
    else:
        hdr = bytes([0x10, 0x00, 0x00, 0x00]) + struct.pack("<I", dec_size)
    try:
        out = decompress_lz(hdr + data[4:])
        return out or b""
    except Exception:
        return b""


def _iter_blobs(data: bytes, base_off: int = 0) -> Iterator[ArchiveEntry]:
    for magic in _TEXTURE_MAGICS:
        offset = 0
        while offset < len(data) - len(magic):
            idx = data.find(magic, offset)
            if idx < 0:
                break

            remaining = len(data) - idx
            if magic == b"BCH\x00" and remaining >= 0x20:
                data_addr = struct.unpack_from("<I", data, idx + 0x14)[0]
                blob_size = (min(data_addr + 8 * 1024 * 1024, remaining)
                             if 0 < data_addr < remaining else min(remaining, 512 * 1024))
            elif magic == b"CTPK" and remaining >= 0x10:
                ctpk_size = struct.unpack_from("<I", data, idx + 0x08)[0]
                blob_size = (min(ctpk_size + 0x100, remaining)
                             if 0 < ctpk_size < remaining else min(remaining, 4 * 1024 * 1024))
            elif magic == b"CGFX" and remaining >= 0x10:
                cgfx_size = struct.unpack_from("<I", data, idx + 0x08)[0]
                blob_size = (min(cgfx_size + 0x100, remaining)
                             if 0 < cgfx_size < remaining else min(remaining, 4 * 1024 * 1024))
            elif magic == b"IMGC" and remaining >= 0x40:
                imgc_comp = struct.unpack_from("<I", data, idx + 0x3C)[0]
                blob_size = (min(0x48 + imgc_comp + 256, remaining)
                             if 0 < imgc_comp < remaining else min(remaining, 512 * 1024))
            else:
                blob_size = min(remaining, 4 * 1024 * 1024)

            if blob_size >= _MIN_BLOB:
                tag = magic.rstrip(b"\x00").decode("ascii", "replace")
                yield ArchiveEntry(
                    name=f"arc0@0x{base_off + idx:X}.{tag.lower()}",
                    data=bytes(data[idx:idx + blob_size]),
                )
            offset = idx + max(4, blob_size)


def _iter(data: bytes) -> Iterator[ArchiveEntry]:
    if not _is_arc0(data) or len(data) < 0x18:
        return

    header_size = struct.unpack_from("<I", data, 4)[0]
    data_offset = struct.unpack_from("<I", data, 0x14)[0]
    if data_offset == 0 or data_offset >= len(data):
        data_offset = header_size

    yield from _iter_blobs(data[data_offset:], base_off=data_offset)

    # XPCK sweeper: walk every XPCK header and probe for L5 LZ10 inside.
    offset = data_offset
    while offset < len(data) - 4:
        idx = data.find(XPCK_MAGIC, offset)
        if idx < 0:
            break
        nxt = data.find(XPCK_MAGIC, idx + 4)
        end = nxt if nxt > 0 else len(data)
        block = data[idx:end]

        # Try L5-style LZ10 at small offsets -- empirically 16..256.
        for lz_off in range(16, min(len(block) - 4, 256), 4):
            lz_val = struct.unpack_from("<I", block, lz_off)[0]
            if (lz_val & 7) != 1:
                continue
            dec_size = lz_val >> 3
            if not (256 < dec_size < 4 * 1024 * 1024):
                continue
            decompressed = _l5_lz10(block[lz_off:])
            if len(decompressed) < 64:
                continue
            for magic in _TEXTURE_MAGICS:
                if decompressed[:4] == magic:
                    tag = magic.rstrip(b"\x00").decode("ascii", "replace")
                    yield ArchiveEntry(
                        name=f"arc0>xpck@0x{idx:X}+0x{lz_off:X}.{tag.lower()}",
                        data=decompressed,
                    )
                    break
        offset = end


@register_archive("arc0", priority=70)
class _ARC0:
    @staticmethod
    def detect(data: bytes) -> bool:
        return _is_arc0(data)

    @staticmethod
    def iter_entries(data: bytes) -> Iterator[ArchiveEntry]:
        try:
            yield from _iter(data)
        except Exception as e:
            logger.warning("ARC0 parse error: %s", e)
