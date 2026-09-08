"""Multi-content CIA parsing on hand-built archives.

A CIA lays out header / cert / ticket / TMD / content, each major section
64-byte aligned. Inside the content region every content also begins on a
fresh 64-byte block. The number of contents and their sizes come from the
TMD chunk records, which sit after the 0xC4 signed header and the 0x900
block of (ignored) content-info records.

These tests build that structure from scratch -- two real contents with a
deliberately non-64-aligned first content -- so we exercise the chunk-record
walk, the per-content alignment, the type flags (encrypted / optional), and
the index bounds, with no ROM on disk.
"""

import struct

import pytest

from tex_forge.core.binio import align_up
from tex_forge.rom.cia import CIAParser

_SIG_BLOB = 0x140  # RSA-2048 SHA-256: 4 (type) + 0x100 (sig) + 0x3C (pad)


def _be16(v): return struct.pack(">H", v)
def _be32(v): return struct.pack(">I", v)
def _be64(v): return struct.pack(">Q", v)
def _le32(v): return struct.pack("<I", v)


def _pad64(buf: bytearray) -> None:
    while len(buf) % 64:
        buf.append(0)


def _build_tmd(specs) -> bytes:
    """specs: list of (content_id, content_index, type_flags, size)."""
    blob = bytearray()
    blob += _be32(0x00010004)              # signature type
    blob += b"\x00" * (0x100 + 0x3C)       # signature + padding
    assert len(blob) == _SIG_BLOB

    header = bytearray(b"\x00" * 0xC4)
    header[0x9E:0xA0] = _be16(len(specs))  # content count
    blob += header
    blob += b"\x00" * 0x900                # 64 content-info records

    for cid, cidx, tflags, size in specs:
        rec = bytearray(b"\x00" * 0x30)
        rec[0x00:0x04] = _be32(cid)
        rec[0x04:0x06] = _be16(cidx)
        rec[0x06:0x08] = _be16(tflags)
        rec[0x08:0x10] = _be64(size)
        blob += rec
    return bytes(blob)


def _build_cia(contents) -> bytes:
    """contents: list of (content_id, content_index, type_flags, data_bytes)."""
    specs = [(cid, cidx, tf, len(data)) for cid, cidx, tf, data in contents]
    tmd = _build_tmd(specs)
    cert = b"CERT" * 4
    ticket = b"TIK!" * 4

    header = bytearray(b"\x00" * 0x20)
    header[0x00:0x04] = _le32(0x20)         # header_size
    header[0x08:0x0C] = _le32(len(cert))
    header[0x0C:0x10] = _le32(len(ticket))
    header[0x10:0x14] = _le32(len(tmd))

    out = bytearray(header)
    _pad64(out)
    out += cert
    _pad64(out)
    out += ticket
    _pad64(out)
    out += tmd
    _pad64(out)

    content_start = len(out)
    for _, _, _, data in contents:
        out += data
        _pad64(out)
    out[0x18:0x1C] = _le32(len(out) - content_start)
    return bytes(out)


def test_two_contents_resolve_with_alignment():
    c0 = b"\xA0" * 100   # deliberately not a multiple of 64
    c1 = b"\xB1" * 50
    cia = CIAParser(_build_cia([
        (0x00000000, 0, 0x0000, c0),   # main
        (0x00000001, 1, 0x4000, c1),   # optional / DLC
    ]))

    assert cia.content_count == 2
    assert cia.get_content(0) == c0
    assert cia.get_content(1) == c1
    # content 1 begins on the 64-byte block after content 0
    assert cia.contents[1].offset == align_up(cia.contents[0].offset + 100, 64)


def test_type_flags_and_lookup_by_content_index():
    c0 = b"\xA0" * 64
    c1 = b"\xB1" * 64
    cia = CIAParser(_build_cia([
        (0, 0, 0x0001, c0),   # encrypted flag set
        (5, 5, 0x4000, c1),   # optional, non-contiguous content_index
    ]))

    assert cia.contents[0].encrypted is True
    assert cia.contents[0].optional is False
    assert cia.contents[1].optional is True
    assert cia.get_content_by_index(5) == c1
    with pytest.raises(IndexError):
        cia.get_content_by_index(99)


def test_index_out_of_range_raises_indexerror_not_notimplemented():
    cia = CIAParser(_build_cia([(0, 0, 0x0000, b"\xCC" * 32)]))
    with pytest.raises(IndexError):
        cia.get_content(1)


def test_single_content_backward_compatible():
    c0 = b"\xCC" * 200
    cia = CIAParser(_build_cia([(0, 0, 0x0000, c0)]))
    assert cia.content_count == 1
    assert cia.get_content() == c0
    assert cia.get_content(0) == c0


def test_iter_contents_yields_all_in_order():
    c0 = b"\x10" * 48
    c1 = b"\x20" * 48
    c2 = b"\x30" * 48
    cia = CIAParser(_build_cia([
        (0, 0, 0x0000, c0),
        (1, 1, 0x0000, c1),
        (2, 2, 0x4000, c2),
    ]))
    blobs = [blob for _meta, blob in cia.iter_contents()]
    assert blobs == [c0, c1, c2]
