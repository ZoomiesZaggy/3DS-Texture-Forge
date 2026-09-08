"""Custom-texture pack builder for Azahar/Citra.

Three modes:
  azahar  -- the manifest carries `azahar_hash_cityhash64` for each
             texture (computed offline at extract time via CityHash64
             of the raw GPU bytes). Output is a drop-in pack with
             `tex1_<W>x<H>_<HASH>_<code>.png` filenames; no emulator
             dump required.
  mapped  -- legacy import-dump path. If runtime-dumped hashes are
             available (`dump_hash` field), uses those to produce a
             working pack with `<hash>.png` filenames.
  staging -- organises extracted textures with human-readable names.
             Not directly usable as a drop-in texture pack -- the user
             can either re-extract with the current Forge (which
             populates azahar hashes automatically) or run import-dump.

Auto-detection (`mode="auto"`) picks azahar > mapped > staging based
on what's available in the manifest.

Pack folder structure follows the Azahar/Citra convention:
  load/textures/<title_id>/
    tex1_<W>x<H>_<HASH>_<code>_mip0.png   (azahar mode, drop-in)
    <hash>.png                            (mapped mode, drop-in)
    <readable_name>.png                   (staging mode, not drop-in)
    pack.json                             (azahar/mapped: minimal Azahar
                                           config pinning use_new_hash=false)
    forge_pack_meta.json                  (Forge's own audit metadata --
                                           mappings, counts, mode declaration)

The Azahar `pack.json` is deliberately minimal: it carries only name/author/
description and `use_new_hash: false`. Forge's verbose metadata lives in
`forge_pack_meta.json` so it never gets parsed as Azahar's pack config (a
large pack.json can crash Azahar, and the wrong schema could flip it to the
new hash that Forge's legacy-hash filenames don't match).

Optional `upscaled_dir` parameter: if provided, the pack ships PNGs
from that directory instead of the originals -- handy for shipping a
pack of upscaled (e.g. ESRGAN-processed) textures while reusing the
hash mapping the extraction already produced.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from typing import Any, Dict, List, Optional, Tuple

from tex_forge.textures.azahar_hash import (
    azahar_filename,
    is_available as cityhash_available,
    is_supported_format,
)

logger = logging.getLogger(__name__)


def build_pack(
    output_dir: str,
    title_id: str,
    manifest_textures: List[Dict[str, Any]],
    mode: str = "auto",
    upscaled_dir: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Build a texture pack folder.

    Args:
        output_dir: project output directory (contains textures/ and manifest.json)
        title_id: 16-char hex title ID
        manifest_textures: texture records from manifest.json
        mode: "auto" (default), "azahar", "mapped", or "staging".
        upscaled_dir: optional directory of upscaled PNGs to ship in
            place of the originals.

    Returns (pack_dir, pack_meta).
    """
    if mode == "auto":
        mode = _autodetect_mode(manifest_textures)

    pack_dir = os.path.join(output_dir, "load_pack", "load", "textures", title_id)
    os.makedirs(pack_dir, exist_ok=True)

    pack_meta: Dict[str, Any] = {
        "schema_version": 2,
        "title_id": title_id,
        "pack_mode": mode,
        "texture_count": 0,
        "mapped_count": 0,
        "unmapped_count": 0,
        "format_unsupported_count": 0,
        "hash_collision_count": 0,
        "missing_upscaled_count": 0,
        "upscaled_dir": upscaled_dir or "",
        "warning": None,
        "mappings": {},
    }

    proj_real = os.path.realpath(output_dir)
    upscaled_real = os.path.realpath(upscaled_dir) if upscaled_dir else None

    # Collision tracker: dest filename -> source tex_id that won
    seen_dest: Dict[str, str] = {}

    mapped = 0
    unmapped = 0
    copied = 0

    for tex in manifest_textures:
        png_rel = tex.get("decoded_png_path", "")
        if not png_rel:
            continue

        png_abs = png_rel if os.path.isabs(png_rel) else os.path.join(output_dir, png_rel)
        if not os.path.isfile(png_abs):
            continue

        # Audit F048 -- defend against a tampered manifest pointing at a path
        # outside output_dir. Resolve symlinks, then verify the source PNG lies
        # under the project's realpath. Fail loud (IOError) rather than silently
        # skip: a tampered manifest is a security event the user must see.
        _png_real = os.path.realpath(png_abs)
        if os.path.commonpath([proj_real, _png_real]) != proj_real:
            raise IOError(
                f"pack_builder: manifest texture {tex.get('id', '<no-id>')!r} "
                f"decoded_png_path resolves to {_png_real!r}, which is outside "
                f"the project directory {proj_real!r}. Refusing to copy."
            )

        # Decide which source PNG actually gets copied. If upscaled_dir
        # was provided, look for a same-relative-path file there first;
        # fall back to a filename-only search; otherwise mark missing
        # and fall through to the original.
        src_png = png_abs
        if upscaled_real is not None:
            up_match = _resolve_upscaled(png_rel, upscaled_real)
            if up_match is None:
                pack_meta["missing_upscaled_count"] += 1
                logger.debug("No upscaled match for %s", png_rel)
            else:
                # Same F048 audit applies to the upscaled tree.
                _up_real = os.path.realpath(up_match)
                if os.path.commonpath([upscaled_real, _up_real]) != upscaled_real:
                    raise IOError(
                        f"pack_builder: upscaled candidate {_up_real!r} resolves "
                        f"outside upscaled_dir {upscaled_real!r}. Refusing to copy."
                    )
                src_png = up_match

        tex_id = tex.get("id", f"tex_{unmapped + mapped:04d}")
        dump_hash = tex.get("dump_hash", "")
        azahar_hash = tex.get("azahar_hash_cityhash64", "")
        fmt = tex.get("detected_format", "")
        w = tex.get("width", 0)
        h = tex.get("height", 0)

        dest_name: Optional[str] = None
        mapping_extras: Dict[str, Any] = {}

        if mode == "azahar":
            if not azahar_hash:
                # Record exists but has no offline hash. Skip rather than
                # silently fall through to a different filename scheme.
                continue
            if not is_supported_format(fmt):
                pack_meta["format_unsupported_count"] += 1
                logger.debug("Unsupported format %r for %s", fmt, tex_id)
                continue
            try:
                hash_int = int(azahar_hash, 16)
            except ValueError:
                logger.warning("Bad azahar_hash_cityhash64 %r on %s", azahar_hash, tex_id)
                continue
            dest_name = azahar_filename(w, h, hash_int, fmt)
            if dest_name is None:
                pack_meta["format_unsupported_count"] += 1
                continue
            mapping_extras = {
                "azahar_hash": azahar_hash,
                "format_code": fmt,
            }
        elif mode == "mapped":
            if not dump_hash:
                # No runtime hash for this texture; skip in mapped mode.
                continue
            dest_name = f"{dump_hash}.png"
            mapping_extras = {
                "source_id": tex_id,
                "source_file": tex.get("source_file_path", ""),
                "dimensions": f"{w}x{h}",
                "format": fmt or "unknown",
            }
        else:  # staging
            dest_name = _safe_filename(tex_id, tex)
            mapping_extras = {
                "pack_filename": dest_name,
                "source_file": tex.get("source_file_path", ""),
                "dimensions": f"{w}x{h}",
                "format": fmt or "unknown",
                "hash": "UNKNOWN -- needs runtime dump or re-extract with current Forge",
            }

        if dest_name is None:
            continue

        # Collision check -- two source textures mapping to the same
        # filename. First-write-wins.
        prior = seen_dest.get(dest_name)
        if prior is not None:
            pack_meta["hash_collision_count"] += 1
            logger.warning(
                "Pack filename collision on %s: keeping %s, skipping %s",
                dest_name, prior, tex_id,
            )
            continue

        dest_path = os.path.join(pack_dir, dest_name)
        try:
            shutil.copy2(src_png, dest_path)
        except Exception as e:
            logger.warning("Failed to copy %s -> %s: %s", src_png, dest_path, e)
            continue

        seen_dest[dest_name] = tex_id
        copied += 1
        if mode in ("azahar", "mapped"):
            mapped += 1
            key = azahar_hash if mode == "azahar" else dump_hash
            pack_meta["mappings"][key] = mapping_extras
        else:
            unmapped += 1
            pack_meta["mappings"][tex_id] = mapping_extras

    pack_meta["texture_count"] = copied
    pack_meta["mapped_count"] = mapped
    pack_meta["unmapped_count"] = unmapped

    if mode == "azahar":
        if not cityhash_available():
            pack_meta["warning"] = (
                "Azahar pack built, but no CityHash64 backend was available "
                "at runtime. Check that tex_forge.textures._cityhash_pure is "
                "importable, or `pip install cityhash` for the native module."
            )
    elif mode == "mapped":
        pack_meta["warning"] = None
    else:
        pack_meta["warning"] = (
            "STAGING PACK: This pack does NOT contain runtime texture hashes "
            "and is not a drop-in for Azahar/Citra. Re-extract the ROM with "
            "current Forge to produce a drop-in pack -- no emulator dump "
            "needed. Alternatively, run the emulator's texture dumper and "
            "use 'import-dump' followed by build-pack with mode=mapped."
        )

    # Forge's own audit metadata goes in forge_pack_meta.json -- NOT pack.json.
    # Azahar reads pack.json from the load folder as its texture-pack config;
    # a file there with Forge's schema (and a large per-texture mappings dict)
    # would either flip Azahar to the new hash (which our legacy CityHash64
    # filenames don't match) or, if big enough, crash it (azahar issue #1512).
    forge_meta_path = os.path.join(pack_dir, "forge_pack_meta.json")
    with open(forge_meta_path, "w", encoding="utf-8") as f:
        json.dump(pack_meta, f, indent=2)

    # For genuine drop-in packs, write a minimal Azahar-schema pack.json that
    # pins the legacy hash. This is tiny (no mappings dict) so it can't trip
    # the large-pack.json crash, and it's explicit: Forge stores the OLD
    # (CityHash64-over-upload-data) hash in every filename. If Azahar somehow
    # failed to parse it, it would fall back to "legacy defaults" -- also the
    # old hash -- so every outcome resolves to the hash our filenames use.
    if mode in ("azahar", "mapped"):
        azahar_config = {
            "name": f"3DS Texture Forge pack {title_id}",
            "author": "3DS Texture Forge",
            "description": (
                "Extracted with 3DS Texture Forge. Uses the legacy (old) "
                "texture hash; do not enable use_new_hash for this pack."
            ),
            "use_new_hash": False,
        }
        with open(os.path.join(pack_dir, "pack.json"), "w", encoding="utf-8") as f:
            json.dump(azahar_config, f, indent=2)
        pack_meta["azahar_pack_json"] = True

    logger.info(
        "Pack built: %s\n  mode=%s, total=%d, mapped=%d, unmapped=%d, "
        "format_unsupported=%d, collisions=%d, missing_upscaled=%d",
        pack_dir, mode, copied, mapped, unmapped,
        pack_meta["format_unsupported_count"],
        pack_meta["hash_collision_count"],
        pack_meta["missing_upscaled_count"],
    )
    return pack_dir, pack_meta


