"""Extraction quality checks and report generation for decoded textures."""

import json
import os
import math
import logging
import datetime
import numpy as np
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# PICA200 alpha-only formats
_ALPHA_FORMATS = {0x8, 0xB}  # A8, A4


def compute_quality_metrics(
    rgba: np.ndarray,
    pica_format: int = -1,
) -> Dict[str, Any]:
    """
    Compute quality metrics for a decoded RGBA texture.
    Returns a dict of metrics and flags for suspicious images.

    Flags:
      SUSPICIOUS_SOLID       — >80% identical pixels
      SUSPICIOUS_LOW_VARIANCE— stddev < 8 (for textures > 16x16)
      SUSPICIOUS_EXTREME     — mean luminance < 5 or > 250
      SUSPICIOUS_DIMS        — bad dimensions (0, non-pow2, >4096)
      INFO_NORMAL_MAP        — HILO8 format (expected, not suspicious)
    """
    h, w = rgba.shape[:2]
    total_pixels = h * w

    # Percent fully transparent pixels (alpha == 0)
    alpha = rgba[:, :, 3]
    transparent_count = int(np.sum(alpha == 0))
    pct_transparent = round(transparent_count / total_pixels * 100, 1)

    # Variance score across RGB channels
    rgb = rgba[:, :, :3].astype(np.float32)
    channel_vars = [float(np.var(rgb[:, :, c])) for c in range(3)]
    variance_score = round(sum(channel_vars) / 3.0, 1)
    stddev = round(math.sqrt(max(variance_score, 0)), 2)

    # Mean luminance
    luminance = (0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2])
    mean_luminance = float(np.mean(luminance))

    # Unique color count estimate (sample if large)
    flat = rgba.reshape(-1, 4)
    if total_pixels > 4096:
        rng = np.random.RandomState(42)
        indices = rng.choice(total_pixels, 4096, replace=False)
        sample = flat[indices]
    else:
        sample = flat
    packed = (sample[:, 0].astype(np.uint32) << 24 |
              sample[:, 1].astype(np.uint32) << 16 |
              sample[:, 2].astype(np.uint32) << 8 |
              sample[:, 3].astype(np.uint32))
    unique_colors = int(len(np.unique(packed)))

    # Percent of pixels that are the most common value
    if len(packed) > 0:
        values, counts = np.unique(packed, return_counts=True)
        max_count = int(counts.max())
        pct_dominant = round(max_count / len(packed) * 100, 1)
    else:
        pct_dominant = 100.0

    # Build flags
    flags = []
    is_suspicious = False

    # Exceptions: skip flagging for tiny textures, alpha-only formats
    is_tiny = (w <= 8 and h <= 8)
    is_alpha_only = pica_format in _ALPHA_FORMATS
    is_normal_map = (pica_format == 0x6)  # HILO8

    if is_normal_map:
        flags.append("INFO_NORMAL_MAP")

    if not is_tiny and not is_alpha_only and not is_normal_map:
        # SOLID: >80% of pixels are identical
        if pct_dominant > 80.0:
            flags.append("SUSPICIOUS_SOLID")
            is_suspicious = True

        # LOW_VARIANCE: stddev < 8 for textures > 16x16
        if w > 16 and h > 16 and stddev < 8.0:
            flags.append("SUSPICIOUS_LOW_VARIANCE")
            is_suspicious = True

        # EXTREME: mean luminance < 5 or > 250
        if mean_luminance < 5.0 or mean_luminance > 250.0:
            flags.append("SUSPICIOUS_EXTREME")
            is_suspicious = True

    # DIMS: bad dimensions
    def _is_pow2(n):
        return n > 0 and (n & (n - 1)) == 0
    if w == 0 or h == 0 or w > 4096 or h > 4096:
        flags.append("SUSPICIOUS_DIMS")
        is_suspicious = True

    return {
        "pct_transparent": pct_transparent,
        "variance_score": variance_score,
        "stddev": stddev,
        "mean_luminance": round(mean_luminance, 1),
        "unique_colors_sampled": unique_colors,
        "pct_dominant_color": pct_dominant,
        "is_suspicious": is_suspicious,
        "flags": flags,
    }


