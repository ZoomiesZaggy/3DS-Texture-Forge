"""Public decoder entry point -- numpy first, python fallback.

Single function, `decode(data, w, h, fmt) -> ndarray | None`. Everywhere
else in the codebase that wants to decode pixels should import this and
nothing else from textures.decoder.

Why a separate file? Avoids a circular import: pica_numpy and pica_python
both depend on tex_forge.textures.formats, and exposing dispatch from
tex_forge.textures.decoder.__init__ pulls them both in eagerly.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from tex_forge.textures.decoder.pica_numpy import decode_numpy
from tex_forge.textures.decoder.pica_python import decode_python

logger = logging.getLogger(__name__)

#: Refuse absurd dimensions before allocating the output image. 8192 covers
#: every real 3DS surface (the GPU's practical max is well under this) and
#: stops a corrupt header from asking for a multi-gigabyte decode.
MAX_TEXTURE_DIMENSION = 8192


def decode(data: bytes, width: int, height: int, fmt: int) -> Optional[np.ndarray]:
    """Decode a PICA200 morton-tiled texture into an RGBA8 ndarray.

    Returns the (H, W, 4) uint8 array on success, None if the format isn't
    supported or the input is malformed.

    Tiny textures (W or H < 4) take the python path because the numpy
    morton tables don't tile cleanly below the 8x8 PICA tile size.
    Width or height above MAX_TEXTURE_DIMENSION is rejected.
    """
    if width <= 0 or height <= 0:
        return None
    if width > MAX_TEXTURE_DIMENSION or height > MAX_TEXTURE_DIMENSION:
        logger.warning(
            "refusing %dx%d texture (limit %d per side)",
            width, height, MAX_TEXTURE_DIMENSION,
        )
        return None

    if width >= 4 and height >= 4:
        result = decode_numpy(data, width, height, fmt)
        if result is not None:
            return result

    return decode_python(data, width, height, fmt)
