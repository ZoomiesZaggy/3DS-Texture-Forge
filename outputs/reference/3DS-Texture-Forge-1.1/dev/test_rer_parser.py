"""
Tests for RE:Revelations TEX parser using synthetic fixtures
that replicate real observed header patterns.

Real evidence:
  File 1: 4116 bytes, header 54455800 A5000020 01100002 010C0100 + 4 unknown bytes
  File 2: 32788 bytes, header 54455800 A5000020 01800008 01110100 + 4 unknown bytes
  File 3: 393236 bytes, header 54455800 A5000460 02080001 060B0100 + 4 unknown bytes

Confirmed:
  - Header = 0x14 (20) bytes, payload = file_size - 0x14
  - Format byte at offset 0x0D:
      0x0C -> ETC1A4 (8bpp) -> file1: 64x64
      0x11 -> ETC1 (4bpp)   -> file2: 256x256
      0x0B -> RGB8 (24bpp)  -> file3: 512x256 or 256x512
"""

import os
import sys
import struct
import numpy as np
import unittest

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from textures.tex_capcom import (
    parse_capcom_tex_strict, TexParseResult, is_capcom_tex,
    _find_pow2_dims_for_payload, GAME_PROFILES,
)
from textures.decoder import (
    decode_texture_fast, calculate_texture_size,
    FMT_ETC1, FMT_ETC1A4, FMT_RGB8, FMT_RGBA8, FMT_L8,
)

RER_TITLE_ID = "0004000000060200"


def _make_rer_tex_file(header_bytes_16: bytes, payload: bytes) -> bytes:
    """Build a synthetic TEX file: 16 known header bytes + 4 padding + payload."""
    # Pad header to 0x14 bytes
    header = header_bytes_16 + b'\x00\x00\x00\x00'
    assert len(header) == 0x14
    return header + payload


class TestRERPayloadDrivenParser(unittest.TestCase):
    """Test the RE:Revelations payload-driven parser against synthetic fixtures."""

    def test_file1_etc1a4_64x64(self):
        """File 1: 4116 bytes, format=0x0C(ETC1A4), expected 64x64."""
        header = bytes.fromhex('54455800A500002001100002010C0100')
        payload_size = 4096  # 64*64*8/8
        payload = os.urandom(payload_size)
        data = _make_rer_tex_file(header, payload)

        self.assertEqual(len(data), 4116)
        self.assertTrue(is_capcom_tex(data))

        result = parse_capcom_tex_strict(data, "test/tex1.tex", title_id=RER_TITLE_ID)

        self.assertIn(result.status, ("parsed", "partial"))
        self.assertEqual(result.width, 64)
        self.assertEqual(result.height, 64)
        self.assertEqual(result.format_pica, FMT_ETC1A4)
        self.assertEqual(result.data_offset, 0x14)
        self.assertEqual(len(result.pixel_data), payload_size)
        self.assertIn(result.confidence, ("high", "medium"))
        self.assertIn("rer_payload", result.parser_variant)

        print(f"  file1: {result.width}x{result.height} PICA=0x{result.format_pica:X} "
              f"conf={result.confidence} variant={result.parser_variant}")

    def test_file2_etc1_256x256(self):
        """File 2: 32788 bytes, format=0x11(ETC1), expected 256x256."""
        header = bytes.fromhex('54455800A500002001800008011101 00'.replace(' ', ''))
        payload_size = 32768  # 256*256*4/8
        payload = os.urandom(payload_size)
        data = _make_rer_tex_file(header, payload)

        self.assertEqual(len(data), 32788)

        result = parse_capcom_tex_strict(data, "test/tex2.tex", title_id=RER_TITLE_ID)

        self.assertIn(result.status, ("parsed", "partial"))
        self.assertEqual(result.width, 256)
        self.assertEqual(result.height, 256)
        self.assertEqual(result.format_pica, FMT_ETC1)
        self.assertEqual(result.data_offset, 0x14)
        self.assertIn(result.confidence, ("high", "medium"))

        print(f"  file2: {result.width}x{result.height} PICA=0x{result.format_pica:X} "
              f"conf={result.confidence} variant={result.parser_variant}")

    def test_file3_rgb8_512x256(self):
        """File 3: 393236 bytes, format=0x0B(RGB8), expected 512x256 or 256x512."""
        header = bytes.fromhex('54455800A500046002080001060B0100')
        payload_size = 393216  # 256*512*24/8 = 131072*3
        payload = os.urandom(payload_size)
        data = _make_rer_tex_file(header, payload)

        self.assertEqual(len(data), 393236)

        result = parse_capcom_tex_strict(data, "test/tex3.tex", title_id=RER_TITLE_ID)

        self.assertIn(result.status, ("parsed", "partial"))
        self.assertEqual(result.format_pica, FMT_RGB8)
        # Accept either 512x256 or 256x512
        self.assertEqual(result.width * result.height, 131072)
        self.assertTrue(result.width in (256, 512))
        self.assertTrue(result.height in (256, 512))
        self.assertEqual(result.data_offset, 0x14)

        print(f"  file3: {result.width}x{result.height} PICA=0x{result.format_pica:X} "
              f"conf={result.confidence} variant={result.parser_variant}")

    def test_without_title_id_falls_back(self):
        """Without title_id, the parser should still attempt payload bruteforce."""
        header = bytes.fromhex('54455800A500002001100002010C0100')
        payload_size = 4096
        payload = os.urandom(payload_size)
        data = _make_rer_tex_file(header, payload)

        result = parse_capcom_tex_strict(data, "test/tex1.tex", title_id="")

        # Should still find something via bruteforce, but possibly different format
        self.assertIn(result.status, ("parsed", "partial"))
        self.assertEqual(result.data_offset, 0x14)
        self.assertEqual(result.width * result.height * _bpp(result.format_pica) // 8,
                         payload_size)

        print(f"  no_title: {result.width}x{result.height} PICA=0x{result.format_pica:X} "
              f"conf={result.confidence} variant={result.parser_variant}")

    def test_decode_etc1a4_64x64_produces_image(self):
        """Verify that decoded pixel data produces a valid numpy array."""
        header = bytes.fromhex('54455800A500002001100002010C0100')
        payload_size = 4096
        # Create non-random ETC1A4 data (all zeros = valid ETC1 blocks)
        payload = bytes(payload_size)
        data = _make_rer_tex_file(header, payload)

        result = parse_capcom_tex_strict(data, "test/decode.tex", title_id=RER_TITLE_ID)
        self.assertIn(result.status, ("parsed", "partial"))

        rgba = decode_texture_fast(result.pixel_data, result.width, result.height,
                                   result.format_pica)
        self.assertIsNotNone(rgba)
        self.assertEqual(rgba.shape, (64, 64, 4))

        print(f"  decode: shape={rgba.shape}, dtype={rgba.dtype}")

    def test_decode_etc1_256x256_produces_image(self):
        """Verify ETC1 256x256 decode."""
        header = bytes.fromhex('54455800A500002001800008011101 00'.replace(' ', ''))
        payload_size = 32768
        payload = bytes(payload_size)
        data = _make_rer_tex_file(header, payload)

        result = parse_capcom_tex_strict(data, "test/decode2.tex", title_id=RER_TITLE_ID)
        self.assertIn(result.status, ("parsed", "partial"))

        rgba = decode_texture_fast(result.pixel_data, result.width, result.height,
                                   result.format_pica)
        self.assertIsNotNone(rgba)
        self.assertEqual(rgba.shape, (256, 256, 4))

        print(f"  decode: shape={rgba.shape}")

    def test_decode_rgb8_512x256_produces_image(self):
        """Verify RGB8 512x256 decode (or 256x512)."""
        header = bytes.fromhex('54455800A500046002080001060B0100')
        payload_size = 393216
        # Create simple gradient data
        payload = bytes(payload_size)
        data = _make_rer_tex_file(header, payload)

        result = parse_capcom_tex_strict(data, "test/decode3.tex", title_id=RER_TITLE_ID)
        self.assertIn(result.status, ("parsed", "partial"))

        rgba = decode_texture_fast(result.pixel_data, result.width, result.height,
                                   result.format_pica)
        self.assertIsNotNone(rgba)
        self.assertEqual(rgba.shape[0] * rgba.shape[1], 131072)
        self.assertEqual(rgba.shape[2], 4)

        print(f"  decode: shape={rgba.shape}")


