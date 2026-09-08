"""ROM container parsers -- the outermost layers around RomFS data.

Stack (outermost to innermost):

    .3ds  -> NCSD (cartridge dump) -> NCCH partition 0 -> RomFS (IVFC tree)
    .cia  -> CIA  (installable)    -> NCCH content 0   -> RomFS (IVFC tree)
    .cxi  ->                          NCCH (raw)       -> RomFS

Top-level entry: parse_rom(path) -> (romfs_bytes, title_id, product_code, chain).
The chain string is purely for logging ("CIA/content0/NCCH/RomFS" etc.).

Format references:
  - https://www.3dbrew.org/wiki/NCCH
  - https://www.3dbrew.org/wiki/NCSD
  - https://www.3dbrew.org/wiki/CIA
  - https://www.3dbrew.org/wiki/RomFS
"""

from tex_forge.rom.loader import parse_rom  # noqa: F401

__all__ = ["parse_rom"]
