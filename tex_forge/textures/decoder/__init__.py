"""Pure pixel decoders -- bytes + (W, H, format) -> RGBA8 ndarray.

Two decoder backends:

  pica_numpy.py  -- vectorised, uses morton.scatter_map / etc1_block_order.
                    First-choice path. Handles all formats including ETC1.
  pica_python.py -- pure-Python scalar fallback for tiny textures (W or H < 4)
                    where the NumPy gather/scatter overhead dominates and the
                    morton tables don't tile cleanly.

The public entry point is `decode(data, w, h, fmt)` -- it dispatches to numpy
first, falls back to python on failure or for tiny textures, returns None on
unrecoverable failure.
"""

from tex_forge.textures.decoder.dispatch import decode  # noqa: F401

__all__ = ["decode"]
