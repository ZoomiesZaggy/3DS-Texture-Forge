"""NCSD (.3ds cartridge dump) parser.

Format: https://www.3dbrew.org/wiki/NCSD

Layout:
    0x000  signature (RSA-2048, ignored for our purposes)
    0x100  "NCSD" magic
    0x104  image size (in 0x200-byte media units)
    0x108  title ID (u64 LE)
    0x120  partition table -- 8 entries of (offset, size) in media units

Partition 0 is the game executable / RomFS container (an NCCH).
Partitions 1-7 are usually update / manual / DLP child contents.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List

from tex_forge.core.binio import (
    MEDIA_UNIT,
    memcmp_at,
    read_u32_le,
    read_u64_le,
    safe_slice,
)
from tex_forge.core.exceptions import ROMParseError

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _Partition:
    index: int
    offset: int
    size: int


class NCSDParser:
    """Parse an NCSD cartridge dump and expose its 8 partitions."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.title_id: int = 0
        self.image_size: int = 0
        self.partitions: List[_Partition] = []
        self._parse()

    def _parse(self) -> None:
        if not memcmp_at(self.data, 0x100, b"NCSD"):
            raise ROMParseError(f"Bad NCSD magic at 0x100: {self.data[0x100:0x104]!r}")

        self.image_size = read_u32_le(self.data, 0x104) * MEDIA_UNIT
        self.title_id = read_u64_le(self.data, 0x108)
        logger.info("NCSD title_id=%016X", self.title_id)

        # 8 partition entries at 0x120, 8 bytes each.
        for i in range(8):
            entry = 0x120 + i * 8
            off = read_u32_le(self.data, entry) * MEDIA_UNIT
            sz = read_u32_le(self.data, entry + 4) * MEDIA_UNIT
            if sz > 0:
                self.partitions.append(_Partition(i, off, sz))
                logger.debug("NCSD partition %d: off=0x%X size=0x%X", i, off, sz)

        if not self.partitions:
            raise ROMParseError("NCSD has zero partitions")

    def get_partition(self, index: int = 0) -> bytes:
        """Return raw bytes of the requested partition (default: 0 = game NCCH)."""
        for p in self.partitions:
            if p.index == index:
                return safe_slice(self.data, p.offset, p.size)
        raise ROMParseError(f"NCSD partition {index} not present")
