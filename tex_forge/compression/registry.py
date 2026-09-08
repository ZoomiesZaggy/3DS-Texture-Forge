"""Plugin registry for decompression codecs.

Each codec registers a (detect, decompress) pair plus a name and a priority.
The dispatcher walks codecs in *descending* priority and returns the first
match -- so put more-specific magics (Yaz0, CRILAYLA) at high priority and
broad heuristics (zlib, LZ-by-first-byte) lower.

Codec contract:

    detect(data: bytes) -> bool
        Cheap magic-byte check. False positives are tolerable but expensive.

    decompress(data: bytes) -> bytes | None
        Full decompression. Return None on failure rather than raising;
        callers usually want to fall through to the next codec.

A codec's `decompress` may be invoked even if `detect` returned False --
the pipeline sometimes pre-filters by extension and then probes a single
codec directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

DetectFn = Callable[[bytes], bool]
DecompressFn = Callable[[bytes], Optional[bytes]]


@dataclass(slots=True)
class Decompressed:
    """Result of a successful decompression."""

    data: bytes
    codec: str
    original_size: int

    def __len__(self) -> int:
        return len(self.data)


@dataclass(slots=True)
class _Codec:
    name: str
    priority: int
    detect: DetectFn
    decompress: DecompressFn
    note: str = ""


_CODECS: List[_Codec] = []


def register_compression(
    name: str,
    *,
    priority: int = 0,
    note: str = "",
) -> Callable:
    """Decorator: register a (detect, decompress) pair under *name*.

    Usage:

        @register_compression("yaz0", priority=100)
        class _Yaz0:
            @staticmethod
            def detect(data): ...
            @staticmethod
            def decompress(data): ...
    """
    def wrap(cls):
        codec = _Codec(
            name=name,
            priority=priority,
            detect=cls.detect,
            decompress=cls.decompress,
            note=note,
        )
        _CODECS.append(codec)
        _CODECS.sort(key=lambda c: -c.priority)
        return cls

    return wrap


def iter_codecs():
    """Yield codecs in descending priority order. Useful for tests / debugging."""
    yield from _CODECS


def try_decompress(data: bytes, *, hint: Optional[str] = None) -> Optional[Decompressed]:
    """Try each registered codec, returning the first one that decodes successfully.

    *hint* (optional): if a specific codec name is supplied, try that one first
    before falling back to the auto-detection chain. Useful when the caller
    has already established the codec from a file extension or a wrapper.
    """
    if hint is not None:
        for c in _CODECS:
            if c.name == hint:
                out = c.decompress(data)
                if out is not None:
                    return Decompressed(out, c.name, len(data))
                break

    for c in _CODECS:
        if not c.detect(data):
            continue
        out = c.decompress(data)
        if out is not None:
            return Decompressed(out, c.name, len(data))

    return None


def decompress_by_name(name: str, data: bytes) -> Optional[bytes]:
    """Look up a codec by name and call its decompress(); None if unknown."""
    for c in _CODECS:
        if c.name == name:
            return c.decompress(data)
    return None
