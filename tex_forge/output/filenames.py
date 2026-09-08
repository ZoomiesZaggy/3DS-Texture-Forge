"""Output filename / path helpers.

Two flavours:
  generate_filename(idx, tex)   -> "tex_NNNN_<name>_<fmt>_<W>x<H>.png"
  build_output_path(dir, src, fname)
                                -> mirror inner archive paths under a textures/ subtree

Plus sanitise_subdir() that turns "a.garc>0001.cgfx" into a directory tree.

Path-traversal defence (audit findings F028 / F048):
  * '..', '.', and empty segments are dropped from any source_path before
    composition.
  * The composed path is checked with os.path.realpath / os.path.commonpath
    against the realpath of output_dir. If the result lies outside output_dir
    (e.g. via a symlink-following segment), build_output_path raises
    ValueError. Callers should let this propagate -- a tampered archive is a
    security event, not a recoverable parser error.

We use os.path.realpath, not os.path.abspath, so symlink-following escape
attempts are caught at the boundary check.
"""

from __future__ import annotations

import os
from typing import Any, Dict

from tex_forge.textures.formats import name as fmt_name


def generate_filename(index: int, tex: Dict[str, Any]) -> str:
    """Compose a filesystem-safe filename for a texture.

    If the texture has a name (e.g. from CGFX texture metadata), include it.
    Otherwise just index + format + dimensions.
    """
    fmt = fmt_name(tex.get("format", 0))
    w = tex.get("width", 0)
    h = tex.get("height", 0)
    name = tex.get("name", "")
    if name:
        name = name.replace("\\", "_").replace("/", "_").replace(" ", "_")
        name = "".join(c for c in name if c.isalnum() or c in ("_", "-", "."))
        return f"tex_{index:04d}_{name}_{fmt}_{w}x{h}.png"
    return f"tex_{index:04d}_{fmt}_{w}x{h}.png"


def _drop_traversal_segments(parts):
    """Drop empty, '.', and '..' segments. Used by build_output_path / sanitise_subdir."""
    return [p for p in parts if p and p != "." and p != ".."]


def build_output_path(output_dir: str, source_path: str, filename: str) -> str:
    """Stick *filename* inside output_dir/textures/<mirrored_source_dirs>/.

    Source-path components equal to '..', '.', or empty are dropped. The
    final composed path is verified to lie under output_dir via realpath +
    commonpath; mismatch raises ValueError.
    """
    parts: list[str] = []
    if source_path:
        # Treat both '/' and '\\' as separators, plus our scanner-internal
        # '>' which composes nested-archive breadcrumbs (a.garc>b.cgfx).
        clean = source_path.replace("\\", "/").replace(">", "/").lstrip("/")
        # split + drop the source filename + drop '..'/'.'/empty
        all_segs = clean.split("/")
        if all_segs:
            all_segs = all_segs[:-1]   # drop the leaf (which is the source file)
        parts = _drop_traversal_segments(all_segs)

    if parts:
        result = os.path.join(output_dir, "textures", *parts, filename)
    else:
        result = os.path.join(output_dir, "textures", filename)

    # Boundary check: the resolved result must lie under the resolved output_dir.
    # On Windows there are two quirks to handle:
    #   1. os.path.commonpath raises ValueError when the two paths are on
    #      different drives -- that's a boundary violation, treat as escape.
    #   2. os.path.realpath sometimes returns the \\?\ extended-length prefix
    #      for long paths, but only on one of the two inputs. That makes
    #      commonpath think the paths are unrelated even when they're the
    #      same location. Normalise both sides by stripping \\?\ before
    #      comparing.
    def _norm_for_compare(p: str) -> str:
        rp = os.path.realpath(p)
        if rp.startswith("\\\\?\\"):
            rp = rp[4:]
        # Also normalise case + separators on Windows for a stable compare.
        return os.path.normcase(rp)

    out_real_cmp = _norm_for_compare(output_dir)
    res_real_cmp = _norm_for_compare(result)
    try:
        common = os.path.commonpath([out_real_cmp, res_real_cmp])
    except ValueError:
        common = None
    if common != out_real_cmp:
        raise ValueError(
            f"build_output_path: resolved path {os.path.realpath(result)!r} "
            f"escapes output_dir {os.path.realpath(output_dir)!r}; "
            f"refusing to write."
        )
    return result


def sanitise_subdir(source_path: str) -> str:
    """Turn 'a.garc>0001.cgfx' into a clean subdir like 'a.garc/0001.cgfx',
    with '..' / '.' / empty segments dropped.

    Output is a relative path with forward-slash separators. Never starts
    with '/' or '..'; never contains a '..' segment.
    """
    if not source_path:
        return ""
    clean = source_path.replace("\\", "/").replace(">", "/").lstrip("/")
    parts = clean.split("/")
    if parts:
        parts = parts[:-1]
    return "/".join(_drop_traversal_segments(parts))
