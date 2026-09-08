"""FileFilter: which RomFS files are even worth peeking at?

A 3DS RomFS can have hundreds of thousands of files; reading every single
one to check its magic bytes is wasted I/O. The filter has three signals:

  1. Hard-skip extensions: audio, fonts, shaders, scripts, save files, etc.
     If the file ends in one of these, drop it without looking inside.

  2. Process extensions: file extensions known to contain textures.
     If the file ends in one of these, accept it unconditionally.

  3. Process directories: substrings in the path that suggest texture
     content -- "/textures/", "/ui/", "/chr/", etc. Often a game uses an
     unrecognised extension (or no extension at all) inside these dirs.

For files that pass none of the above but exist in the RomFS, the pipeline
peeks at the first few bytes and uses classify_file() to decide.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet, Set


# ─────────────────────────────────────────────────────────────────────────────
# Defaults -- copied from v1 main.py, kept centralised so we can override.
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_SKIP_EXTENSIONS: FrozenSet[str] = frozenset({
    ".bcstm", ".bcwav", ".bcsnd", ".bcsar",  # audio
    ".bgm", ".brsar", ".bfsar", ".bfstm",
    ".moflex", ".mods",                      # video
    ".msbt", ".bmg",                         # localisation strings
    ".bfttf", ".bcfnt",                      # fonts
    ".shbin", ".bcsv",                       # shaders / CSV
    ".txt", ".xml", ".json", ".lua",
    ".db", ".sav",
    ".mp4", ".aac", ".ogg", ".wav",
    ".ips", ".bps",
})

DEFAULT_PROCESS_EXTENSIONS: FrozenSet[str] = frozenset({
    ".tex", ".bch", ".bcres", ".bflim", ".bclim",
    ".ctpk", ".cptk", ".ctxb", ".cmb", ".cgfx",
    ".bcmdl", ".bctex", ".bcmcla", ".szs",
    ".zar", ".zsi",
    ".bccam", ".bcsdr", ".bcptl", ".bhres", ".bhtex", ".cbres",
    ".lz", ".cmp",
    ".chres", ".chtex", ".stex",
    ".gar", ".lzs", ".zrc", ".fs", ".texturegdb",
    ".bin", ".raw", ".dat", ".img", ".arc", ".sarc", ".garc", ".narc",
    ".nwmdl", ".nwtex", ".pmnweffb", ".nwenv", ".nwlyt",
    ".fa", ".cpk", ".jtex", ".jarc", ".data", ".gfa",
})

DEFAULT_PROCESS_DIRS: FrozenSet[str] = frozenset({
    "/tex/", "/texture/", "/textures/", "/gui/", "/effect/",
    "/model/", "/chr/", "/bg/", "/ui/", "/font/", "/a/",
    "/kart/", "/course/", "/driver/", "/menu",
    "/actor/", "/scene/", "/kankyo/", "/ending/", "/misc/",
})

# Magic bytes that mean "definitely not a texture, even if extension is
# unknown" -- usually audio banks. Keeping these out of the peek path saves
# significant I/O on non-texture-heavy ROMs.
NEVER_TEXTURES: FrozenSet[bytes] = frozenset({
    b"BKHD", b"AKPK", b"CSAR", b"NUS3", b"RIFF",
})

# Magic bytes that are texture-bearing even with unknown extension.
TEXTURE_MAGICS: FrozenSet[bytes] = frozenset({
    b"CRAG", b"SARC", b"NARC", b"darc", b"Yaz0",
    b"CGFX", b"BCH\x00", b"CTPK", b"CTXB", b"ARC\x00", b"ARC0",
    b"CPK ", b"ZAR\x01", b"GAR2", b"jIMG", b"GDB1",
    b"3DST", b"GFAC", b"XFSA",
})


@dataclass(slots=True)
class FileFilter:
    """Rule set for "is this file worth peeking at?"

    Customise via constructor args; otherwise uses DEFAULT_* sets.
    """

    skip_extensions:    Set[str] = field(default_factory=lambda: set(DEFAULT_SKIP_EXTENSIONS))
    process_extensions: Set[str] = field(default_factory=lambda: set(DEFAULT_PROCESS_EXTENSIONS))
    process_dirs:       Set[str] = field(default_factory=lambda: set(DEFAULT_PROCESS_DIRS))
    scan_all: bool = False

    def should_peek(self, path: str, peek_data: bytes = b"",
                    tail_data: bytes = b"") -> bool:
        """Return True iff this file is worth at least a magic-byte peek.

        Path-only checks are fast (extension, directory). Magic checks are
        used only when the path doesn't classify (peek_data is provided
        by the caller, usually first 0x30 bytes; tail_data is the last 0x28
        bytes, needed because BFLIM/BCLIM put their magic in a footer).
        """
        if self.scan_all:
            return True

        ext = ""
        if "." in path:
            ext = "." + path.rsplit(".", 1)[-1].lower()
        if ext in self.skip_extensions:
            return False
        if ext in self.process_extensions:
            return True

        path_lower = path.lower()
        if any(d in path_lower for d in self.process_dirs):
            return True

        if peek_data and len(peek_data) >= 4:
            magic4 = peek_data[:4]
            if magic4 in TEXTURE_MAGICS:
                return True
            if peek_data[0] in (0x10, 0x11, 0x13):  # LZ leading byte
                return True
            if len(peek_data) >= 6 and peek_data[4:6] == b"\x1f\x8b":  # gzip-prefix
                return True
            # Tiny files: the head peek IS the whole file, so a footer check
            # against it is valid.
            if len(peek_data) >= 0x28:
                if peek_data[-0x28:-0x24] in (b"FLIM", b"CLIM"):
                    return True

        # BFLIM/BCLIM magic lives 0x28 bytes before file end (footer header),
        # so it is only visible in a tail peek. Before tail_data existed this
        # check could never fire for files larger than the 0x30-byte head peek.
        if tail_data and len(tail_data) >= 0x28:
            if tail_data[-0x28:-0x24] in (b"FLIM", b"CLIM"):
                return True

        return False

    def is_definitely_not_texture(self, peek_data: bytes) -> bool:
        return len(peek_data) >= 4 and peek_data[:4] in NEVER_TEXTURES
