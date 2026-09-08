"""RomFS (Read-Only Filesystem) parser for 3DS NCCH partitions.

Format: https://www.3dbrew.org/wiki/RomFS

A RomFS blob is wrapped in an IVFC hash-tree container. Inside, three levels
of hash data sit before the actual filesystem (Level 3). Level 3 contains:

    0x00  header_length (always 0x28)
    0x04  dir_hash_table_offset / size
    0x0C  dir_meta_offset / size
    0x14  file_hash_table_offset / size
    0x1C  file_meta_offset / size
    0x24  file_data_offset

Directory and file metadata form a tree linked by sibling/child pointers.
Names are UTF-16LE.

We BFS-walk the tree once at parse time, building a flat list of
(path, abs_offset, size) tuples. read_file_by_index then becomes a slice.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from tex_forge.core.binio import (
    align_up,
    read_u32_le,
    read_utf16le,
    safe_slice,
)
from tex_forge.core.exceptions import ROMParseError

logger = logging.getLogger(__name__)

_END = 0xFFFFFFFF


class RomFSParser:
    """Walk a RomFS into a flat (path, offset, size) file list.

    Memory note: this parser keeps a reference to *data* (the RomFS blob)
    because read_file_by_index slices into it. For a fresh-from-disk RomFS
    the blob can be 1-2 GB; that's fine on 64-bit but be aware.
    """

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.files: List[Tuple[str, int, int]] = []
        self._parse()

    # ── public API ──────────────────────────────────────────────────────

    def list_files(self) -> List[Tuple[str, int, int]]:
        return self.files

    def read_file(self, path: str) -> bytes:
        for fpath, offset, size in self.files:
            if fpath == path:
                return safe_slice(self.data, offset, size)
        raise FileNotFoundError(f"Not in RomFS: {path}")

    def read_file_by_index(self, index: int) -> Tuple[str, bytes]:
        if not (0 <= index < len(self.files)):
            raise IndexError(f"RomFS file index {index} out of range")
        path, offset, size = self.files[index]
        return path, safe_slice(self.data, offset, size)

    # ── internals ───────────────────────────────────────────────────────

    def _parse(self) -> None:
        if self.data[0:4] != b"IVFC":
            raise ROMParseError(f"Bad RomFS magic: {self.data[0:4]!r}")

        l3 = self._find_level3()
        if l3 is None:
            raise ROMParseError("RomFS Level 3 not found")
        logger.info("RomFS Level 3 starts at 0x%X", l3)

        dir_meta_off  = read_u32_le(self.data, l3 + 0x0C) + l3
        dir_meta_size = read_u32_le(self.data, l3 + 0x10)
        file_meta_off = read_u32_le(self.data, l3 + 0x1C) + l3
        file_data_off = read_u32_le(self.data, l3 + 0x24) + l3

        self._walk(dir_meta_off, file_meta_off, file_data_off)
        logger.info("RomFS: indexed %d files", len(self.files))

    def _find_level3(self) -> Optional[int]:
        """Locate the Level 3 partition.

        The IVFC header is 0x5C bytes; afterwards the master hash, level 1
        hashes, level 2 hashes, then level 3 (the actual filesystem) live at
        block-aligned offsets. In practice level 3 is almost always at one
        of {0x1000, 0x2000, 0x3000, 0x4000}; we fall back to a header-driven
        computation for the rare exception.
        """
        for cand in (0x1000, 0x2000, 0x3000, 0x4000):
            if cand + 0x28 <= len(self.data):
                if read_u32_le(self.data, cand) == 0x28:
                    # Sanity: the dir-hash table offset should be small.
                    if read_u32_le(self.data, cand + 0x04) < 0x100000:
                        return cand

        try:
            master_hash_size = read_u32_le(self.data, 0x08)
            lv1_data_size = read_u32_le(self.data, 0x2C)
            lv2_data_size = read_u32_le(self.data, 0x3C)
            ivfc_end = 0x60
            master_end = ivfc_end + master_hash_size
            lv1 = align_up(master_end, 0x1000)
            lv2 = align_up(lv1 + lv1_data_size, 0x1000)
            lv3 = align_up(lv2 + lv2_data_size, 0x1000)
            if lv3 + 0x28 <= len(self.data) and read_u32_le(self.data, lv3) == 0x28:
                return lv3
        except Exception:
            pass
        return None

    def _walk(self, dir_meta_off: int, file_meta_off: int, file_data_off: int) -> None:
        """BFS the directory tree, collecting files."""
        seen_dirs: set[int] = set()
        seen_files: set[int] = set()
        # (dir_entry_offset, parent_path)
        queue: list[Tuple[int, str]] = [(0, "")]

        while queue:
            entry_off, parent = queue.pop(0)
            if entry_off in seen_dirs:
                continue
            seen_dirs.add(entry_off)

            abs_off = dir_meta_off + entry_off
            if abs_off + 0x18 > len(self.data):
                continue

            sibling_dir   = read_u32_le(self.data, abs_off + 0x04)
            first_child   = read_u32_le(self.data, abs_off + 0x08)
            first_file    = read_u32_le(self.data, abs_off + 0x0C)
            name_len      = read_u32_le(self.data, abs_off + 0x14)

            if entry_off == 0:
                dir_name = ""
            else:
                if name_len > 1024:
                    continue
                dir_name = read_utf16le(self.data, abs_off + 0x18, name_len)

            current_path = f"{parent}/{dir_name}" if dir_name else parent

            if first_file != _END:
                self._walk_files(file_meta_off, first_file, file_data_off, current_path, seen_files)

            if first_child != _END and first_child not in seen_dirs:
                queue.append((first_child, current_path))
            if sibling_dir != _END and sibling_dir not in seen_dirs:
                queue.append((sibling_dir, parent))

    def _walk_files(
        self,
        file_meta_base: int,
        first_offset: int,
        file_data_off: int,
        dir_path: str,
        seen: set[int],
    ) -> None:
        offset = first_offset
        while offset != _END:
            if offset in seen:
                break
            seen.add(offset)

            abs_off = file_meta_base + offset
            if abs_off + 0x20 > len(self.data):
                break

            sibling = read_u32_le(self.data, abs_off + 0x04)
            data_off = int.from_bytes(self.data[abs_off + 0x08:abs_off + 0x10], "little")
            data_size = int.from_bytes(self.data[abs_off + 0x10:abs_off + 0x18], "little")
            name_len = read_u32_le(self.data, abs_off + 0x1C)

            if name_len > 1024:
                break
            file_name = read_utf16le(self.data, abs_off + 0x20, name_len)
            path = f"{dir_path}/{file_name}" if dir_path else file_name

            self.files.append((path, file_data_off + data_off, data_size))
            offset = sibling
