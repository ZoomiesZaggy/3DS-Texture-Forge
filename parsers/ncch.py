"""NCCH (Nintendo Content Container Header) parser."""

import logging
from utils import read_u32_le, read_u64_le, read_u16_le, read_u8, read_string, MEDIA_UNIT

logger = logging.getLogger(__name__)


class NCCHParser:
    """Parse NCCH game container format."""

    def __init__(self, data: bytes):
        self.data = data
        self._parse()

    def _parse(self):
        # NCCH magic at offset 0x100
        magic = self.data[0x100:0x104]
        if magic != b'NCCH':
            raise ValueError(f"Invalid NCCH magic: {magic!r} (expected b'NCCH')")

        logger.info("Valid NCCH header found")

        # Content size in media units
        self.content_size = read_u32_le(self.data, 0x104) * MEDIA_UNIT

        # Title ID
        self.title_id = read_u64_le(self.data, 0x108)
        logger.info(f"Title ID: {self.title_id:016X}")

        # Product code (offset 0x150, 16 bytes)
        self.product_code = self.data[0x150:0x160].split(b'\x00')[0].decode('ascii', errors='replace')
        logger.info(f"Product code: {self.product_code}")

        # Encryption flags
        self.crypto_method = read_u8(self.data, 0x18B)
        self.flags_index_7 = read_u8(self.data, 0x18F)
        self.is_encrypted = not bool(self.flags_index_7 & 0x04)  # Bit 2 = NoCrypto

        if self.is_encrypted:
            logger.warning("ROM appears to be encrypted!")

        # ExeFS offset and size (in media units)
        self.exefs_offset = read_u32_le(self.data, 0x1A0) * MEDIA_UNIT
        self.exefs_size = read_u32_le(self.data, 0x1A4) * MEDIA_UNIT

        # RomFS offset and size (in media units)
        self.romfs_offset = read_u32_le(self.data, 0x1B0) * MEDIA_UNIT
        self.romfs_size = read_u32_le(self.data, 0x1B4) * MEDIA_UNIT

        logger.info(f"ExeFS: offset=0x{self.exefs_offset:X}, size=0x{self.exefs_size:X}")
        logger.info(f"RomFS: offset=0x{self.romfs_offset:X}, size=0x{self.romfs_size:X}")

    def check_encryption(self):
        """Check if ROM is encrypted and raise an error if so."""
        if self.is_encrypted:
            raise RuntimeError(
                "ERROR: ROM is encrypted. Please decrypt with GodMode9 first.\n"
                "See: https://3ds.hacks.guide/godmode9-usage.html"
            )

    def get_romfs(self) -> bytes:
        """Extract the RomFS blob."""
        self.check_encryption()

        if self.romfs_offset == 0 or self.romfs_size == 0:
            raise ValueError("No RomFS found in NCCH")

        end = self.romfs_offset + self.romfs_size
        if end > len(self.data):
            logger.warning(
                f"RomFS extends beyond data (offset=0x{self.romfs_offset:X}, "
                f"size=0x{self.romfs_size:X}, data_len=0x{len(self.data):X}). Truncating."
            )
            end = len(self.data)

        romfs = self.data[self.romfs_offset:end]
        logger.info(f"Extracted RomFS: {len(romfs)} bytes")
        return romfs

    def get_exefs(self) -> bytes:
        """Extract the ExeFS blob."""
        self.check_encryption()

        if self.exefs_offset == 0 or self.exefs_size == 0:
            raise ValueError("No ExeFS found in NCCH")

        end = self.exefs_offset + self.exefs_size
        if end > len(self.data):
            end = len(self.data)

        return self.data[self.exefs_offset:end]
