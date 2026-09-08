"""Exceptions surfaced to callers (CLI, GUI, library users).

The CLI catches these by type to print actionable error messages -- in
particular, EncryptedROMError gets the GodMode9 hint.
"""


class TexForgeError(Exception):
    """Base for all 3DS Texture Forge exceptions. Useful as a catch-all."""


class ROMParseError(TexForgeError):
    """Raised when the outermost ROM container can't be parsed."""


class EncryptedROMError(TexForgeError):
    """Raised when an NCCH partition is encrypted (NoCrypto flag clear).

    The CLI uses this exception to print the GodMode9 decryption guide.
    Catch this *before* :class:`ROMParseError`.
    """


class DecodeError(TexForgeError):
    """Raised when a pixel decoder hits an unrecoverable invariant violation.

    Most decoder failures are *not* exceptional -- they're returned as None
    and counted in the failure manifest. Reserve this for actual bugs (e.g.
    a NumPy reshape mismatch that should never happen).
    """


class CompressionError(TexForgeError):
    """Raised when decompression fails in a way the caller can't recover from.

    Most decompressors return None on failure; this is for catastrophic
    cases (corrupt header, infinite loop guard tripped, etc.).
    """
