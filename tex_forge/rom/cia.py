"""CIA (CTR Importable Archive) parser.

Format: https://www.3dbrew.org/wiki/CIA

A CIA bundles a header, certificate chain, ticket, TMD (title metadata), the
content (one or more NCCH/CFA blobs), and an optional metadata blob. Each of
those top-level sections is aligned to a 64-byte boundary.

Within the content region, each content is ALSO aligned to a 64-byte block:
if a content ends mid-block, the next one starts on a fresh block. That detail
matters once a title carries more than content 0 -- updates ship a patched
RomFS, and DLC ships extra CFA contents, both of which hold textures we want.

We parse the TMD's content chunk records to recover every content's index,
type flag and size, then expose them via `get_content(i)` / `iter_contents()`.
Signatures are not validated; sizes/offsets are all we need.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterator, List

from tex_forge.core.binio import (
    align_up,
    read_u16_le,
    read_u32_le,
    safe_slice,
)
from tex_forge.core.exceptions import ROMParseError

logger = logging.getLogger(__name__)

# CIA header length is fixed at 0x2020, but we read it from the header itself.
_ALIGN = 64

# TMD layout constants (sizes in bytes), from
# https://www.3dbrew.org/wiki/Title_metadata
_TMD_HEADER_SIZE   = 0xC4    # signed header
_TMD_INFO_RECORDS  = 0x900   # 64 content-info records x 0x24
_CHUNK_RECORD_SIZE = 0x30    # one per content
_CONTENT_COUNT_OFF = 0x9E    # u16 BE, within the TMD header
_CHUNKS_OFF        = _TMD_HEADER_SIZE + _TMD_INFO_RECORDS  # 0x9C4 from header

# Content type bit flags (chunk record offset 0x06, u16 BE).
_TYPE_ENCRYPTED = 0x0001
_TYPE_OPTIONAL  = 0x4000   # DLC / optional content

# TMD signature type -> (signature_size + padding) mapping. The sig blob
# (type word + signature + padding) is aligned to 0x40; the size depends on
# the RSA key length, not the hash, so SHA-1 and SHA-256 variants pair up.
# https://www.3dbrew.org/wiki/Title_metadata#Signature_Data
_SIG_SIZES = {
    0x00010000: 0x200 + 0x3C,  # RSA-4096 SHA-1
    0x00010001: 0x100 + 0x3C,  # RSA-2048 SHA-1
    0x00010003: 0x200 + 0x3C,  # RSA-4096 SHA-256
    0x00010004: 0x100 + 0x3C,  # RSA-2048 SHA-256
    0x00010005: 0x3C  + 0x40,  # ECDSA SHA-256
    0x03000300: 0x200 + 0x3C,  # legacy big-endian variant
    0x04000100: 0x100 + 0x3C,
}


@dataclass(frozen=True)
class CIAContent:
    """One content entry resolved from the TMD chunk records."""
    chunk_index: int   # position in the chunk table (0-based)
    content_id: int    # TMD Content ID
    content_index: int # TMD Content Index field
    type_flags: int    # raw u16 type flags
    offset: int        # absolute byte offset into the CIA file
    size: int          # content size in bytes

    @property
    def encrypted(self) -> bool:
        return bool(self.type_flags & _TYPE_ENCRYPTED)

    @property
    def optional(self) -> bool:
        return bool(self.type_flags & _TYPE_OPTIONAL)


class CIAParser:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.contents: List[CIAContent] = []
        self._parse()

    @property
    def content_count(self) -> int:
        return len(self.contents)

    def _parse(self) -> None:
        # CIA header
        self.header_size = read_u32_le(self.data, 0x00)
        self.type        = read_u16_le(self.data, 0x04)
        self.version     = read_u16_le(self.data, 0x06)
        self.cert_size   = read_u32_le(self.data, 0x08)
        self.ticket_size = read_u32_le(self.data, 0x0C)
        self.tmd_size    = read_u32_le(self.data, 0x10)
        self.meta_size   = read_u32_le(self.data, 0x14)
        # content_size is 64-bit
        lo = read_u32_le(self.data, 0x18)
        hi = read_u32_le(self.data, 0x1C)
        self.content_size = lo | (hi << 32)

        # Section offsets (each aligned to 64).
        off = align_up(self.header_size, _ALIGN)
        self.cert_offset = off
        off = align_up(off + self.cert_size, _ALIGN)
        self.ticket_offset = off
        off = align_up(off + self.ticket_size, _ALIGN)
        self.tmd_offset = off
        off = align_up(off + self.tmd_size, _ALIGN)
        self.content_offset = off

        logger.info(
            "CIA header=%d cert=%d ticket=%d tmd=%d content_off=0x%X size=%d",
            self.header_size, self.cert_size, self.ticket_size,
            self.tmd_size, self.content_offset, self.content_size,
        )
        self._parse_tmd()

    def _tmd_header_start(self, tmd: bytes) -> int:
        """Offset of the signed TMD header inside the TMD blob.

        Skips the variable-length signature blob based on its type word.
        """
        if len(tmd) < 4:
            return 4 + 0x100 + 0x3C  # assume RSA-2048

        sig_type_le = read_u32_le(tmd, 0x00)
        sig_type_be = int.from_bytes(tmd[0:4], "big")
        if sig_type_le in _SIG_SIZES:
            return 4 + _SIG_SIZES[sig_type_le]
        if sig_type_be in _SIG_SIZES:
            return 4 + _SIG_SIZES[sig_type_be]
        logger.warning("Unknown TMD signature type 0x%08X, assuming RSA-2048", sig_type_le)
        return 4 + 0x100 + 0x3C

    def _parse_tmd(self) -> None:
        """Build the content table from the TMD chunk records.

        On any malformation we fall back to a single content spanning the whole
        content region -- the historical behaviour, so plain single-NCCH CIAs
        keep working byte-for-byte.
        """
        tmd = safe_slice(self.data, self.tmd_offset, self.tmd_size)
        header_start = self._tmd_header_start(tmd)

        count_off = header_start + _CONTENT_COUNT_OFF
        if count_off + 2 <= len(tmd):
            count = int.from_bytes(tmd[count_off:count_off + 2], "big")
        else:
            count = 0

        chunks_base = header_start + _CHUNKS_OFF
        needed = chunks_base + count * _CHUNK_RECORD_SIZE

        if count <= 0 or count > 0x10000 or needed > len(tmd):
            # No usable chunk table -- treat the whole content region as one.
            self._fallback_single_content()
            return

        contents: List[CIAContent] = []
        pos = self.content_offset
        for i in range(count):
            rec = chunks_base + i * _CHUNK_RECORD_SIZE
            content_id    = int.from_bytes(tmd[rec + 0x00:rec + 0x04], "big")
            content_index = int.from_bytes(tmd[rec + 0x04:rec + 0x06], "big")
            type_flags    = int.from_bytes(tmd[rec + 0x06:rec + 0x08], "big")
            size          = int.from_bytes(tmd[rec + 0x08:rec + 0x10], "big")
            contents.append(CIAContent(
                chunk_index=i,
                content_id=content_id,
                content_index=content_index,
                type_flags=type_flags,
                offset=pos,
                size=size,
            ))
            # Each content starts on a fresh 64-byte block.
            pos = align_up(pos + size, _ALIGN)

        self.contents = contents
        logger.info(
            "CIA TMD: %d content(s) -- sizes=%s optional=%s encrypted=%s",
            count,
            [c.size for c in contents],
            [c.optional for c in contents],
            [c.encrypted for c in contents],
        )

    def _fallback_single_content(self) -> None:
        size = self.content_size or max(0, len(self.data) - self.content_offset)
        self.contents = [CIAContent(
            chunk_index=0, content_id=0, content_index=0, type_flags=0,
            offset=self.content_offset, size=size,
        )]
        logger.info("CIA TMD unreadable; falling back to single content of %d bytes", size)

    def get_content(self, index: int = 0) -> bytes:
        """Return content blob at chunk position *index* (0-based).

        Raises IndexError if *index* is out of range, ROMParseError if the
        slice is empty. Encrypted contents are returned as-is with a warning --
        the caller's NCCH parser will reject them, which is the right signal.
        """
        if index < 0 or index >= len(self.contents):
            raise IndexError(
                f"CIA content index {index} out of range (have {len(self.contents)})"
            )
        c = self.contents[index]
        if c.encrypted:
            logger.warning(
                "CIA content %d (id=0x%X) is flagged encrypted; NCCH parse will likely fail",
                index, c.content_id,
            )
        end = min(c.offset + c.size, len(self.data))
        blob = self.data[c.offset:end]
        if not blob:
            raise ROMParseError(f"CIA content {index} is empty")
        return blob

    def get_content_by_index(self, content_index: int) -> bytes:
        """Return the content whose TMD Content Index field == *content_index*."""
        for c in self.contents:
            if c.content_index == content_index:
                return self.get_content(c.chunk_index)
        raise IndexError(f"No CIA content with content_index {content_index}")

    def iter_contents(self) -> Iterator[tuple[CIAContent, bytes]]:
        """Yield (metadata, bytes) for every content in chunk order."""
        for c in self.contents:
            end = min(c.offset + c.size, len(self.data))
            yield c, self.data[c.offset:end]
