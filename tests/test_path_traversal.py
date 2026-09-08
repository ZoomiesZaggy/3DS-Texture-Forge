"""Path-traversal regression suite.

Closes audit findings F028, F030, F031, F048. These tests assert the
*property* that downstream paths cannot escape output_dir / project_dir,
not just the *string shape* of intermediate values -- "no '..' in the
result" would not be the same property.
"""

import json
import os
import shutil
import struct
import tempfile

import pytest

from tex_forge.core.types import ArchiveEntry, sanitise_archive_name
from tex_forge.output.filenames import build_output_path, sanitise_subdir
from tex_forge.output.pack_builder import build_pack
from tex_forge.output.png_writer import save_png


# ─────────────────────────────────────────────────────────────────────────
# Layer 1 -- ArchiveEntry name sanitiser
# ─────────────────────────────────────────────────────────────────────────

def test_archive_entry_strips_dotdot_segments():
    e = ArchiveEntry(name="../../etc/passwd", data=b"x")
    assert ".." not in e.name.split("/")
    # The remaining safe components survive: 'etc/passwd' (each safe)
    assert e.name == "etc/passwd"


def test_archive_entry_strips_leading_slash():
    e = ArchiveEntry(name="/absolute/path", data=b"x")
    assert not e.name.startswith("/")
    assert e.name == "absolute/path"


def test_archive_entry_drops_inner_dotdot():
    e = ArchiveEntry(name="a/../../b", data=b"x")
    assert ".." not in e.name.split("/")
    # 'a' and 'b' survive; both '..' are dropped.
    assert e.name == "a/b"


def test_archive_entry_normalises_backslashes():
    e = ArchiveEntry(name="\\windows\\style", data=b"x")
    assert "\\" not in e.name
    assert e.name == "windows/style"


def test_archive_entry_drops_null_bytes():
    e = ArchiveEntry(name="null\x00byte", data=b"x")
    assert "\x00" not in e.name
    # Null byte is dropped -> "nullbyte"
    assert e.name == "nullbyte"


def test_archive_entry_empty_name_uses_fallback():
    e = ArchiveEntry(name="", data=b"x")
    assert e.name == "_unnamed"


def test_archive_entry_pure_dotdot_uses_fallback():
    e = ArchiveEntry(name="..", data=b"x")
    assert e.name == "_unnamed"


def test_archive_entry_pure_dot_uses_fallback():
    e = ArchiveEntry(name=".", data=b"x")
    assert e.name == "_unnamed"


def test_archive_entry_only_separators_uses_fallback():
    e = ArchiveEntry(name="///", data=b"x")
    assert e.name == "_unnamed"


def test_archive_entry_windows_reserved_basename_renamed():
    """CON.cgfx is reserved on Windows even with extension; CON_.cgfx is not."""
    e = ArchiveEntry(name="CON.cgfx", data=b"x")
    assert e.name == "CON_.cgfx"


def test_archive_entry_windows_reserved_no_ext_renamed():
    e = ArchiveEntry(name="LPT1", data=b"x")
    assert e.name == "LPT1_"


def test_archive_entry_unsafe_chars_replaced():
    """The < > : " | ? * set is invalid on Windows."""
    e = ArchiveEntry(name='bad<name>:"|?*.cgfx', data=b"x")
    assert "<" not in e.name and ">" not in e.name and ":" not in e.name
    assert '"' not in e.name and "|" not in e.name and "?" not in e.name and "*" not in e.name
    assert e.name.endswith(".cgfx")


def test_archive_entry_control_characters_dropped():
    e = ArchiveEntry(name="text\x01\x02\x1ftab", data=b"x")
    for c in "\x01\x02\x1f":
        assert c not in e.name


def test_archive_entry_preserves_inner_paths_for_legit_names():
    """Legitimate inner paths like 'ui/menu/icon.bflim' should survive."""
    e = ArchiveEntry(name="ui/menu/icon.bflim", data=b"x")
    assert e.name == "ui/menu/icon.bflim"


def test_sanitise_archive_name_idempotent():
    """Sanitising twice is the same as sanitising once."""
    raw = "../../etc/CON.cgfx"
    once = sanitise_archive_name(raw)
    twice = sanitise_archive_name(once)
    assert once == twice


# ─────────────────────────────────────────────────────────────────────────
# Layer 2 -- build_output_path defence-in-depth
# ─────────────────────────────────────────────────────────────────────────

def test_build_output_path_drops_dotdot_segments():
    with tempfile.TemporaryDirectory() as out:
        result = build_output_path(out, "evil.cpk>../foo>file.cgfx", "tex.png")
        out_real = os.path.realpath(out)
        res_real = os.path.realpath(result)
        # The PROPERTY: result must lie under output_dir.
        assert os.path.commonpath([out_real, res_real]) == out_real, \
            f"escape detected: {res_real} not under {out_real}"


def test_build_output_path_handles_deep_dotdot_chain():
    with tempfile.TemporaryDirectory() as out:
        # 6 levels of ".." would have escaped output_dir/textures/ in v1.
        result = build_output_path(out, "a/../../../../../../etc/passwd", "tex.png")
        out_real = os.path.realpath(out)
        res_real = os.path.realpath(result)
        assert os.path.commonpath([out_real, res_real]) == out_real


