"""
Conservative custom-texture pack builder for Azahar/Citra.

IMPORTANT: This builder does NOT compute runtime texture hashes from static ROM data.
Azahar/Citra hash textures at GPU upload time, which depends on draw-call state that
cannot be derived from ROM files alone.

Two modes:
  a) "staging" - organizes extracted textures with human-readable names.
     NOT directly usable as a drop-in texture pack without hash mapping.
  b) "mapped" - if runtime-dumped hashes are available (via import-dump),
     uses those to produce a working pack folder.

Pack folder structure follows the Citra/Azahar convention:
  load/textures/<title_id>/
    <hash>.png          (mapped mode, one per known hash)
    pack.json           (metadata, mappings, mode declaration)
"""

import os
import json
import shutil
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


def build_pack(
    output_dir: str,
    title_id: str,
    manifest_textures: List[Dict[str, Any]],
    mode: str = "staging",
) -> str:
    """
    Build a texture pack folder.

    Args:
        output_dir: project output directory (contains textures/ and manifest.json)
        title_id: 16-char hex title ID
        manifest_textures: texture records from manifest.json
        mode: "staging" or "mapped"

    Returns path to the pack folder.
    """
    pack_dir = os.path.join(output_dir, "load_pack", "load", "textures", title_id)
    os.makedirs(pack_dir, exist_ok=True)

    pack_meta = {
        "schema_version": 1,
        "title_id": title_id,
        "pack_mode": mode,
        "texture_count": 0,
        "mapped_count": 0,
        "unmapped_count": 0,
        "warning": None,
        "mappings": {},
    }

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

        tex_id = tex.get("id", f"tex_{unmapped + mapped:04d}")
        dump_hash = tex.get("dump_hash", "")

        if dump_hash and mode == "mapped":
            # We have a real runtime hash from an emulator dump
            dest_name = f"{dump_hash}.png"
            dest_path = os.path.join(pack_dir, dest_name)
            try:
                shutil.copy2(png_abs, dest_path)
                pack_meta["mappings"][dump_hash] = {
                    "source_id": tex_id,
                    "source_file": tex.get("source_file_path", ""),
                    "dimensions": f"{tex.get('width', '?')}x{tex.get('height', '?')}",
                    "format": tex.get("detected_format", "unknown"),
                }
                mapped += 1
                copied += 1
            except Exception as e:
                logger.warning(f"Failed to copy {png_abs} -> {dest_path}: {e}")
        else:
            # Staging mode: copy with readable name, record as unmapped
            safe_name = _safe_filename(tex_id, tex)
            dest_path = os.path.join(pack_dir, safe_name)
            try:
                shutil.copy2(png_abs, dest_path)
                pack_meta["mappings"][tex_id] = {
                    "pack_filename": safe_name,
                    "source_file": tex.get("source_file_path", ""),
                    "dimensions": f"{tex.get('width', '?')}x{tex.get('height', '?')}",
                    "format": tex.get("detected_format", "unknown"),
                    "hash": "UNKNOWN - needs runtime dump",
                }
                unmapped += 1
                copied += 1
            except Exception as e:
                logger.warning(f"Failed to copy {png_abs} -> {dest_path}: {e}")

    pack_meta["texture_count"] = copied
    pack_meta["mapped_count"] = mapped
    pack_meta["unmapped_count"] = unmapped

    if mode == "staging" or unmapped > 0:
        pack_meta["warning"] = (
            "STAGING PACK: This pack does NOT contain runtime texture hashes. "
            "It cannot be used as a direct drop-in for Azahar/Citra custom textures. "
            "To make it usable, run the emulator's texture dumper, then use "
            "'import-dump' to merge real hashes and rebuild with mode=mapped."
        )
    elif mapped > 0 and unmapped == 0:
        pack_meta["warning"] = None  # Fully mapped pack

    pack_json_path = os.path.join(pack_dir, "pack.json")
    with open(pack_json_path, "w", encoding="utf-8") as f:
        json.dump(pack_meta, f, indent=2)

    logger.info(
        f"Pack built: {pack_dir}\n"
        f"  mode={mode}, total={copied}, mapped={mapped}, unmapped={unmapped}"
    )
    return pack_dir


def _safe_filename(tex_id: str, tex: Dict[str, Any]) -> str:
    """Generate a filesystem-safe filename for staging mode."""
    w = tex.get("width", 0)
    h = tex.get("height", 0)
    fmt = tex.get("detected_format", "UNK")
    src = tex.get("source_file_path", "")
    base = os.path.splitext(os.path.basename(src))[0] if src else tex_id
    base = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in base)
    return f"{base}_{w}x{h}_{fmt}.png"
