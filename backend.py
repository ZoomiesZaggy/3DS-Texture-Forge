"""
Thin backend wrapper for 3DS Texture Forge GUI.

Provides clean functions that GUI worker threads call.
Does NOT import PySide6 or any GUI code.
All exceptions are caught internally — returns structured dicts.
"""

import glob
import logging
import os
import time
import traceback
from types import SimpleNamespace
from typing import Callable, Dict, Any, List, Optional

from main import parse_rom, cmd_extract, EncryptedROMError, ROMParseError
from parsers.romfs import RomFSParser

logger = logging.getLogger(__name__)


def scan_rom(filepath: str) -> Dict[str, Any]:
    """
    Load a ROM file, parse headers, return metadata.
    Returns a result dict; never raises.
    """
    result = {
        "success": False,
        "title_id": "",
        "product_code": "",
        "file_count": 0,
        "romfs_files_preview": [],
        "error_message": "",
        "is_encrypted": False,
    }

    try:
        romfs_data, title_id, product_code, chain = parse_rom(filepath)
        romfs = RomFSParser(romfs_data)
        files = romfs.list_files()

        result["success"] = True
        result["title_id"] = title_id
        result["product_code"] = product_code
        result["file_count"] = len(files)
        result["chain"] = chain

        # Preview: first 20 file paths
        result["romfs_files_preview"] = [p for p, _, _ in files[:20]]

    except EncryptedROMError as e:
        result["is_encrypted"] = True
        result["error_message"] = str(e)
    except ROMParseError as e:
        result["error_message"] = str(e)
    except Exception as e:
        result["error_message"] = f"Unexpected error: {e}"
        logger.debug(traceback.format_exc())

    return result


def run_extraction(
    filepath: str,
    output_dir: str,
    options: Dict[str, Any],
    progress_callback: Optional[Callable] = None,
) -> Dict[str, Any]:
    """
    Run the full extraction pipeline: load -> extract -> manifest.
    Returns a result dict; never raises.

    options keys: scan_all, dump_raw, verbose
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
    }

    t0 = time.time()

    try:
        os.makedirs(output_dir, exist_ok=True)

        # Build a namespace that looks like argparse output
        args = SimpleNamespace(
            input=filepath,
            output=output_dir,
            scan_all=options.get("scan_all", False),
            dump_raw=options.get("dump_raw", False),
            verbose=options.get("verbose", False),
            quiet=False,
            list_files=False,
        )

        summary, records, failures = cmd_extract(args, progress_callback=progress_callback)

        result["success"] = True
        result["summary"] = summary
        result["record_count"] = len(records)
        result["failure_count"] = len(failures)

    except EncryptedROMError as e:
        result["is_encrypted"] = True
        result["error_message"] = str(e)
    except ROMParseError as e:
        result["error_message"] = str(e)
    except Exception as e:
        result["error_message"] = f"Extraction failed: {e}"
        logger.debug(traceback.format_exc())

    result["elapsed"] = round(time.time() - t0, 1)
    return result


def get_output_previews(output_dir: str, max_count: int = 12) -> List[str]:
    """
    Find the first N extracted PNGs in the output directory.
    Returns list of absolute paths.
    """
    try:
        textures_dir = os.path.join(output_dir, "textures")
        if not os.path.isdir(textures_dir):
            textures_dir = output_dir

        png_files = []
        for root, dirs, files in os.walk(textures_dir):
            for f in sorted(files):
                if f.lower().endswith(".png"):
                    png_files.append(os.path.join(root, f))
                    if len(png_files) >= max_count:
                        return png_files
        return png_files
    except Exception:
        return []
