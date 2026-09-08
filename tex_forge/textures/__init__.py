"""Texture handling: format enum, morton de-tiling, decoders, container plugins.

The split is:

  formats.py      -- PicaFormat enum, the single source of truth for format IDs
  morton.py       -- Z-order de-tiling tables (8x8 tiles, 4x4 ETC1 macro-tiles)
  decoder/        -- Pure pixel decoders (bytes + PicaFormat -> RGBA8 ndarray)
  containers/     -- Plugins that parse a *texture file* (BCH, CGFX, CTPK, ...)
  registry.py     -- @register_texture decorator + dispatch
  base.py         -- TexturePlugin ABC

Plugins emit core.types.Texture, the decoder turns those Textures into PNGs.
Decoders never look at format-specific containers; containers never decode
pixels. This separation is what lets us add new container formats without
touching the ETC1 decoder, and vice versa.
"""

from tex_forge.textures.formats import PicaFormat  # noqa: F401
