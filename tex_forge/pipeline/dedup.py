"""Two-tier deduplication for the extraction pipeline.

Many 3DS games re-use the same texture across hundreds of inner files
(common HUD icons, font glyphs, particle effects). Writing them all to
disk wastes space; decoding them all wastes CPU.

We dedupe at two levels:

  1. Raw-pixel xxhash64 -- catches identical encoded bytes BEFORE decode.
     If we've already decoded these exact bytes, skip the decode entirely.

  2. Decoded-pixel md5 -- catches the same image encoded differently
     (e.g. RGBA8 vs RGBA4 reductions of the same source).

Both are stored as dicts of hash -> first_tex_id. The dedup pass returns
metadata records for duplicates instead of writing PNGs, so the manifest
still reflects every occurrence -- just without the disk overhead.

xxhash is much faster than md5/sha256 but has a small chance of collision
on adversarial inputs. We use it only for the first-pass byte check.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

try:
    import xxhash as _xxhash
    _HAS_XXHASH = True
except ImportError:
    _HAS_XXHASH = False
    logger.info("xxhash not installed -- raw-byte dedup disabled")


@dataclass(slots=True)
class DedupHit:
    """One side of a duplicate match: tex_id of the first occurrence and its content hash."""

    first_tex_id: str
    content_hash: str


@dataclass(slots=True)
class Deduper:
    """Two-tier dedup tracker. Cheap to call -- both checks are O(1) hashtable lookups."""

    enabled: bool = False
    seen_raw: Dict[str, Tuple[str, str]] = field(default_factory=dict)   # xxhash -> (tex_id, content_hash)
    seen_content: Dict[str, str] = field(default_factory=dict)           # md5    -> tex_id

    # ── pre-decode check (raw pixel bytes) ─────────────────────────────────

    def check_raw(self, raw_pixel_bytes: bytes) -> Optional[DedupHit]:
        """If these raw bytes have been seen, return the previous hit; else None.

        A hit means the caller can skip decoding entirely and write a
        duplicate-of record pointing at the first occurrence.
        """
        if not (self.enabled and _HAS_XXHASH and raw_pixel_bytes):
            return None
        h = _xxhash.xxh64(raw_pixel_bytes).hexdigest().upper()
        prev = self.seen_raw.get(h)
        if prev is None:
            return None
        return DedupHit(first_tex_id=prev[0], content_hash=prev[1])

    def remember_raw(self, raw_pixel_bytes: bytes, tex_id: str, content_hash: str) -> None:
        if not (self.enabled and _HAS_XXHASH and raw_pixel_bytes):
            return
        h = _xxhash.xxh64(raw_pixel_bytes).hexdigest().upper()
        self.seen_raw.setdefault(h, (tex_id, content_hash))

    def raw_hash(self, raw_pixel_bytes: bytes) -> str:
        """Compute the raw-byte xxh64 (or empty string if xxhash missing)."""
        if not (_HAS_XXHASH and raw_pixel_bytes):
            return ""
        return _xxhash.xxh64(raw_pixel_bytes).hexdigest().upper()

    # ── post-decode check (RGBA pixel array) ───────────────────────────────

    def check_content(self, rgba: np.ndarray) -> Tuple[str, Optional[str]]:
        """Compute content_hash for *rgba*; return (hash, prev_tex_id_or_None)."""
        h = hashlib.md5(rgba.tobytes()).hexdigest()
        return h, self.seen_content.get(h)

    def remember_content(self, content_hash: str, tex_id: str) -> None:
        self.seen_content.setdefault(content_hash, tex_id)
