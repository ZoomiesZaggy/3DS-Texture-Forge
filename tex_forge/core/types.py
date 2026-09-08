"""Dataclasses passed between layers of the pipeline.

These are deliberately *plain dataclasses*, not pydantic models -- everything
in the hot path runs millions of times per ROM and the overhead matters.

Layer cheat sheet (top to bottom):

    +-------------------------------------------------------+
    | ExtractionPipeline (pipeline/extractor.py)            |
    |   yields manifest dicts per output texture            |
    +-------------------------------------------------------+
                          |
    +-------------------------------------------------------+
    | ArchivePlugin / TexturePlugin (archives/, textures/)  |
    |   yields ArchiveEntry  ->  yields Texture             |
    +-------------------------------------------------------+
                          |
    +-------------------------------------------------------+
    | core/types.py (Texture, ArchiveEntry, FilePeek)       |
    +-------------------------------------------------------+
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Path-traversal-safe name sanitiser
#
# Archive entry names come from inside the binary file we're parsing -- they're
# attacker-controlled. This sanitiser is the single chokepoint that strips path
# separators, drops '..' segments, rejects null bytes / control characters,
# avoids Windows-reserved basenames, and guarantees the result is a clean
# relative path with forward-slash separators that downstream layers can mirror
# safely under output_dir.
#
# Closes audit findings F028/F030/F031/F048 at the source.
# ─────────────────────────────────────────────────────────────────────────────

# Characters that are invalid on Windows (or trouble on macOS/Linux) and must
# never appear inside a path component. Forward-slash and backslash are
# handled separately as path SEPARATORS, so they're not in this set.
_UNSAFE_CHARS: frozenset[str] = frozenset('<>:"|?*')

# Windows-reserved basenames (case-insensitive). Names like "CON.cgfx" are
# blocked by the OS even with an extension, so we append a trailing underscore
# to the BASE name to neutralise them: CON.cgfx -> CON_.cgfx.
_WIN_RESERVED: frozenset[str] = frozenset({
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
})


def _sanitise_segment(seg: str) -> str:
    """Sanitise one path component.

    - Drops null bytes and ASCII control characters (< 0x20 and 0x7F).
    - Replaces unsafe chars (< > : " | ? *) with '_'.
    - Neutralises Windows-reserved basenames by trailing-underscore.
    - Returns '' for segments that should be discarded ('..', '.', empty).
    """
    if seg in ("", ".", ".."):
        return ""
    # Drop control characters and null bytes; replace unsafe chars.
    cleaned = []
    for ch in seg:
        cp = ord(ch)
        if cp < 0x20 or cp == 0x7F:
            # control / null -> drop
            continue
        if ch in _UNSAFE_CHARS:
            cleaned.append("_")
        else:
            cleaned.append(ch)
    out = "".join(cleaned)
    if not out or out in (".", ".."):
        return ""
    # Windows reserved basename check (case-insensitive, on the part before '.')
    base = out.split(".", 1)[0].upper()
    if base in _WIN_RESERVED:
        # Inject an underscore after the base name. CON.cgfx -> CON_.cgfx
        if "." in out:
            head, tail = out.split(".", 1)
            out = f"{head}_.{tail}"
        else:
            out = f"{out}_"
    return out


def sanitise_archive_name(raw: str, *, fallback: str = "_unnamed") -> str:
    """Turn a raw archive entry name into a safe relative path.

    Guarantees about the result:
      * No leading '/' or '\\'.
      * No '..' or '.' segments.
      * Forward-slash separators only.
      * No null bytes, control characters, or Windows-reserved basenames.
      * Never empty -- empty input maps to *fallback*.

    The result is still a *relative* path (may contain inner '/'). Callers
    that want a single flat name should additionally `.replace("/", "_")`
    or take only the last segment.
    """
    if not isinstance(raw, str):
        raw = str(raw)
    # Normalise both separator flavours; collapse to '/'-delimited segments.
    normalised = raw.replace("\\", "/")
    parts = normalised.split("/")
    safe_parts = []
    for seg in parts:
        out = _sanitise_segment(seg)
        if out:
            safe_parts.append(out)
    if not safe_parts:
        return fallback
    return "/".join(safe_parts)


# ─────────────────────────────────────────────────────────────────────────────
# What an archive emits (one entry from a GARC, SARC, ZAR, etc.)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class ArchiveEntry:
    """A single inner file extracted from a container archive.

    The archive plugins don't decode textures -- they just emit raw bytes
    plus a hint of the original filename. The pipeline routes those bytes
    back through the scanner, recursively if needed.

    The *name* field is sanitised in __post_init__ via sanitise_archive_name
    so downstream path composition cannot escape output_dir.
    """

    name: str               # inner filename (e.g. "0042.cgfx", "ui/menu.bflim")
    data: bytes             # raw inner-file bytes
    parent_path: str = ""   # outer archive path for breadcrumb logging

    def __post_init__(self) -> None:
        # Centralised sanitisation -- closes path-traversal cluster
        # F028/F030/F031/F048 from the audit.
        self.name = sanitise_archive_name(self.name)


# ─────────────────────────────────────────────────────────────────────────────
# What a texture-container plugin emits (one decoded texture)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class Texture:
    """A texture ready to be decoded into RGBA8 pixels.

    The texture plugin does *not* decode pixels -- that's the decoder's job.
    The plugin only tells the pipeline:
      * here are the raw pixel bytes (still in PICA200 morton-tiled format)
      * width / height / format / mipmap count
      * if BFLIM-style: the visible region inside a power-of-2 atlas
      * a confidence rating, used for dedup tie-breaking and quality reports
    """

    name: str = ""              # texture name from container, if any
    width: int = 0
    height: int = 0
    format: int = 0             # PICA200 format ID (see textures.formats.PicaFormat)
    data: bytes = b""           # raw morton-tiled pixel bytes
    mip_count: int = 1
    crop_width: int = 0         # >0 => visible width inside W (BFLIM/BCLIM)
    crop_height: int = 0        # >0 => visible height inside H (BFLIM/BCLIM)
    parser_used: str = "unknown"
    confidence: str = "high"    # high / medium / low
    source_file: str = ""       # ROM-relative path or breadcrumb (a.garc>b.cgfx)
    notes: List[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)  # parser-specific overflow

    def __post_init__(self) -> None:
        # Defensive: callers occasionally pass numpy.int64 from header reads.
        # Convert to plain Python ints so downstream PNG / hash / JSON is happy.
        self.width = int(self.width)
        self.height = int(self.height)
        self.format = int(self.format)
        self.mip_count = int(self.mip_count)
        self.crop_width = int(self.crop_width)
        self.crop_height = int(self.crop_height)


# ─────────────────────────────────────────────────────────────────────────────
# Lightweight file classification result
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class FilePeek:
    """Cheap, magic-byte-only classification of a file's outer container.

    Produced by pipeline.scanner.classify_file. Kept tiny because the
    scanner runs once per RomFS file -- can be hundreds of thousands of
    invocations on a Pokemon ROM.
    """

    path: str
    size: int
    ext: str
    magic4: bytes
    detected_type: Optional[str] = None  # plugin id, e.g. "garc", "bch", "lz_nintendo"
    confidence: str = "none"             # high / medium / low / none

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "size": self.size,
            "ext": self.ext,
            "magic": self.magic4.hex() if self.magic4 else "",
            "detected_type": self.detected_type,
            "confidence": self.confidence,
        }
