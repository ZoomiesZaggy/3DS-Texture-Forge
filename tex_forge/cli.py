"""tex-forge CLI entry point.

Subcommands:
  scan         -- inspect ROM contents without extracting
  extract      -- decode textures to PNG
  batch        -- extract every ROM in given files/folders (continue on error)
  verify       -- audit an extraction output dir (manifest vs disk)
  report       -- summarise a previous extraction
  build-pack   -- build an Azahar/Citra custom-texture pack from the project
  import-dump  -- merge emulator-dumped texture hashes into the project manifest
"""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(
        prog="tex-forge",
        description="Extract textures from Nintendo 3DS ROMs.",
    )
    try:
        from importlib.metadata import version as _pkg_version
        _ver = _pkg_version("tex-forge")
    except Exception:
        _ver = "2.0.0"
    top.add_argument("--version", action="version",
                     version=f"%(prog)s {_ver}")
    sub = top.add_subparsers(dest="command", required=True)

    from tex_forge.commands import (
        batch as batch_cmd,
        build_pack as build_pack_cmd,
        extract as extract_cmd,
        import_dump as import_dump_cmd,
        report as report_cmd,
        scan as scan_cmd,
        verify as verify_cmd,
    )

    extract_cmd.add_subparser(sub)
    batch_cmd.add_subparser(sub)
    scan_cmd.add_subparser(sub)
    verify_cmd.add_subparser(sub)
    report_cmd.add_subparser(sub)
    build_pack_cmd.add_subparser(sub)
    import_dump_cmd.add_subparser(sub)
    return top


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "_handler", None)
    if handler is None:
        parser.print_help()
        return 1
    return handler(args) or 0


if __name__ == "__main__":
    sys.exit(main())
