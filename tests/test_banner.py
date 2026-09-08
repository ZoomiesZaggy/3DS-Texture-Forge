"""Tests for the HOME Menu banner accessor (rom/banner.py).

parse_cbmd is tested against hand-built CBMD blobs (magic, common vs
region-specific offsets, CWAV bounding, truncation). decode_banner_cgfx is
tested through its registry seam (_iter_cgfx_textures) so the
largest-decodable-texture selection runs the REAL decoder on synthetic
RGBA8 payloads without needing a real banner CGFX.
"""

import pytest

import tex_forge.rom.banner as banner
from tex_forge.core.types import Texture
from tex_forge.rom.banner import (
    CBMD_HEADER_SIZE,
    decode_banner_cgfx,
    parse_cbmd,
)
from tex_forge.textures.formats import PicaFormat


def _cbmd(common_off=0, region_offs=(), cwav_off=0, body=b""):
    h = bytearray(CBMD_HEADER_SIZE)
    h[0:4] = b"CBMD"
    h[0x08:0x0C] = common_off.to_bytes(4, "little")
    for i, off in enumerate(region_offs):
        at = 0x0C + 4 * i
        h[at:at + 4] = off.to_bytes(4, "little")
    h[0x84:0x88] = cwav_off.to_bytes(4, "little")
    return bytes(h) + body


def test_parse_cbmd_common_payload_bounded_by_cwav():
    body = b"PAYLOAD!" + b"CWAVdata"
    blob = _cbmd(common_off=CBMD_HEADER_SIZE,
                 cwav_off=CBMD_HEADER_SIZE + 8, body=body)
    assert parse_cbmd(blob) == b"PAYLOAD!"


def test_parse_cbmd_region_fallback_and_no_cwav():
    # common offset 0, first region carries the model; no CWAV: run to end
    blob = _cbmd(common_off=0, region_offs=(CBMD_HEADER_SIZE,),
                 cwav_off=0, body=b"REGIONMODEL")
    assert parse_cbmd(blob) == b"REGIONMODEL"


def test_parse_cbmd_rejects_bad_magic_and_truncation():
    assert parse_cbmd(b"NOPE" + b"\x00" * 0x90) is None
    assert parse_cbmd(b"CBMD\x00\x00") is None  # shorter than the header
    # header-only blob with no payload offsets
    assert parse_cbmd(_cbmd()) is None


def _rgba8_payload(side: int) -> bytes:
    out = bytearray()
    for i in range(side * side):
        out.extend([i & 0xFF, (i * 3) & 0xFF, 0x40, 0xFF])
    return bytes(out)


def test_decode_banner_picks_largest_decodable(monkeypatch):
    small = Texture(name="ramp", width=8, height=8,
                    format=int(PicaFormat.RGBA8), data=_rgba8_payload(8),
                    parser_used="cgfx", source_file="banner")
    big = Texture(name="banner_img", width=16, height=16,
                  format=int(PicaFormat.RGBA8), data=_rgba8_payload(16),
                  parser_used="cgfx", source_file="banner")
    broken = Texture(name="bad", width=64, height=64,
                     format=int(PicaFormat.RGBA8), data=b"",  # undecodable
                     parser_used="cgfx", source_file="banner")
    monkeypatch.setattr(banner, "_iter_cgfx_textures",
                        lambda data: iter([small, broken, big]))
    rgba = decode_banner_cgfx(b"raw-cgfx-not-compressed")
    assert rgba is not None and rgba.shape == (16, 16, 4)


def test_decode_banner_none_when_nothing_decodes(monkeypatch):
    monkeypatch.setattr(banner, "_iter_cgfx_textures", lambda data: iter(()))
    assert decode_banner_cgfx(b"whatever") is None
