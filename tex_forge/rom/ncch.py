"""NCCH (Nintendo Content Container Header) parser.

Format: https://www.3dbrew.org/wiki/NCCH

Layout:
    0x000  signature (RSA-2048, ignored)
    0x100  "NCCH" magic
    0x104  content size (in 0x200-byte media units)
    0x108  title ID
    0x150  product code (16 byte ASCII, e.g. "CTR-P-AGKE")
    0x18B  crypto method
    0x18F  flags[7]: bit2 (0x04) = NoCrypto. ENCRYPTED iff bit2 is CLEAR.
    0x1A0  ExeFS offset (media units)
    0x1A4  ExeFS size
    0x1B0  RomFS offset (media units)
    0x1B4  RomFS size

This parser raises EncryptedROMError when the partition is encrypted, so the
CLI can show its GodMode9 decryption hint.
"""

from __future__ import annotations

import logging

from tex_forge.core.binio import (
    MEDIA_UNIT,
    memcmp_at,
    read_cstring,
    read_u8,
    read_u32_le,
    read_u64_le,
    safe_slice,
)
from tex_forge.core.exceptions import EncryptedROMError, ROMParseError

logger = logging.getLogger(__name__)


class NCCHParser:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.title_id: int = 0
        self.product_code: str = ""
        self.is_encrypted: bool = False
        self.exefs_offset: int = 0
        self.exefs_size: int = 0
        self.romfs_offset: int = 0
        self.romfs_size: int = 0
        self._parse()

    def _parse(self) -> None:
        if not memcmp_at(self.data, 0x100, b"NCCH"):
            raise ROMParseError(f"Bad NCCH magic at 0x100: {self.data[0x100:0x104]!r}")

        self.title_id = read_u64_le(self.data, 0x108)
        self.product_code = read_cstring(self.data, 0x150, max_len=16)

        flags7 = read_u8(self.data, 0x18F)
        # Bit 2 set => NoCrypto. So encrypted = NOT(bit2).
        self.is_encrypted = not bool(flags7 & 0x04)

        self.exefs_offset = read_u32_le(self.data, 0x1A0) * MEDIA_UNIT
        self.exefs_size   = read_u32_le(self.data, 0x1A4) * MEDIA_UNIT
        self.romfs_offset = read_u32_le(self.data, 0x1B0) * MEDIA_UNIT
        self.romfs_size   = read_u32_le(self.data, 0x1B4) * MEDIA_UNIT

        logger.info(
            "NCCH title=%016X product=%s romfs=0x%X..0x%X exefs=0x%X..0x%X enc=%s",
            self.title_id, self.product_code,
            self.romfs_offset, self.romfs_offset + self.romfs_size,
            self.exefs_offset, self.exefs_offset + self.exefs_size,
            self.is_encrypted,
        )

    def _check_decrypted(self) -> None:
        if self.is_encrypted:
            raise EncryptedROMError(
                "ROM partition is encrypted. Decrypt with GodMode9 first: "
                "https://3ds.hacks.guide/godmode9-usage.html"
            )

    def get_romfs(self) -> bytes:
        self._check_decrypted()
        if self.romfs_offset == 0 or self.romfs_size == 0:
            raise ROMParseError("NCCH has no RomFS")
        return safe_slice(self.data, self.romfs_offset, self.romfs_size)

    def get_exefs(self) -> bytes:
        self._check_decrypted()
        if self.exefs_offset == 0 or self.exefs_size == 0:
            raise ROMParseError("NCCH has no ExeFS")
        return safe_slice(self.data, self.exefs_offset, self.exefs_size)
