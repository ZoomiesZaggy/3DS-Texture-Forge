"""Strict manifest schema -- one record per texture.

The manifest is consumed by:
  - report subcommand    -> render breakdowns / quality summary
  - build-pack subcommand -> produce Azahar/Citra texture packs
  - import-dump subcommand -> match manifest rows to runtime hashes
  - third-party tools  -> any consumer that reads manifest.json

Schema version 2 (matches v1's output.py):
    schema_version: 2
    title_id, game_title, rom_file, texture_count, textures: [TextureRecord]
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Record builder (mirrors v1's make_texture_record signature exactly)
# ─────────────────────────────────────────────────────────────────────────────

def make_record(
    *,
    tex_id: str,
    source_rom: str = "",
    source_container_chain: str = "",
    source_file_path: str = "",
    source_offset: int = 0,
    detected_format: str = "",
    width: int = 0,
    height: int = 0,
    mip_count: int = 1,
    raw_data_size: int = 0,
    decoded_png_path: str = "",
    confidence: str = "high",
    parser_used: str = "",
    notes: str = "",
    sha1_rgba: str = "",
    sha1_source_blob: str = "",
    quality: Optional[Dict[str, Any]] = None,
    failed_reason: str = "",
    content_hash: str = "",
    raw_data_hash_xxh64: str = "",
    azahar_hash_cityhash64: str = "",
    duplicate_of: str = "",
    source_content: str = "",
    raw_dump_path: str = "",
) -> Dict[str, Any]:
    rec: Dict[str, Any] = {
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
        "sha1_rgba": sha1_rgba,
        "sha1_source_blob": sha1_source_blob,
        "failed_reason": failed_reason,
    }
    if content_hash:
        rec["content_hash"] = content_hash
    if raw_data_hash_xxh64:
        rec["raw_data_hash_xxh64"] = raw_data_hash_xxh64
    if azahar_hash_cityhash64:
        rec["azahar_hash_cityhash64"] = azahar_hash_cityhash64
    if duplicate_of:
        rec["duplicate_of"] = duplicate_of
    if source_content:
        rec["source_content"] = source_content
    if raw_dump_path:
        rec["raw_dump_path"] = raw_dump_path
    if quality:
        rec["quality"] = quality
    return rec


# ─────────────────────────────────────────────────────────────────────────────
# Writers
# ─────────────────────────────────────────────────────────────────────────────

def write_manifest(
    output_dir: str,
    records: List[Dict[str, Any]],
    *,
    rom_file: str,
    title_id: str,
    game_title: str,
    summary: Optional[Dict[str, Any]] = None,
    container_chain: str = "",
) -> str:
    payload = {
        "schema_version": 2,
        "title_id": title_id,
        "game_title": game_title,
        "rom_file": os.path.basename(rom_file),
        "container_chain": container_chain,
        "texture_count": len(records),
        "textures": records,
    }
    if summary:
        payload["summary"] = summary

    path = os.path.join(output_dir, "manifest.json")
    os.makedirs(output_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    logger.info("Wrote manifest.json (%d textures)", len(records))
    return path


def write_failures(output_dir: str, failures: List[Dict[str, Any]]) -> str:
    path = os.path.join(output_dir, "failures.json")
    os.makedirs(output_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"count": len(failures), "failures": failures}, f, indent=2)
    return path


def write_unknowns(output_dir: str, unknowns: List[Dict[str, Any]]) -> str:
    path = os.path.join(output_dir, "unknown_files.json")
    os.makedirs(output_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"count": len(unknowns), "files": unknowns}, f, indent=2)
    return path


def write_summary(output_dir: str, summary: Dict[str, Any]) -> str:
    path = os.path.join(output_dir, "summary.json")
    os.makedirs(output_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    return path


# ─────────────────────────────────────────────────────────────────────────────
# SHA-1 helpers (used by record building and dedup integrity audits)
# ─────────────────────────────────────────────────────────────────────────────

def sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def sha1_rgba(rgba) -> str:
    """SHA-1 of a numpy RGBA array's tobytes() representation."""
    return hashlib.sha1(rgba.tobytes()).hexdigest()
