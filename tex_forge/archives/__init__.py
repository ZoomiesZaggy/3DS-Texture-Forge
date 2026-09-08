"""Archive (container) plugins -- GARC, SARC, ZAR, ARC, CPK, etc.

Pattern: each archive format gets one module that defines a class, decorated
with @register_archive("name", priority=N). The class implements:

    @staticmethod
    def detect(data: bytes) -> bool: ...
    @staticmethod
    def iter_entries(data: bytes) -> Iterator[ArchiveEntry]: ...

The pipeline uses pipeline.scanner to classify each RomFS file by magic, then
calls the matched plugin's iter_entries() and recurses on each entry.

Side-effect imports below register every plugin as the package loads.
"""

from tex_forge.archives.registry import (  # noqa: F401
    ArchivePlugin,
    register_archive,
    iter_plugins,
    detect_archive,
)

# Side-effect imports -- registers each plugin.
from tex_forge.archives import garc        # noqa: F401
from tex_forge.archives import sarc        # noqa: F401
from tex_forge.archives import narc        # noqa: F401
from tex_forge.archives import zar         # noqa: F401
from tex_forge.archives import gar         # noqa: F401
from tex_forge.archives import darc        # noqa: F401
from tex_forge.archives import arc_capcom  # noqa: F401
from tex_forge.archives import arc_fe      # noqa: F401
from tex_forge.archives import smash_dt    # noqa: F401
from tex_forge.archives import l5_flat     # noqa: F401
from tex_forge.archives import gfac        # noqa: F401
from tex_forge.archives import arc0        # noqa: F401
from tex_forge.archives import cpk         # noqa: F401

__all__ = [
    "ArchivePlugin",
    "register_archive",
    "iter_plugins",
    "detect_archive",
]
