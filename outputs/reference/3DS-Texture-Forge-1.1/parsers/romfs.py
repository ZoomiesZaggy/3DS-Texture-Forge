"""RomFS (Read-Only Filesystem) parser for 3DS."""

import logging
from typing import List, Tuple, Optional
from utils import read_u32_le, read_string

logger = logging.getLogger(__name__)


class RomFSParser:
    """Parse 3DS RomFS filesystem."""

    def __init__(self, data: bytes):
        self.data = data
        self.files = []  # List of (path, offset, size)
        self._parse()

    def _parse(self):
        # RomFS starts with IVFC header
        magic = self.data[0x00:0x04]
        if magic != b'IVFC':
            raise ValueError(f"Invalid RomFS magic: {magic!r} (expected b'IVFC')")

        logger.info("Valid IVFC header found")

        # IVFC magic version check
        magic_number = read_u32_le(self.data, 0x04)
        logger.debug(f"IVFC magic number: 0x{magic_number:08X}")

        # Level 3 offset - for RomFS, the IVFC header tells us where level 3 is
        # The IVFC header is 0x5C bytes, and level 3 info is at specific offsets
        # Level 3 logical offset at 0x4C, Level 3 size at 0x50
        level3_offset_field = read_u32_le(self.data, 0x4C)
        level3_size = read_u32_le(self.data, 0x50)

        # The actual Level 3 data typically starts at offset 0x1000 in the RomFS blob
        # But we need to find it. Usually after the IVFC header, the master hash follows,
        # then the levels. Level 3 is the actual filesystem data.
        # Common approach: scan for the Level 3 header
        level3_start = self._find_level3()
        if level3_start is None:
            raise ValueError("Could not locate Level 3 data in RomFS")

        logger.info(f"Level 3 data starts at offset 0x{level3_start:X}")

        # Level 3 header
        l3 = level3_start
        header_size = read_u32_le(self.data, l3 + 0x00)
        dir_hash_offset = read_u32_le(self.data, l3 + 0x04) + l3
        dir_hash_size = read_u32_le(self.data, l3 + 0x08)
        dir_meta_offset = read_u32_le(self.data, l3 + 0x0C) + l3
        dir_meta_size = read_u32_le(self.data, l3 + 0x10)
        file_hash_offset = read_u32_le(self.data, l3 + 0x14) + l3
        file_hash_size = read_u32_le(self.data, l3 + 0x18)
        file_meta_offset = read_u32_le(self.data, l3 + 0x1C) + l3
        file_meta_size = read_u32_le(self.data, l3 + 0x20)
        file_data_offset = read_u32_le(self.data, l3 + 0x24) + l3

        logger.info(f"Dir meta: offset=0x{dir_meta_offset:X}, size=0x{dir_meta_size:X}")
        logger.info(f"File meta: offset=0x{file_meta_offset:X}, size=0x{file_meta_size:X}")
        logger.info(f"File data: offset=0x{file_data_offset:X}")

        self._file_data_base = file_data_offset

        # Parse directory tree
        self._parse_directories(dir_meta_offset, dir_meta_size,
                                file_meta_offset, file_meta_size,
                                file_data_offset)

        logger.info(f"Found {len(self.files)} files in RomFS")

    def _find_level3(self) -> Optional[int]:
        """Find the start of Level 3 data in the RomFS."""
        # Level 3 is typically at offset 0x1000, but can vary
        # The Level 3 header starts with its own header length (usually 0x28)
        for candidate in [0x1000, 0x2000, 0x3000, 0x4000]:
            if candidate + 0x28 <= len(self.data):
                header_len = read_u32_le(self.data, candidate)
                if header_len == 0x28:
                    # Sanity check: dir hash table offset should be small
                    dir_hash_off = read_u32_le(self.data, candidate + 0x04)
                    if dir_hash_off < 0x100000:
                        return candidate

        # Fallback: try scanning
        # The IVFC header at offset 0 has level sizes
        # Level 1 offset = 0x60 (right after IVFC header, aligned)
        # We can compute from IVFC fields
        try:
            # IVFC level info: each level has (logical_offset, hash_data_size)
            # at offsets 0x0C, 0x14 for level 1; 0x1C, 0x24 for level 2; etc.
            # The master hash size is at offset 0x08
            master_hash_size = read_u32_le(self.data, 0x08)

            # Level 1: offset 0x2C (data size), 0x30 (block size as log2)
            lv1_data_size = read_u32_le(self.data, 0x2C)
            # Level 2: offset 0x3C (data size)
            lv2_data_size = read_u32_le(self.data, 0x3C)
            # Level 3: offset 0x4C (data size)
            lv3_data_size = read_u32_le(self.data, 0x4C)

            # Compute actual offsets
            # After IVFC header (0x5C bytes), aligned to 0x10
            ivfc_header_end = 0x60

            # Master hash region
            master_hash_end = ivfc_header_end + master_hash_size

            # Level 1 starts after master hash, aligned to block size
            def align_up(v, a):
                return (v + a - 1) & ~(a - 1)

            lv1_start = align_up(master_hash_end, 0x1000)
            lv2_start = align_up(lv1_start + lv1_data_size, 0x1000)
            lv3_start = align_up(lv2_start + lv2_data_size, 0x1000)

            if lv3_start + 0x28 <= len(self.data):
                header_len = read_u32_le(self.data, lv3_start)
                if header_len == 0x28:
                    return lv3_start
        except Exception:
            pass

        return None

    def _parse_directories(self, dir_meta_offset: int, dir_meta_size: int,
                           file_meta_offset: int, file_meta_size: int,
                           file_data_offset: int):
        """Iteratively parse directory and file metadata tables."""
        self._visited_dirs = set()
        self._visited_files = set()

        # BFS through directories starting from root (offset 0)
        dir_queue = [(0, "")]  # (dir_entry_offset, parent_path)

        while dir_queue:
            dir_entry_offset, parent_path = dir_queue.pop(0)

            if dir_entry_offset in self._visited_dirs:
                continue
            self._visited_dirs.add(dir_entry_offset)

            abs_offset = dir_meta_offset + dir_entry_offset
            if abs_offset + 0x18 > len(self.data):
                continue

            first_child_dir = read_u32_le(self.data, abs_offset + 0x08)
            first_file = read_u32_le(self.data, abs_offset + 0x0C)
            name_len = read_u32_le(self.data, abs_offset + 0x14)

            if dir_entry_offset == 0:
                dir_name = ""
            else:
                if name_len > 1024:
                    continue
                name_data = self.data[abs_offset + 0x18:abs_offset + 0x18 + name_len]
                dir_name = name_data.decode('utf-16-le', errors='replace')

            current_path = f"{parent_path}/{dir_name}" if dir_name else parent_path

            # Process files in this directory
            if first_file != 0xFFFFFFFF:
                self._walk_files_iter(file_meta_offset, first_file,
                                      file_data_offset, current_path)

            # Queue child directories
            if first_child_dir != 0xFFFFFFFF and first_child_dir not in self._visited_dirs:
                dir_queue.append((first_child_dir, current_path))

            # Queue sibling directories
            sibling = read_u32_le(self.data, abs_offset + 0x04)
            if sibling != 0xFFFFFFFF and sibling not in self._visited_dirs:
                dir_queue.append((sibling, parent_path))

    def _walk_files_iter(self, file_meta_base: int, file_entry_offset: int,
                         file_data_offset: int, dir_path: str):
        """Iteratively walk file entries in a directory (no recursion)."""
        current_offset = file_entry_offset

        while current_offset != 0xFFFFFFFF:
            if current_offset in self._visited_files:
                break
            self._visited_files.add(current_offset)

            abs_offset = file_meta_base + current_offset
            if abs_offset + 0x20 > len(self.data):
                break

            sibling = read_u32_le(self.data, abs_offset + 0x04)
            data_offset_rel = int.from_bytes(self.data[abs_offset + 0x08:abs_offset + 0x10], 'little')
            data_size = int.from_bytes(self.data[abs_offset + 0x10:abs_offset + 0x18], 'little')
            name_len = read_u32_le(self.data, abs_offset + 0x1C)

            if name_len > 1024:
                break

            name_data = self.data[abs_offset + 0x20:abs_offset + 0x20 + name_len]
            file_name = name_data.decode('utf-16-le', errors='replace')

            file_path = f"{dir_path}/{file_name}" if dir_path else file_name
            abs_data_offset = file_data_offset + data_offset_rel

            self.files.append((file_path, abs_data_offset, data_size))
            logger.debug(f"File: {file_path} (offset=0x{abs_data_offset:X}, size={data_size})")

            current_offset = sibling

    def list_files(self) -> List[Tuple[str, int, int]]:
        """Return list of (path, offset, size) for all files."""
        return self.files

    def read_file(self, path: str) -> bytes:
        """Read a file by its path."""
        for fpath, offset, size in self.files:
            if fpath == path:
                end = min(offset + size, len(self.data))
                return self.data[offset:end]
        raise FileNotFoundError(f"File not found in RomFS: {path}")

    def read_file_by_index(self, index: int) -> Tuple[str, bytes]:
        """Read a file by its index. Returns (path, data)."""
        if index < 0 or index >= len(self.files):
            raise IndexError(f"File index {index} out of range")
        path, offset, size = self.files[index]
        end = min(offset + size, len(self.data))
        return path, self.data[offset:end]
