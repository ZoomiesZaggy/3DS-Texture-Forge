"""Extraction quality checks for decoded textures."""

import numpy as np
from typing import Dict, Any


def compute_quality_metrics(rgba: np.ndarray) -> Dict[str, Any]:
    """
    Compute quality metrics for a decoded RGBA texture.
    Returns a dict of metrics that can be used to flag suspicious images.
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

    # Unique color count estimate (sample if large)
    flat = rgba.reshape(-1, 4)
    if total_pixels > 4096:
        rng = np.random.RandomState(42)
        indices = rng.choice(total_pixels, 4096, replace=False)
        sample = flat[indices]
    else:
        sample = flat
    # Pack RGBA into single u32 for uniqueness
    packed = (sample[:, 0].astype(np.uint32) << 24 |
              sample[:, 1].astype(np.uint32) << 16 |
              sample[:, 2].astype(np.uint32) << 8 |
              sample[:, 3].astype(np.uint32))
    unique_colors = int(len(np.unique(packed)))

    # Flags
    is_blank = variance_score < 1.0 and unique_colors <= 2
    is_solid = unique_colors == 1
    is_mostly_transparent = pct_transparent > 99.0
    is_suspicious = is_blank or is_solid or (variance_score < 5.0 and unique_colors < 4)

    flags = []
    if is_solid:
        flags.append("solid_color")
    if is_blank and not is_solid:
        flags.append("blank")
    if is_mostly_transparent:
        flags.append("mostly_transparent")
    if variance_score < 2.0 and not is_blank and not is_solid:
        flags.append("very_low_variance")
    if is_suspicious and not flags:
        flags.append("suspicious")

    return {
        "pct_transparent": pct_transparent,
        "variance_score": variance_score,
        "unique_colors_sampled": unique_colors,
        "is_suspicious": is_suspicious,
        "flags": flags,
    }
