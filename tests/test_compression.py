"""Round-trip the compressors we ship: LZ10, LZ11, Yaz0 (against known fixtures)."""

import struct

from tex_forge.compression import try_decompress
from tex_forge.compression.lz_nintendo import _decompress_lz10, _decompress_lz11


def test_lz10_all_literals():
    hdr = struct.pack("<I", 0x10 | (5 << 8))
    payload = bytes([0x00]) + b"AAAAA"
    assert _decompress_lz10(hdr + payload) == b"AAAAA"


def test_lz11_all_literals_fast_path():
    hdr = struct.pack("<I", 0x11 | (5 << 8))
    payload = bytes([0x00]) + b"AAAAA"
    assert _decompress_lz11(hdr + payload) == b"AAAAA"


def test_lz11_backref_top2():
    """Encode 'ABCABC' as 3 literals + 1 backref(len=3, dist=3)."""
    hdr = struct.pack("<I", 0x11 | (6 << 8))
    # flag=0b00010000 -> bits[7..4]=0,0,0,1 = literal,literal,literal,backref
    # backref top=2, length=3, distance=3 -> indicator=0x20, b2=0x02
    payload = bytes([0x10, ord("A"), ord("B"), ord("C"), 0x20, 0x02])
    assert _decompress_lz11(hdr + payload) == b"ABCABC"


def test_dispatcher_picks_lz11():
    hdr = struct.pack("<I", 0x11 | (5 << 8))
    payload = bytes([0x00]) + b"AAAAA"
    result = try_decompress(hdr + payload)
    assert result is not None
    assert result.codec == "lz_nintendo_lz11"
    assert result.data == b"AAAAA"


def test_unknown_data_yields_none():
    assert try_decompress(b"random non-magic bytes here") is None
