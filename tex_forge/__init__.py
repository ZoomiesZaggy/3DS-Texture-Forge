"""3DS Texture Forge -- extract textures from Nintendo 3DS ROMs.

Public surface area: import the things you need from their canonical modules.

    from tex_forge.core.types import Texture, ArchiveEntry, FilePeek
    from tex_forge.core.exceptions import EncryptedROMError, ROMParseError
    from tex_forge.pipeline.extractor import ExtractionPipeline, ExtractOptions
    from tex_forge.rom import parse_rom
    from tex_forge.textures.formats import PicaFormat
"""

__version__ = "2.0.0"