class TestFindPow2Dims(unittest.TestCase):
    """Test the dimension-finding helper."""

    def test_4096_at_8bpp(self):
        dims = _find_pow2_dims_for_payload(4096, 8)
        ws = [(w, h) for w, h, _ in dims]
        self.assertIn((64, 64), ws)  # square, should be top-scored

    def test_32768_at_4bpp(self):
        dims = _find_pow2_dims_for_payload(32768, 4)
        ws = [(w, h) for w, h, _ in dims]
        self.assertIn((256, 256), ws)

    def test_393216_at_24bpp(self):
        dims = _find_pow2_dims_for_payload(393216, 24)
        ws = [(w, h) for w, h, _ in dims]
        self.assertIn((256, 512), ws)
        self.assertIn((512, 256), ws)

    def test_no_match_for_prime(self):
        dims = _find_pow2_dims_for_payload(7919, 8)  # prime number
        self.assertEqual(len(dims), 0)

    def test_square_scores_higher(self):
        dims = _find_pow2_dims_for_payload(4096, 8)
        dims.sort(key=lambda x: -x[2])
        # 64x64 (square) should score highest
        self.assertEqual(dims[0][0], 64)
        self.assertEqual(dims[0][1], 64)


class TestGameProfiles(unittest.TestCase):
    """Test game profile lookup."""

    def test_rer_eur_profile_exists(self):
        self.assertIn("0004000000060200", GAME_PROFILES)

    def test_rer_usa_profile_exists(self):
        self.assertIn("0004000000035D00", GAME_PROFILES)

    def test_unknown_title_returns_none(self):
        from textures.tex_capcom import _get_profile
        self.assertIsNone(_get_profile("0000000000000000"))

    def test_profile_format_map_overrides(self):
        from textures.tex_capcom import _get_format_map
        # Default: 0x0B -> 0x0C (ETC1)
        default_map = _get_format_map("")
        self.assertEqual(default_map[0x0B], 0x0C)

        # RE:R: 0x0B -> 0x01 (RGB8)
        rer_map = _get_format_map(RER_TITLE_ID)
        self.assertEqual(rer_map[0x0B], 0x01)

        # RE:R: 0x11 -> 0x0C (ETC1) — added entry
        self.assertEqual(rer_map[0x11], 0x0C)


def _bpp(pica_fmt):
    from textures.tex_capcom import PICA_BPP
    return PICA_BPP.get(pica_fmt, 0)


if __name__ == "__main__":
    print("=" * 60)
    print("RE:Revelations TEX Parser Tests (Synthetic Fixtures)")
    print("=" * 60)
    unittest.main(verbosity=2)
