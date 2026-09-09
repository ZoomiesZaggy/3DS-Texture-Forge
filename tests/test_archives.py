"""Smoke-test that archive plugins detect their magics."""

import struct

from tex_forge.archives.registry import detect_archive


def test_garc_detect():
    fake = b"CRAG" + struct.pack("<I", 0x1C) + b"\xff\xfe\x00\x00" + b"\x00" * 200
    plugin = detect_archive(fake)
    assert plugin is not None and plugin.name == "garc"


def test_sarc_detect():
    fake = (b"SARC" + struct.pack("<HH", 0x14, 0xFEFE) +
            struct.pack("<II", 0x14, 0x14) + struct.pack("<HH", 0x100, 0))
    plugin = detect_archive(fake)
    assert plugin is not None and plugin.name == "sarc"


def test_no_match_returns_none():
    assert detect_archive(b"NotAnArchive") is None


def test_priorities_sorted():
    """Plugins should be iterated in descending priority order."""
    from tex_forge.archives.registry import iter_plugins
    priorities = [r.priority for r in iter_plugins()]
    assert priorities == sorted(priorities, reverse=True)


# ── Level-5 flat archive: decompress + embedded-container scan ────────────────
#
# Fantasy Life stores CGFX/BCH/CTPK/CTXB containers inside LZ-compressed flat
# entries, usually a few hundred bytes behind a resource header. The v2 refactor
# dropped the scan that finds them, regressing Fantasy Life to 0 textures. These
# tests pin the restored behaviour without needing the 372 MB ROM.

def _lz11_literal(payload: bytes) -> bytes:
    """Encode `payload` as an all-literal raw Nintendo LZ11 stream."""
    out = bytearray(struct.pack("<I", 0x11 | (len(payload) << 8)))
    i = 0
    while i < len(payload):
        out.append(0x00)          # flag byte: next 8 tokens are literals
        out += payload[i:i + 8]
        i += 8
    return bytes(out)


def test_l5_flat_finds_embedded_cgfx_in_compressed_entry():
    from tex_forge.archives.l5_flat import _entry_to_container
    # A resource wrapper: 0x100 bytes of header, then a CGFX container, all
    # LZ11-compressed (mirrors the real Fantasy Life entries, CGFX at +0x100).
    inner = b"\x00" * 0x100 + b"CGFX" + b"\x00" * 60
    entry = _lz11_literal(inner)
    assert entry[0] == 0x11
    out = _entry_to_container("entry_00000.bin", entry)
    assert out is not None
    assert out.data[:4] == b"CGFX"
    assert "[lz]" in out.name and "+0x100" in out.name


def test_l5_flat_direct_container_uncompressed():
    from tex_forge.archives.l5_flat import _entry_to_container
    raw = b"CTPK" + b"\x00" * 64
    out = _entry_to_container("entry_00001.bin", raw)
    assert out is not None and out.data[:4] == b"CTPK"


def test_l5_flat_non_texture_entry_skipped():
    from tex_forge.archives.l5_flat import _entry_to_container
    # Decompresses fine but holds no texture container magic -> not yielded.
    entry = _lz11_literal(b"zmdl" + b"\x00" * 200)
    assert _entry_to_container("entry_00002.bin", entry) is None
