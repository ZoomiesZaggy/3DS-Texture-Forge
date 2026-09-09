"""NCSD (.3ds) cartridge dump parser."""

import logging
from utils import read_u32_le, read_u64_le, read_string, MEDIA_UNIT

logger = logging.getLogger(__name__)


class NCSDParser:
    """Parse NCSD (raw cartridge dump) format."""

    def __init__(self, data: bytes):
        self.data = data
        self.partitions = []
        self._parse()

    def _parse(self):
        # NCSD magic at offset 0x100
        magic = self.data[0x100:0x104]
        if magic != b'NCSD':
            raise ValueError(f"Invalid NCSD magic: {magic!r} (expected b'NCSD')")

        logger.info("Valid NCSD header found")

        # Image size in media units
        self.image_size = read_u32_le(self.data, 0x104) * MEDIA_UNIT

        # Title ID
        self.title_id = read_u64_le(self.data, 0x108)
        logger.info(f"Title ID: {self.title_id:016X}")

        # Parse 8 partition entries starting at offset 0x120
        # Each entry is 8 bytes: 4 bytes offset (media units) + 4 bytes size (media units)
        for i in range(8):
            entry_offset = 0x120 + i * 8
            part_offset = read_u32_le(self.data, entry_offset) * MEDIA_UNIT
            part_size = read_u32_le(self.data, entry_offset + 4) * MEDIA_UNIT

            if part_size > 0:
                logger.info(f"Partition {i}: offset=0x{part_offset:X}, size=0x{part_size:X}")
                self.partitions.append({
                    'index': i,
                    'offset': part_offset,
                    'size': part_size,
                })

        if not self.partitions:
            raise ValueError("No partitions found in NCSD")

    def get_partition(self, index: int = 0) -> bytes:
        """Extract a partition (default: partition 0 = game content)."""
        for part in self.partitions:
            if part['index'] == index:
                offset = part['offset']
                size = part['size']
                if offset + size > len(self.data):
                    logger.warning(
                        f"Partition {index} extends beyond file "
                        f"(offset=0x{offset:X}, size=0x{size:X}, file_len=0x{len(self.data):X}). "
                        f"Truncating."
                    )
                    size = len(self.data) - offset
                return self.data[offset:offset + size]
        raise ValueError(f"Partition {index} not found")
