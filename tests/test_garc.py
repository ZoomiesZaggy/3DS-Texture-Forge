"""GARC v4/v6 extraction.

pk3DS walks FATB as a bit vector plus one (start, end, length) triple per
set bit. A fixed 16-byte stride only matches entries with a single subfile,
which is why USUM UI language packs and map model+texture pairs came out
as one file plus a run of unknown tails. These fixtures are built the way
GARC.cs writes them; no ROM is involved.
"""

import struct

from tex_forge.archives.garc import _iter
from tex_forge.pipeline.scanner import extract_textures


def _bclim(pixels: bytes, width: int = 8, height: int = 8, fmt: int = 0) -> bytes:
    """Minimal BCLIM: pixels, then a 0x28-byte CLIM/imag footer."""
    footer = bytearray(0x28)
    footer[0:4] = b"CLIM"
    footer[4:6] = b"\xFF\xFE"  # BOM 0xFFFE, little-endian body
    footer[0x14:0x18] = b"imag"
    struct.pack_into("<HH", footer, 0x1C, width, height)
    struct.pack_into("<I", footer, 0x20, fmt)  # 0 = L8
    return pixels + bytes(footer)


def _lz11_literals(payload: bytes) -> bytes:
    out = bytearray([0x11, len(payload) & 0xFF, (len(payload) >> 8) & 0xFF,
                     (len(payload) >> 16) & 0xFF])
    for i in range(0, len(payload), 8):
        out.append(0x00)
        out += payload[i:i + 8]
    return bytes(out)


def build_garc(entries: list[list[tuple[int, bytes]]], version: int = 0x0600) -> bytes:
    """Pack ``entries`` the way pk3DS GARC.cs writes a v4 or v6 archive.

    ``entries[i]`` is a list of ``(bit, payload)``. Bits are stored low
    to high. File bytes are 4-byte padded; the FATB length field stays
    the unpadded size.
    """
    data = bytearray()
    meta: list[tuple[int, list[tuple[int, int, int]]]] = []
    for subs in entries:
        vector = 0
        triples: list[tuple[int, int, int]] = []
        for bit, payload in sorted(subs, key=lambda item: item[0]):
            vector |= 1 << bit
            start = len(data)
            data += payload
            pad = (4 - (len(payload) % 4)) % 4
            data += b"\xFF" * pad
            triples.append((start, len(data), len(payload)))
        meta.append((vector, triples))

    fatb_body = bytearray()
    fato_offsets = bytearray()
    op = 0
    for vector, triples in meta:
        fato_offsets += struct.pack("<I", op)
        fatb_body += struct.pack("<I", vector)
        op += 4
        for start, end, length in triples:
            fatb_body += struct.pack("<III", start, end, length)
            op += 12

    n = len(entries)
    fato = b"OTAF" + struct.pack("<IHH", 0xC + 4 * n, n, 0xFFFF) + fato_offsets
    file_count = sum(len(subs) for subs in entries)
    fatb = b"BTAF" + struct.pack("<II", 0xC + len(fatb_body), file_count) + fatb_body
    fimb = b"BMIF" + struct.pack("<II", 0xC, len(data))

    hdr_len = 0x24 if version == 0x0600 else 0x1C
    data_offset = hdr_len + len(fato) + len(fatb) + len(fimb)
    largest = max((len(payload) for subs in entries for _, payload in subs), default=0)
    padded = largest + (4 - largest % 4) % 4
    hdr = struct.pack("<4sIHHI", b"CRAG", hdr_len, 0xFEFF, version, 4)
    hdr += struct.pack("<II", data_offset, data_offset + len(data))
    if version == 0x0600:
        hdr += struct.pack("<III", padded, largest, 4)
    else:
        hdr += struct.pack("<I", largest)
    assert len(hdr) == hdr_len
    return bytes(hdr + fato + fatb + fimb + data)


def test_v4_single_subfile_name_and_bytes_ignore_padding():
    payload = b"CGFX" + b"\xAB" * 5  # 9 bytes, pads to 12
    blob = build_garc([[(0, payload)]], version=0x0400)
    found = list(_iter(blob))
    assert len(found) == 1
    assert found[0].name == "0000.cgfx"
    assert found[0].data == payload


def test_v6_multi_subfile_yields_every_language_and_the_next_entry():
    # Entry 0 is a two-language UI pair (bits 0 and 1). Entry 1 is a
    # lone file. A 16-byte stride keeps only the first subfile.
    en = _bclim(b"\x11" * 64)
    jp = _bclim(b"\x22" * 64)
    lone = b"BCH\x00" + b"\x33" * 8
    blob = build_garc([[(0, en), (1, jp)], [(0, lone)]], version=0x0600)

    found = list(_iter(blob))
    names = [e.name for e in found]
    assert names == ["0000_00.bclim", "0000_01.bclim", "0001.bch"]
    assert found[0].data == en
    assert found[1].data == jp
    assert found[2].data == lone
    # Padding must not ride along: the CLIM footer has to stay at EOF.
    assert found[0].data[-0x28:-0x24] == b"CLIM"


def test_v6_garc_of_bclim_and_lz_pc_reaches_the_decoder():
    from tests.test_pokemon_pc import _pc_blob

    pixels = bytes((i * 3) & 0xFF for i in range(8 * 8 * 4))
    pc = _lz11_literals(_pc_blob(8, 8, 4, pixels))
    clim = _bclim(b"\x44" * 64)
    blob = build_garc([[(0, pc), (1, clim)]], version=0x0600)

    found = list(extract_textures(blob, "a/0/6/0"))
    assert len(found) == 2
    by_parser = {tex.parser_used: tex for tex in found}
    assert set(by_parser) == {"pokemon_pc_v5", "bflim"}
    assert by_parser["pokemon_pc_v5"].data == pixels
    assert by_parser["bflim"].format == 0x07  # BCLIM format 0 -> L8
    assert by_parser["bflim"].width == 8 and by_parser["bflim"].height == 8
    assert "0000_00" in by_parser["pokemon_pc_v5"].source_file
    assert "0000_01" in by_parser["bflim"].source_file
