"""PNG saving with alpha-visibility heuristic.

When a texture's RGB is constant (all white or all one colour) but its alpha
channel varies, the *real image* lives in alpha. Naively saving as RGBA
makes the PNG look like a solid blob in most viewers. We detect this case
and remap alpha into the RGB channels so the texture is visually inspectable.

Examples:
  - Mario "M" logo: white RGB, alpha holds the M shape.
  - Shadow maps:    white RGB, alpha is the shadow.
  - Font glyphs:    white RGB, alpha is the glyph silhouette.

The heuristic is conservative: only triggers when std(rgb) < 5 AND std(alpha) > 10.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


def _alpha_visibility(rgba: np.ndarray) -> np.ndarray:
    """If RGB is constant but alpha varies, project alpha into RGB.

    Leaves normal RGBA images untouched.
    """
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        return rgba
    alpha = rgba[:, :, 3]
    rgb = rgba[:, :, :3]
    if float(np.std(rgb.astype(np.float32))) < 5.0 and float(np.std(alpha.astype(np.float32))) > 10.0:
        gray = alpha
        return np.stack([gray, gray, gray, alpha], axis=2)
    return rgba


def save_png(rgba: np.ndarray, path: str, *, alpha_aware: bool = True) -> bool:
    """Save *rgba* (H, W, 4) uint8 as PNG. Returns True on success.

    With alpha_aware=True (default), applies the alpha-visibility heuristic.
    Set False for write-exact-pixel use cases (the Azahar pack builder).
    """
    try:
        from PIL import Image
    except ImportError:
        logger.error("Pillow not installed -- can't save PNGs")
        return False

    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if alpha_aware:
            rgba = _alpha_visibility(rgba)

        # Drop the alpha channel for fully-opaque images -- saves bytes and
        # makes thumbnails open without an alpha plane.
        if rgba.shape[2] == 4 and bool(np.all(rgba[:, :, 3] == 255)):
            Image.fromarray(rgba[:, :, :3], "RGB").save(path, "PNG")
        else:
            Image.fromarray(rgba, "RGBA").save(path, "PNG")
        return True
    except Exception as e:
        logger.warning("Failed to save PNG %s: %s", path, e)
        return False
