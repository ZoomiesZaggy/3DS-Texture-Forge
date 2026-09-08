"""Registry for archive container plugins.

The pipeline calls detect_archive(data) to find the matching plugin in
descending priority order, then calls plugin.iter_entries(data) to walk
the inner files.

Plugin contract:

    name        -- short identifier ("garc", "sarc", ...). Used in logs and
                   the manifest's container_chain field.
    priority    -- int. Higher wins ties when multiple plugins detect.
    detect(data) -- cheap magic-byte test.
    iter_entries(data) -> Iterator[ArchiveEntry]
                   yields one entry per inner file. Each entry's `data`
                   is bytes -- already decompressed if the archive uses
                   per-entry compression (e.g. GFAC's GFCP, MT-Framework's
                   zlib).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator, List, Optional, Protocol, runtime_checkable

from tex_forge.core.types import ArchiveEntry


@runtime_checkable
class ArchivePlugin(Protocol):
    """Static-style protocol -- archive plugins are typically classes with @staticmethod."""

    @staticmethod
    def detect(data: bytes) -> bool: ...

    @staticmethod
    def iter_entries(data: bytes) -> Iterator[ArchiveEntry]: ...


@dataclass(slots=True)
class _Registered:
    name: str
    priority: int
    plugin: ArchivePlugin
    note: str = ""


_PLUGINS: List[_Registered] = []


def register_archive(name: str, *, priority: int = 0, note: str = "") -> Callable:
    """Decorator: register *cls* as the archive plugin for *name*.

    Usage:

        @register_archive("garc", priority=100)
        class _GARC:
            @staticmethod
            def detect(data): ...
            @staticmethod
            def iter_entries(data): ...
    """
    def wrap(cls):
        _PLUGINS.append(_Registered(name, priority, cls, note))
        _PLUGINS.sort(key=lambda r: -r.priority)
        return cls

    return wrap


def iter_plugins() -> Iterator[_Registered]:
    yield from _PLUGINS


def detect_archive(data: bytes) -> Optional[_Registered]:
    """Return the first registered plugin whose detect() accepts *data*, or None."""
    for r in _PLUGINS:
        try:
            if r.plugin.detect(data):
                return r
        except Exception:  # pragma: no cover -- detect should never raise
            continue
    return None


def get_plugin(name: str) -> Optional[ArchivePlugin]:
    for r in _PLUGINS:
        if r.name == name:
            return r.plugin
    return None
