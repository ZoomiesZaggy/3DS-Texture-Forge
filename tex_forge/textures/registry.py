"""Registry for texture-container plugins (BCH, CGFX, CTPK, BFLIM, ...).

Mirrors archives.registry but for *texture-bearing* files. The pipeline
calls detect_texture(data) to find the matching plugin in priority order,
then iter_textures() yields one Texture per image inside the container.

Plugin contract:

    name        -- short identifier ("bch", "cgfx", "ctpk", ...).
    priority    -- int, higher = checked first.
    detect(data) -> bool
    iter_textures(data, source_path: str) -> Iterator[Texture]
                   Each Texture's .data is raw morton-tiled pixel bytes
                   ready for the decoder, plus width/height/format/etc.

Why both archives.registry AND textures.registry, with the same shape?
Because they're called from different points in the pipeline and have
different semantics: archive plugins emit *more files* (recursed back into
the scanner), texture plugins emit *decodable images* (sent straight to
the decoder + PNG writer).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator, List, Optional, Protocol, runtime_checkable

from tex_forge.core.types import Texture


@runtime_checkable
class TexturePlugin(Protocol):
    @staticmethod
    def detect(data: bytes) -> bool: ...

    @staticmethod
    def iter_textures(data: bytes, source_path: str = "") -> Iterator[Texture]: ...


@dataclass(slots=True)
class _Registered:
    name: str
    priority: int
    plugin: TexturePlugin
    note: str = ""


_PLUGINS: List[_Registered] = []


def register_texture(name: str, *, priority: int = 0, note: str = "") -> Callable:
    def wrap(cls):
        _PLUGINS.append(_Registered(name, priority, cls, note))
        _PLUGINS.sort(key=lambda r: -r.priority)
        return cls
    return wrap


def iter_plugins() -> Iterator[_Registered]:
    yield from _PLUGINS


def detect_texture(data: bytes) -> Optional[_Registered]:
    for r in _PLUGINS:
        try:
            if r.plugin.detect(data):
                return r
        except Exception:
            continue
    return None


def get_plugin(name: str) -> Optional[TexturePlugin]:
    for r in _PLUGINS:
        if r.name == name:
            return r.plugin
    return None
