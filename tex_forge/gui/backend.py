"""GUI backend -- thin wrapper around ExtractionPipeline.

Used by the v1 GUI app (vendored under _gui_app_v1.py). The GUI worker
thread imports these functions and forwards results into Qt signals.

Replaces the v1 backend.py which faked argparse output via SimpleNamespace
to call into main.cmd_extract. The new flow goes directly through
ExtractionPipeline -- no argparse round-trip.
"""

from __future__ import annotations

import glob
import logging
import os
import time
import traceback
from typing import Any, Callable, Dict, List, Optional

from tex_forge.core.exceptions import EncryptedROMError, ROMParseError
from tex_forge.metadata.games import get_game_name
from tex_forge.pipeline.extractor import (
    ContentSource,
    ExtractionPipeline,
    ExtractOptions,
)
from tex_forge.pipeline.progress import CallableProgress
from tex_forge.rom.loader import content_label_from_chain, iter_rom_contents
from tex_forge.rom.romfs import RomFSParser

logger = logging.getLogger(__name__)


def scan_rom(filepath: str) -> Dict[str, Any]:
    """Open a ROM and return a metadata-only summary -- never raises.

    For multi-content CIAs the file_count is summed across every RomFS-bearing
    content, `content_count` reports how many there are, and the preview is
    taken from content 0 (the main NCCH).
    """
    result = {
        "success": False,
        "title_id": "",
        "product_code": "",
        "file_count": 0,
        "romfs_files_preview": [],
        "error_message": "",
        "is_encrypted": False,
        "chain": "",
        "content_count": 1,
    }
    try:
        contents = list(iter_rom_contents(filepath))
        total_files = 0
        preview: List[str] = []
        for i, (romfs_data, title_id, product_code, chain) in enumerate(contents):
            files = RomFSParser(romfs_data).list_files()
            total_files += len(files)
            if i == 0:
                result.update(
                    success=True,
                    title_id=title_id,
                    product_code=product_code,
                    chain=chain,
                )
                preview = [p for p, _, _ in files[:20]]
        result.update(
            file_count=total_files,
            content_count=len(contents),
            romfs_files_preview=preview,
        )
    except EncryptedROMError as e:
        result["is_encrypted"] = True
        result["error_message"] = str(e)
    except ROMParseError as e:
        result["error_message"] = str(e)
    except Exception as e:  # pragma: no cover -- defensive
        result["error_message"] = f"Unexpected error: {e}"
        logger.debug(traceback.format_exc())
    return result


def run_extraction(
    filepath: str,
    output_dir: str,
    options: Dict[str, Any],
    progress_callback: Optional[Callable] = None,
    cancel_event=None,
) -> Dict[str, Any]:
    """Run the full extractor and return a structured result dict.

    options keys:
      scan_all (bool), dump_raw (bool), dedup (bool), output_mode (str),
      verbose (bool)

    cancel_event: optional threading.Event. When set, the pipeline stops
    between files, drains its PNG writers, and returns with
    summary["canceled"] = True (partial outputs are still written). This is
    the safe replacement for terminating the worker thread.
    """
    result = {
        "success": False,
        "error_message": "",
        "is_encrypted": False,
        "summary": {},
        "record_count": 0,
        "failure_count": 0,
        "output_dir": output_dir,
        "elapsed": 0.0,
        "content_count": 1,
        "canceled": False,
    }
    t0 = time.time()
    try:
        os.makedirs(output_dir, exist_ok=True)
        contents = list(iter_rom_contents(filepath))
        romfs0, title_id, product_code, chain0 = contents[0]
        multi = len(contents) > 1

        opts = ExtractOptions(
            output_dir=output_dir,
            output_mode=options.get("output_mode", "normal"),
            scan_all=options.get("scan_all", False),
            dedup=options.get("dedup", False),
            dump_raw=options.get("dump_raw", False),
            verbose=options.get("verbose", False),
        )
        progress = CallableProgress(progress_callback) if progress_callback else None
        pipe = ExtractionPipeline(
            romfs_data=romfs0,
            title_id=title_id,
            product_code=product_code,
            chain=chain0,
            rom_path=filepath,
            options=opts,
            progress=progress or _NoOpProgress(),
            content_source=content_label_from_chain(chain0) if multi else "",
            extra_contents=[
                ContentSource(
                    romfs_data=c[0],
                    chain=c[3],
                    source_content=content_label_from_chain(c[3]),
                )
                for c in contents[1:]
            ],
            cancel_event=cancel_event,
        )
        summary = pipe.run()

        result["success"] = True
        result["summary"] = summary
        result["record_count"] = len(pipe.records)
        result["failure_count"] = len(pipe.failures)
        result["content_count"] = len(contents)
        result["canceled"] = bool(summary.get("canceled"))

    except EncryptedROMError as e:
        result["is_encrypted"] = True
        result["error_message"] = str(e)
    except ROMParseError as e:
        result["error_message"] = str(e)
    except Exception as e:  # pragma: no cover
        result["error_message"] = f"Extraction failed: {e}"
        logger.debug(traceback.format_exc())

    result["elapsed"] = round(time.time() - t0, 1)
    return result


def get_rom_icon_rgba(filepath: str):
    """Read-only: decode a title's 48x48 HOME Menu icon to an RGBA8 ndarray.

    Thin pass-through to tex_forge.rom.icon.extract_title_icon, which reuses the
    existing ROM routing and PICA200 decoder (no new swizzle/format code).
    Returns a (48, 48, 4) uint8 ndarray, or None when the icon cannot be read
    (encrypted ExeFS, no icon entry, odd encoding). Never raises; the GUI falls
    back to its placeholder plate.
    """
    try:
        from tex_forge.rom.icon import extract_title_icon
        return extract_title_icon(filepath)
    except Exception as e:  # pragma: no cover -- defensive
        logger.debug("get_rom_icon_rgba failed for %s: %s", filepath, e)
        return None


def get_rom_banner_rgba(filepath: str):
    """Read-only: decode a title's HOME Menu banner image to an RGBA8 ndarray.

    Thin pass-through to tex_forge.rom.banner.extract_title_banner, which
    reuses the existing ROM routing, LZ11 codec, CGFX plugin, and PICA200
    decoder (no new swizzle/format code). Returns an (H, W, 4) uint8 ndarray
    or None (encrypted ExeFS, no banner entry, undecodable model). Never
    raises; the GUI falls back to the SMDH icon, then the placeholder.
    """
    try:
        from tex_forge.rom.banner import extract_title_banner
        return extract_title_banner(filepath)
    except Exception as e:  # pragma: no cover -- defensive
        logger.debug("get_rom_banner_rgba failed for %s: %s", filepath, e)
        return None


def get_output_previews(output_dir: str, max_count: int = 12) -> List[str]:
    """Find the first N PNGs in the output dir for the GUI thumbnail strip."""
    try:
        target = os.path.join(output_dir, "textures") \
            if os.path.isdir(os.path.join(output_dir, "textures")) else output_dir
        out: List[str] = []
        for root, _dirs, files in os.walk(target):
            for f in sorted(files):
                if f.lower().endswith(".png"):
                    out.append(os.path.join(root, f))
                    if len(out) >= max_count:
                        return out
        return out
    except Exception:
        return []


class _NoOpProgress:
    def __call__(self, *args, **kwargs) -> None:
        return
