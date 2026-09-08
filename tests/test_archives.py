"""Smoke-test that archive plugins detect their magics."""

import struct

from tex_forge.archives.registry import detect_archive


def test_garc_detect():
    fake = b"CRAG" + struct.pack("<I", 0x1C) + b"\xff\xfe\x00\x00" + b"\x00" * 200
    plugin = detect_archive(fake)
    assert plugin is not None and plugin.name == "garc"


def test_sarc_detect():
    fake = (b"SARC" + struct.pack("<HH", 0x14, 0xFEFE) +
            struct.pack("<II", 0x14, 0x14) + struct.pack("<HH", 0x100, 0))
    plugin = detect_archive(fake)
    assert plugin is not None and plugin.name == "sarc"


def test_no_match_returns_none():
    assert detect_archive(b"NotAnArchive") is None


def test_priorities_sorted():
    """Plugins should be iterated in descending priority order."""
    from tex_forge.archives.registry import iter_plugins
    priorities = [r.priority for r in iter_plugins()]
    assert priorities == sorted(priorities, reverse=True)
