"""Round-trip the decoders for every PICA200 format on a small synthetic input."""

import numpy as np
import pytest

from tex_forge.textures.decoder import decode
from tex_forge.textures.formats import PicaFormat, encoded_size


def test_rgba8_8x8_solid():
    """8x8 RGBA8 with every byte set to a known pattern."""
    pix = bytearray()
    for _ in range(64):
        pix.extend([0x80, 10, 20, 30])  # A B G R
    out = decode(bytes(pix), 8, 8, int(PicaFormat.RGBA8))
    assert out is not None and out.shape == (8, 8, 4)
    # Decoder reverses ABGR -> RGBA so first pixel = (30, 20, 10, 0x80).
    assert tuple(out[0, 0].tolist()) == (30, 20, 10, 128)


def test_etc1_zero_blocks_yield_solid_alpha():
    """All-zero ETC1 blocks should produce a solid image with full alpha."""
    n_blocks = (16 // 4) ** 2
    out = decode(bytes(n_blocks * 8), 16, 16, int(PicaFormat.ETC1))
    assert out is not None and out.shape == (16, 16, 4)
    assert (out[..., 3] == 255).all()


def test_etc1a4_full_alpha():
    """ETC1A4 with all alpha nibbles = 0xF should decode alpha=255 everywhere."""
    block = b"\xff" * 8 + b"\x00" * 8  # alpha=0xFFFFF... + zero-color block
    out = decode(block, 4, 4, int(PicaFormat.ETC1A4))
    assert out is not None and (out[..., 3] == 255).all()


@pytest.mark.parametrize("fmt,w,h", [
    (PicaFormat.RGBA8, 8, 8),
    (PicaFormat.RGB8, 8, 8),
    (PicaFormat.RGBA5551, 8, 8),
    (PicaFormat.RGB565, 8, 8),
    (PicaFormat.RGBA4, 8, 8),
    (PicaFormat.LA8, 8, 8),
    (PicaFormat.HILO8, 8, 8),
    (PicaFormat.L8, 8, 8),
    (PicaFormat.A8, 8, 8),
    (PicaFormat.LA4, 8, 8),
    (PicaFormat.L4, 8, 8),
    (PicaFormat.A4, 8, 8),
    (PicaFormat.ETC1, 8, 8),
    (PicaFormat.ETC1A4, 8, 8),
])
def test_every_format_round_trips_zero_input(fmt, w, h):
    """Zero-bytes input of the expected size should produce a valid array."""
    size = encoded_size(w, h, int(fmt))
    out = decode(b"\x00" * size, w, h, int(fmt))
    assert out is not None
    assert out.shape == (h, w, 4)
    assert out.dtype == np.uint8


def test_python_path_for_tiny_textures():
    """Sub-4 dimensions hit the python fallback."""
    from tex_forge.textures.decoder.pica_python import decode_python
    out = decode_python(b"\x00" * 16, 2, 2, int(PicaFormat.RGBA8))
    assert out is not None and out.shape == (2, 2, 4)