def test_build_output_path_audit_repro_F028():
    """Original F028 repro: source_path 'evil.cpk>../../etc/passwd>inner.cgfx'."""
    with tempfile.TemporaryDirectory() as out:
        result = build_output_path(
            out, "evil.cpk>../../etc/passwd>inner.cgfx", "tex_0001.png"
        )
        out_real = os.path.realpath(out)
        res_real = os.path.realpath(result)
        # MUST be under output_dir -- this is the property that v1 violated.
        assert os.path.commonpath([out_real, res_real]) == out_real, \
            f"F028 repro NOT closed: {res_real} escapes {out_real}"


def test_build_output_path_normal_case_unaffected():
    """A clean source_path should produce the same path it always did."""
    with tempfile.TemporaryDirectory() as out:
        result = build_output_path(out, "some/inner/file.cgfx", "tex_0001.png")
        # Path mirrors source_path under textures/ minus the leaf filename.
        # 'some/inner/file.cgfx' -> 'some/inner/' as subdir.
        expected_suffix = os.path.join("textures", "some", "inner", "tex_0001.png")
        assert result.endswith(expected_suffix)


def test_sanitise_subdir_rejects_dotdot():
    s = sanitise_subdir("evil>../etc>file.cgfx")
    assert ".." not in s.split("/")


def test_sanitise_subdir_empty_input():
    assert sanitise_subdir("") == ""


# ─────────────────────────────────────────────────────────────────────────
# Layer 3 -- pack_builder rejects out-of-project manifest paths
# ─────────────────────────────────────────────────────────────────────────

def _write_dummy_png(path: str) -> None:
    """Write a minimal valid PNG so build_pack's os.path.isfile gate passes."""
    import numpy as np
    rgba = np.full((4, 4, 4), 100, dtype=np.uint8)
    rgba[..., 3] = 255
    save_png(rgba, path)


def test_build_pack_rejects_manifest_path_outside_project():
    """A tampered manifest pointing at a file outside the project dir must
    raise IOError, not silently copy."""
    with tempfile.TemporaryDirectory() as project:
        # 1. Write a real PNG OUTSIDE project_dir to act as the attacker target.
        outside = tempfile.mkdtemp()
        try:
            outside_png = os.path.join(outside, "stolen.png")
            _write_dummy_png(outside_png)

            # 2. Write a manifest claiming decoded_png_path points there.
            manifest_textures = [{
                "id": "tex_0001",
                "decoded_png_path": outside_png,   # ABSOLUTE path outside project
                "width": 4, "height": 4,
                "detected_format": "RGBA8",
                "source_file_path": "fake.cgfx",
            }]

            # 3. build_pack must REFUSE -- IOError, not silently copy.
            with pytest.raises(IOError):
                build_pack(project, "0004000000055E00", manifest_textures, mode="staging")
        finally:
            shutil.rmtree(outside, ignore_errors=True)


def test_build_pack_accepts_manifest_path_inside_project():
    """Sanity: the legitimate path still works."""
    with tempfile.TemporaryDirectory() as project:
        # Write a PNG INSIDE project's textures/ subtree.
        tex_dir = os.path.join(project, "textures")
        os.makedirs(tex_dir, exist_ok=True)
        png_inside = os.path.join(tex_dir, "tex.png")
        _write_dummy_png(png_inside)

        manifest_textures = [{
            "id": "tex_0001",
            "decoded_png_path": "textures/tex.png",  # relative inside project
            "width": 4, "height": 4,
            "detected_format": "RGBA8",
            "source_file_path": "fake.cgfx",
        }]
        # No exception, pack succeeds.
        pack_dir, _pack_meta = build_pack(
            project, "0004000000055E00", manifest_textures, mode="staging",
        )
        assert os.path.isdir(pack_dir)
        assert os.path.isfile(os.path.join(pack_dir, "forge_pack_meta.json"))


# ─────────────────────────────────────────────────────────────────────────
# Layer 4 -- end-to-end: ArchiveEntry sanitisation feeds clean source_path
# ─────────────────────────────────────────────────────────────────────────

def test_archive_entry_then_build_output_path_safe():
    """Even if someone bypasses the centralised sanitiser and synthesises a
    raw breadcrumb, build_output_path's own dropping + commonpath check
    must keep the result under output_dir."""
    with tempfile.TemporaryDirectory() as out:
        e = ArchiveEntry(name="../../../etc/passwd", data=b"x")
        # First-layer fix: e.name was sanitised
        assert ".." not in e.name.split("/")
        # Second-layer fix: even if the breadcrumb were tampered, build_output_path holds
        breadcrumb = f"rom>{e.name}>inner.cgfx"
        result = build_output_path(out, breadcrumb, "tex.png")
        out_real = os.path.realpath(out)
        res_real = os.path.realpath(result)
        assert os.path.commonpath([out_real, res_real]) == out_real
