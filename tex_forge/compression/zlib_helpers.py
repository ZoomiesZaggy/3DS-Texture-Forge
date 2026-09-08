"""zlib + gzip-with-prefix wrappers.

Some 3DS games (e.g. Smash Bros dt/ls resources) store raw zlib streams.
Others (Spike Chunsoft titles like Corpse Party) prefix gzip data with a
4-byte little-endian "decompressed size" -- so the first 6 bytes look like
[size:4 LE][1f 8b].

Both are registered as separate codecs.
"""

from __future__ import annotations

import gzip as _gzip
import logging
import zlib as _zlib
from typing import Optional

from tex_forge.compression.registry import register_compression

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Bare zlib stream
# ─────────────────────────────────────────────────────────────────────────────

# zlib magic = first byte 0x78 + a CMF byte from a small set.
# https://www.rfc-editor.org/rfc/rfc1950 (the FLEVEL field gives 4 valid CMF values)
_ZLIB_HEADERS = {b"\x78\x01", b"\x78\x5E", b"\x78\x9C", b"\x78\xDA"}


@register_compression("zlib", priority=40, note="raw zlib stream (used by Smash Bros dt/ls)")
class _Zlib:
    @staticmethod
    def detect(data: bytes) -> bool:
        return len(data) >= 2 and data[:2] in _ZLIB_HEADERS

    @staticmethod
    def decompress(data: bytes) -> Optional[bytes]:
        try:
            return _zlib.decompress(data)
        except _zlib.error:
            return None


# ─────────────────────────────────────────────────────────────────────────────
# 4-byte size prefix + gzip
# ─────────────────────────────────────────────────────────────────────────────

@register_compression("gzip_prefix", priority=50, note="size-prefixed gzip (Spike Chunsoft games)")
class _GzipPrefix:
    @staticmethod
    def detect(data: bytes) -> bool:
        return len(data) >= 6 and data[4:6] == b"\x1f\x8b"

    @staticmethod
    def decompress(data: bytes) -> Optional[bytes]:
        if len(data) < 6:
            return None
        try:
            return _gzip.decompress(data[4:])
        except Exception as e:
            logger.debug("gzip-prefix decompress failed: %s", e)
            return None
