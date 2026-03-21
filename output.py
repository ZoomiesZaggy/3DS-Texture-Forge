"""
Output layer: strict manifest schema, PNG saving, failures/unknown tracking.

Manifest schema per texture:
  id, source_rom, source_container_chain, source_file_path, source_offset,
  detected_format, width, height, mip_count, raw_data_size, decoded_png_path,
  confidence, parser_used, notes, sha1_rgba, sha1_source_blob, failed_reason
"""

import os
import json
import hashlib
import logging
import numpy as np
from PIL import Image
from typing import List, Dict, Any, Optional
from textures.decoder import get_format_name

logger = logging.getLogger(__name__)


def sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def sha1_rgba(rgba: np.ndarray) -> str:
    return hashlib.sha1(rgba.tobytes()).hexdigest()


def make_alpha_visible(rgba_data: np.ndarray, pica_format: int = -1) -> np.ndarray:
    """For alpha-only or white-luminance+alpha textures, make the alpha channel visible.

    When RGB is constant (all white or all one color) but alpha varies, the texture
    carries its real data in the alpha channel. This converts it so the alpha values
    become visible grayscale in RGB, making textures like the Mario "M" logo or
    shadow maps actually visible in image viewers.

    Only activates when RGB is truly constant — normal RGBA textures are unaffected.
    """
    if rgba_data.ndim != 3 or rgba_data.shape[2] != 4:
        return rgba_data

    alpha = rgba_data[:, :, 3]
    rgb = rgba_data[:, :, :3]

    # Check if RGB is constant (std < 5) but alpha has meaningful variation
    rgb_std = float(np.std(rgb.astype(np.float32)))
    alpha_std = float(np.std(alpha.astype(np.float32)))

    if rgb_std < 5.0 and alpha_std > 10.0:
        # Alpha IS the texture — make it visible as grayscale with alpha preserved
        gray = alpha
        return np.stack([gray, gray, gray, alpha], axis=2)

    return rgba_data


def save_texture_as_png(rgba_data: np.ndarray, output_path: str,
                        pica_format: int = -1) -> bool:
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        # Make alpha/luminance textures visible
        rgba_data = make_alpha_visible(rgba_data, pica_format)
        if rgba_data.shape[2] == 4 and np.all(rgba_data[:, :, 3] == 255):
            img = Image.fromarray(rgba_data[:, :, :3], "RGB")
        else:
            img = Image.fromarray(rgba_data, "RGBA")
        img.save(output_path, "PNG")
        return True
    except Exception as e:
        logger.warning(f"Failed to save PNG {output_path}: {e}")
        return False


def generate_output_filename(index: int, tex_info: Dict[str, Any],
                              source_path: str = "") -> str:
    fmt_name = get_format_name(tex_info.get("format", 0))
    width = tex_info.get("width", 0)
    height = tex_info.get("height", 0)
    name = tex_info.get("name", "")
    if name:
        name = name.replace("\\", "_").replace("/", "_").replace(" ", "_")
        name = "".join(c for c in name if c.isalnum() or c in ("_", "-", "."))
        return f"tex_{index:04d}_{name}_{fmt_name}_{width}x{height}.png"
    return f"tex_{index:04d}_{fmt_name}_{width}x{height}.png"


def build_output_path(output_dir: str, source_path: str, filename: str) -> str:
    if source_path:
        clean = source_path.lstrip("/").replace("\\", "/")
        parts = clean.split("/")
        dir_part = "/".join(parts[:-1]) if len(parts) > 1 else ""
    else:
        dir_part = ""
    if dir_part:
        return os.path.join(output_dir, "textures", dir_part, filename)
    return os.path.join(output_dir, "textures", filename)


def save_raw_data(data: bytes, output_path: str) -> bool:
    try:
        bin_path = output_path.rsplit(".", 1)[0] + ".bin"
        os.makedirs(os.path.dirname(bin_path), exist_ok=True)
        with open(bin_path, "wb") as f:
            f.write(data)
        return True
    except Exception as e:
        logger.warning(f"Failed to save raw data: {e}")
        return False


# --- Strict manifest schema ---

def make_texture_record(
    tex_id: str,
    source_rom: str,
    source_container_chain: str,
    source_file_path: str,
    source_offset: int,
    detected_format: str,
    width: int,
    height: int,
    mip_count: int,
    raw_data_size: int,
    decoded_png_path: str,
    confidence: str,
    parser_used: str,
    notes: str,
    sha1_rgba_val: str,
    sha1_source_val: str,
    quality_metrics: Optional[Dict] = None,
    failed_reason: str = "",
) -> Dict[str, Any]:
    rec = {
        "id": tex_id,
        "source_rom": source_rom,
        "source_container_chain": source_container_chain,
        "source_file_path": source_file_path,
        "source_offset": source_offset,
        "detected_format": detected_format,
        "width": width,
        "height": height,
        "mip_count": mip_count,
        "raw_data_size": raw_data_size,
        "decoded_png_path": decoded_png_path,
        "confidence": confidence,
        "parser_used": parser_used,
        "notes": notes,
        "sha1_rgba": sha1_rgba_val,
        "sha1_source_blob": sha1_source_val,
        "failed_reason": failed_reason,
    }
    if quality_metrics:
        rec["quality"] = quality_metrics
    return rec


def write_manifest(output_dir: str, records: List[Dict[str, Any]],
                   rom_file: str, title_id: str, game_title: str):
    manifest = {
        "schema_version": 2,
        "game_title": game_title,
        "title_id": title_id,
        "rom_file": os.path.basename(rom_file),
        "texture_count": len(records),
        "textures": records,
    }
    path = os.path.join(output_dir, "manifest.json")
    os.makedirs(output_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    logger.info(f"Wrote manifest.json ({len(records)} textures)")


def write_failures(output_dir: str, failures: List[Dict[str, Any]]):
    path = os.path.join(output_dir, "failures.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"count": len(failures), "failures": failures}, f, indent=2)
    logger.info(f"Wrote failures.json ({len(failures)} entries)")


def write_unknown_files(output_dir: str, unknowns: List[Dict[str, Any]]):
    path = os.path.join(output_dir, "unknown_files.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"count": len(unknowns), "files": unknowns}, f, indent=2)
    logger.info(f"Wrote unknown_files.json ({len(unknowns)} entries)")


def write_summary(output_dir: str, summary: Dict[str, Any]):
    path = os.path.join(output_dir, "summary.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    logger.info(f"Wrote summary.json")


# Legacy compat
def generate_manifest(output_dir, rom_file, title_id, game_title, textures):
    records = []
    for tex in textures:
        records.append({
            "id": f"tex_{tex.get('index', 0):04d}",
            "source_file_path": tex.get("source_file", ""),
            "detected_format": get_format_name(tex.get("format", 0)),
            "width": tex.get("width", 0),
            "height": tex.get("height", 0),
            "decoded_png_path": tex.get("output_file", ""),
        })
    write_manifest(output_dir, records, rom_file, title_id, game_title)