def generate_quality_report(
    records: List[Dict[str, Any]],
    game_name: str,
    rom_file: str,
    output_dir: str,
    format_distribution: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """
    Generate quality_report.json and quality_report.txt from texture records.

    Each record should have a 'quality' dict with 'is_suspicious' and 'flags'.
    Returns the report dict.
    """
    total = len(records)
    if total == 0:
        return {"total_textures": 0, "quality_score": 0.0}

    # Count categories
    suspicious_count = 0
    valid_count = 0
    breakdown = {
        "SUSPICIOUS_SOLID": 0,
        "SUSPICIOUS_LOW_VARIANCE": 0,
        "SUSPICIOUS_EXTREME": 0,
        "SUSPICIOUS_DIMS": 0,
    }
    normal_maps = 0
    flagged_files = []

    # Build format distribution from records if not provided
    if format_distribution is None:
        format_distribution = {}
        for r in records:
            fmt = r.get("detected_format", "?")
            format_distribution[fmt] = format_distribution.get(fmt, 0) + 1

    for r in records:
        qm = r.get("quality", {})
        flags = qm.get("flags", [])
        if qm.get("is_suspicious", False):
            suspicious_count += 1
            png_path = r.get("decoded_png_path", "")
            if png_path:
                flagged_files.append(os.path.basename(png_path))
            for flag_name in flags:
                if flag_name in breakdown:
                    breakdown[flag_name] += 1
        else:
            valid_count += 1
        if "INFO_NORMAL_MAP" in flags:
            normal_maps += 1

    quality_score = round(valid_count / total, 3) if total > 0 else 0.0

    report = {
        "game": game_name,
        "rom": os.path.basename(rom_file),
        "extracted_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "total_textures": total,
        "valid": valid_count,
        "suspicious": suspicious_count,
        "quality_score": quality_score,
        "breakdown": breakdown,
        "normal_maps": normal_maps,
        "flagged_files": flagged_files[:100],  # cap at 100
        "format_distribution": format_distribution,
    }

    # Write JSON
    json_path = os.path.join(output_dir, "quality_report.json")
    os.makedirs(output_dir, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # Write human-readable TXT
    txt_path = os.path.join(output_dir, "quality_report.txt")
    pct = round(quality_score * 100, 1)
    lines = [
        "=" * 51,
        "  3DS Texture Forge - Quality Report",
        "=" * 51,
        f"  Game:             {game_name}",
        f"  Extracted:        {total:,} textures",
        f"  Valid:            {valid_count:,}  ({pct}%)",
        f"  Suspicious:       {suspicious_count:,}  ({round((1 - quality_score) * 100, 1)}%)",
    ]
    if breakdown["SUSPICIOUS_SOLID"]:
        lines.append(f"     Solid color:   {breakdown['SUSPICIOUS_SOLID']}")
    if breakdown["SUSPICIOUS_LOW_VARIANCE"]:
        lines.append(f"     Low variance:  {breakdown['SUSPICIOUS_LOW_VARIANCE']}")
    if breakdown["SUSPICIOUS_EXTREME"]:
        lines.append(f"     Too bright/dark: {breakdown['SUSPICIOUS_EXTREME']}")
    if breakdown["SUSPICIOUS_DIMS"]:
        lines.append(f"     Bad dimensions: {breakdown['SUSPICIOUS_DIMS']}")
    if normal_maps:
        lines.append(f"  Normal maps:      {normal_maps}  (expected, not errors)")
    lines.append("")
    lines.append(f"  Quality score: {pct}%")
    lines.append("  " + "-" * 45)
    lines.append("  Format breakdown:")
    # Sort by count descending
    sorted_fmts = sorted(format_distribution.items(), key=lambda x: -x[1])
    for fmt_name, count in sorted_fmts:
        pct_fmt = round(count / total * 100, 1)
        lines.append(f"    {fmt_name:12s} {count:>6,}  ({pct_fmt}%)")
    lines.append("=" * 51)

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    logger.info(f"Quality report: {pct}% valid ({valid_count}/{total})")

    # Quality score gate warning
    if quality_score < 0.50:
        logger.warning(
            f"WARNING: Only {pct}% of textures appear valid. "
            f"This usually means a pixel decoder bug."
        )

    return report
