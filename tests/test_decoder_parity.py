"""Property-style parity between the numpy and pure-Python PICA decoders.

Random tiled bytes, several sizes, every format both paths implement.
A mismatch here means a pack hashed from one backend would not match a
pack hashed from the other, so the two decoders have to agree.
"""

import numpy as np
import pytest

from tex_forge.textures.decoder.pica_numpy import decode_numpy
from tex_forge.textures.decoder.pica_python import decode_python
from tex_forge.textures.formats import PicaFormat, encoded_size


@pytest.mark.parametrize("fmt", list(PicaFormat))
@pytest.mark.parametrize("width,height", [(8, 8), (16, 8), (12, 20)])
def test_numpy_matches_python_on_random_data(fmt, width, height):
    rng = np.random.default_rng((int(fmt) << 16) ^ (width << 8) ^ height)
    size = encoded_size(width, height, int(fmt))
    data = rng.integers(0, 256, size=size, dtype=np.uint8).tobytes()
    got_np = decode_numpy(data, width, height, int(fmt))
    got_py = decode_python(data, width, height, int(fmt))
    assert got_np is not None and got_py is not None
    np.testing.assert_array_equal(got_np, got_py)
