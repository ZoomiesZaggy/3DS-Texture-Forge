"""CIA (CTR Importable Archive) parser."""

import logging
from utils import read_u32_le, read_u16_le, align

logger = logging.getLogger(__name__)


class CIAParser:
    """Parse CIA installable title format."""

    def __init__(self, data: bytes):
        self.data = data
        self._parse()

    def _parse(self):
        # CIA header
        self.header_size = read_u32_le(self.data, 0x00)
        self.type = read_u16_le(self.data, 0x04)
        self.version = read_u16_le(self.data, 0x06)
        self.cert_size = read_u32_le(self.data, 0x08)
        self.ticket_size = read_u32_le(self.data, 0x0C)
        self.tmd_size = read_u32_le(self.data, 0x10)
        self.meta_size = read_u32_le(self.data, 0x14)
        self.content_size = read_u32_le(self.data, 0x18)  # Low 32 bits
        # Content size can be 64-bit, read high 32 bits too
        content_size_high = read_u32_le(self.data, 0x1C)
        self.content_size |= (content_size_high << 32)

        logger.info(f"CIA header: header={self.header_size}, cert={self.cert_size}, "
                     f"ticket={self.ticket_size}, tmd={self.tmd_size}, "
                     f"content={self.content_size}")

        # Calculate section offsets (each section aligned to 64 bytes)
        offset = align(self.header_size, 64)
        self.cert_offset = offset

        offset = align(offset + self.cert_size, 64)
        self.ticket_offset = offset

        offset = align(offset + self.ticket_size, 64)
        self.tmd_offset = offset

        offset = align(offset + self.tmd_size, 64)
        self.content_offset = offset

        logger.info(f"Content starts at offset 0x{self.content_offset:X}")

        # Parse TMD to find content count
        self._parse_tmd()

    def _parse_tmd(self):
        """Parse the Title Metadata to find content info."""
        tmd = self.data[self.tmd_offset:self.tmd_offset + self.tmd_size]

        # TMD signature type at offset 0
        sig_type = read_u32_le(tmd, 0x00)

        # Determine signature size based on type
        sig_sizes = {
            0x00010003: 0x200 + 0x3C,  # RSA_4096_SHA256
            0x00010004: 0x100 + 0x3C,  # RSA_2048_SHA256
            0x00010005: 0x3C + 0x40,   # ECDSA_SHA256
            0x03000300: 0x200 + 0x3C,  # RSA_4096_SHA256 (big endian variant)
            0x04000100: 0x100 + 0x3C,  # RSA_2048_SHA256 (big endian variant)
        }

        # Try both endiannesses for the signature type
        sig_type_be = int.from_bytes(tmd[0:4], 'big')
        if sig_type in sig_sizes:
            header_start = 4 + sig_sizes[sig_type]
        elif sig_type_be in sig_sizes:
            header_start = 4 + sig_sizes[sig_type_be]
        else:
            # Default: RSA-2048 is most common
            header_start = 4 + 0x100 + 0x3C
            logger.warning(f"Unknown TMD signature type 0x{sig_type:08X}, assuming RSA-2048")

        # Content count at header_start + 0x9E (in the TMD header)
        if header_start + 0x9E + 2 <= len(tmd):
            self.content_count = int.from_bytes(tmd[header_start + 0x9E:header_start + 0xA0], 'big')
        else:
            self.content_count = 1
            logger.warning("Could not read content count from TMD, assuming 1")

        logger.info(f"TMD content count: {self.content_count}")

    def get_content(self, index: int = 0) -> bytes:
        """Extract content by index (default: content 0 = main NCCH)."""
        if index != 0:
            raise ValueError("Only content 0 extraction is currently supported")

        # Content 0 starts at self.content_offset
        # For content 0, we read until content_size or end of data
        end = min(self.content_offset + self.content_size, len(self.data))
        content = self.data[self.content_offset:end]

        if len(content) == 0:
            raise ValueError("Content 0 is empty")

        logger.info(f"Extracted content 0: {len(content)} bytes")
        return content
