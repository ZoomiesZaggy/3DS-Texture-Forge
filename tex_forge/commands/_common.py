"""Helpers shared between CLI subcommands."""

from __future__ import annotations

import os
import sys
from typing import Tuple

from tex_forge.core.exceptions import EncryptedROMError, ROMParseError
from tex_forge.core.logging import setup_logging


def setup(verbose: bool, quiet: bool) -> None:
    setup_logging(verbose=verbose, quiet=quiet)


def load_rom_or_die(path: str) -> Tuple[bytes, str, str, str]:
    """Wrapper around parse_rom() with friendly error messages."""
    from tex_forge.rom import parse_rom
    try:
        return parse_rom(path)
    except EncryptedROMError as e:
        _print_encrypted_help()
        raise SystemExit(2)
    except ROMParseError as e:
        print(f"ROM parse error: {e}", file=sys.stderr)
        raise SystemExit(1)


def load_all_contents_or_die(path: str):
    """Like load_rom_or_die, but returns *every* RomFS-bearing content.

    For .3ds/.cxi and single-content .cia this is a one-item list identical to
    load_rom_or_die. For multi-content .cia it includes update/DLC contents.
    Returns a list of (romfs_bytes, title_id, product_code, chain).
    """
    from tex_forge.rom.loader import iter_rom_contents
    try:
        contents = list(iter_rom_contents(path))
    except EncryptedROMError:
        _print_encrypted_help()
        raise SystemExit(2)
    except ROMParseError as e:
        print(f"ROM parse error: {e}", file=sys.stderr)
        raise SystemExit(1)
    if not contents:
        print(f"ROM parse error: no readable content in {path}", file=sys.stderr)
        raise SystemExit(1)
    return contents


def _print_encrypted_help() -> None:
    print("\n" + "=" * 56, file=sys.stderr)
    print("  ERROR: Encrypted ROM", file=sys.stderr)
    print("=" * 56, file=sys.stderr)
    print("  This ROM is encrypted and cannot be extracted.", file=sys.stderr)
    print("  Decrypt it first using GodMode9 on your 3DS:", file=sys.stderr)
    print(file=sys.stderr)
    print("    GodMode9 > [A] on game > Manage Title... > Decrypt File", file=sys.stderr)
    print("    or:       NCSD image options... > Decrypt image (0)", file=sys.stderr)
    print(file=sys.stderr)
    print("  Guide: https://3ds.hacks.guide/godmode9-usage.html", file=sys.stderr)
    print("=" * 56 + "\n", file=sys.stderr)