def _autodetect_mode(textures: List[Dict[str, Any]]) -> str:
    """Pick the best available mode given what the manifest carries."""
    has_azahar = any(t.get("azahar_hash_cityhash64") for t in textures)
    if has_azahar and cityhash_available():
        return "azahar"
    if any(t.get("dump_hash") for t in textures):
        return "mapped"
    return "staging"


def _resolve_upscaled(png_rel: str, upscaled_real: str) -> Optional[str]:
    """Look up a counterpart for `png_rel` (a path relative to the
    project's textures tree) inside the upscaled directory. Tries the
    same relative path first, then a filename-only search."""
    if not png_rel:
        return None
    rel_norm = png_rel.replace("\\", "/").lstrip("./")
    candidate = os.path.join(upscaled_real, rel_norm)
    if os.path.isfile(candidate):
        return candidate

    # Fallback: filename-only search. Walk once -- packs are small.
    target = os.path.basename(rel_norm)
    for root, _, files in os.walk(upscaled_real):
        if target in files:
            return os.path.join(root, target)
    return None


def _safe_filename(tex_id: str, tex: Dict[str, Any]) -> str:
    """Generate a filesystem-safe filename for staging mode."""
    w = tex.get("width", 0)
    h = tex.get("height", 0)
    fmt = tex.get("detected_format", "UNK")
    src = tex.get("source_file_path", "")
    base = os.path.splitext(os.path.basename(src))[0] if src else tex_id
    base = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in base)
    return f"{base}_{w}x{h}_{fmt}.png"
