"""Pokemon PC containers reach the decoder.

Ultra Sun/Moon keep model textures in LZ-compressed PC section blobs inside
GARCs. v2 had the parser (parse_pokemon_pc_v5) but never called it, and the
decompression fast-reject dropped anything that did not start with a standard
texture magic. These tests lock both halves.
"""

import struct

from tex_forge.pipeline.scanner import _has_texture_payload, extract_textures


def _pc_blob(width: int, height: int, pc_fmt: int, pixels: bytes) -> bytes:
    """Minimal PC v2 file with one 'texture' section."""
    section = bytearray(0x80 + len(pixels))
    section[8:16] = b"texture\x00"
    section[0x28:0x2C] = b"tex\x00"
    struct.pack_into("<HHH", section, 0x68, width, height, pc_fmt)
    section[0x80:] = pixels

    version = 2
    header = 4 + (version + 1) * 4
    sec_off = header
    sec_end = sec_off + len(section)
    blob = bytearray(sec_end)
    blob[0:2] = b"PC"
    blob[2] = version
    struct.pack_into("<III", blob, 4, sec_off, sec_end, sec_end)
    blob[sec_off:sec_end] = section
    return bytes(blob)


def _lz11_literals(payload: bytes) -> bytes:
    out = bytearray([0x11, len(payload) & 0xFF, (len(payload) >> 8) & 0xFF,
                     (len(payload) >> 16) & 0xFF])
    for i in range(0, len(payload), 8):
        out.append(0x00)
        out += payload[i:i + 8]
    return bytes(out)


def test_pc_section_yields_texture():
    pixels = bytes((i * 3) & 0xFF for i in range(8 * 8 * 4))
    blob = _pc_blob(8, 8, 4, pixels)  # PC format 4 -> RGBA8
    found = list(extract_textures(blob, "a/0/0/0"))
    assert len(found) == 1
    tex = found[0]
    assert tex.width == 8 and tex.height == 8
    assert tex.format == 0  # RGBA8
    assert tex.parser_used == "pokemon_pc_v5"
    assert tex.data == pixels


def test_lz_wrapped_pc_is_not_rejected():
    pixels = bytes((i * 5) & 0xFF for i in range(8 * 8 * 4))
    blob = _pc_blob(8, 8, 4, pixels)
    wrapped = _lz11_literals(blob)
    assert _has_texture_payload(blob) is True
    found = list(extract_textures(wrapped, "a/0/0/1.lz"))
    assert len(found) == 1
    assert found[0].data == pixels


def test_legacy_gr_wrapper_points_at_inner_bch():
    from tex_forge.pipeline.adapters import unwrap_pokemon_container
    # unwrap_pokemon_container ignores buffers shorter than 0x84.
    # This file stores the BCH offset at byte 4 (the previous Forge read).
    # The u32 at byte 8 is the BCH magic itself, so Ohana's +0x08 slot does
    # not steal it.
    inner = b"BCH\x00" + b"\x11" * 16
    blob = b"GR\x00\x00" + struct.pack("<I", 8) + inner
    blob = blob.ljust(0x84, b"\x00")
    assert unwrap_pokemon_container(blob) == blob[8:]
    assert _has_texture_payload(blob) is True


def test_ohana_gr_offset_at_8_beats_a_plausible_offset_at_4():
    from tex_forge.pipeline.adapters import unwrap_pokemon_container
    # Ohana.vb reads the GR BCH offset from 0x08. Both slots point at a
    # BCH magic here; 0x08 is the one the loader uses.
    blob = bytearray(0x84)
    blob[0:2] = b"GR"
    struct.pack_into("<I", blob, 4, 0x10)
    struct.pack_into("<I", blob, 8, 0x30)
    blob[0x10:0x14] = b"BCH\x00"
    blob[0x30:0x34] = b"BCH\x00"
    assert unwrap_pokemon_container(bytes(blob)) == bytes(blob[0x30:])


def test_mm_and_tm_wrappers_unwrap_bch_at_0x80():
    from tex_forge.pipeline.adapters import unwrap_pokemon_container
    for magic in (b"MM", b"TM", b"PC", b"PT"):
        blob = bytearray(0x90)
        blob[0:2] = magic
        blob[0x80:0x84] = b"BCH\x00"
        blob[0x84:] = b"\x5A" * 12
        assert unwrap_pokemon_container(bytes(blob)) == bytes(blob[0x80:])
        assert _has_texture_payload(bytes(blob)) is True


def test_mm_section_container_is_not_stolen_by_the_bch_unwrap():
    # A USUM MM/PC section file is parsed as pixels. A BCH-shaped tail
    # must not replace that result.
    pixels = bytes((i * 7) & 0xFF for i in range(8 * 8 * 4))
    blob = bytearray(_pc_blob(8, 8, 4, pixels))
    blob[0:2] = b"MM"
    if len(blob) < 0x84:
        blob.extend(b"\x00" * (0x84 - len(blob)))
    blob[0x80:0x84] = b"BCH\x00"
    found = list(extract_textures(bytes(blob), "a/0/8/3"))
    assert len(found) == 1
    assert found[0].parser_used == "pokemon_pc_v5"
    assert found[0].data == pixels
