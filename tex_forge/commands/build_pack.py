"""`tex-forge build-pack PROJECT_DIR` -- build an Azahar/Citra texture pack.

Three modes:
  azahar  -- the manifest carries `azahar_hash_cityhash64` for each
             texture (CityHash64 of the raw GPU bytes, computed
             offline at extract time). Drop-in pack with
             `tex1_<W>x<H>_<HASH>_<code>.png` filenames; no emulator
             dump needed.
  mapped  -- legacy import-dump path: if the manifest has dump_hash
             entries (added by import-dump), emit one <hash>.png per
             known hash.
  staging -- organises extracted PNGs with human-readable names. Not
             a drop-in pack on its own.

Mode selection is automatic by default: azahar > mapped > staging,
based on what the manifest carries. Override with --mode.

Output goes to PROJECT_DIR/load_pack/load/textures/<title_id>/.
"""

from __future__ import annotations

import argparse
import json
import os

from tex_forge.commands._common import setup
from tex_forge.output.pack_builder import build_pack
from tex_forge.textures.azahar_hash import is_available as cityhash_available


def add_subparser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("build-pack", help="Build Azahar/Citra texture pack")
    p.add_argument("project_dir", help="Extraction output directory")
    p.add_argument(
        "--mode",
        choices=("auto", "azahar", "mapped", "staging"),
        default="auto",
        help="Pack mode (default: auto-detect based on manifest contents).",
    )
    p.add_argument(
        "--upscaled",
        metavar="DIR",
        default=None,
        help="Optional directory of upscaled PNGs to ship in place of the originals. "
             "Files are matched by relative path under the textures/ tree, "
             "with a filename-only fallback.",
    )
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--quiet",   action="store_true")
    p.set_defaults(_handler=_run)


def _run(args: argparse.Namespace) -> int:
    setup(args.verbose, args.quiet)
    project_dir = args.project_dir

    manifest_path = os.path.join(project_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        print(f"No manifest.json in {project_dir}")
        return 1

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    title_id = manifest.get("title_id", "0000000000000000")
    textures = manifest.get("textures", [])

    pack_dir, pack_meta = build_pack(
        project_dir, title_id, textures,
        mode=args.mode, upscaled_dir=args.upscaled,
    )

    mode = pack_meta.get("pack_mode", args.mode)

    print()
    print(f"Pack built: {pack_dir}")
    print(f"Mode: {mode}")
    print(f"  textures copied:    {pack_meta['texture_count']}")
    print(f"  mapped (drop-in):   {pack_meta['mapped_count']}")
    print(f"  unmapped (staging): {pack_meta['unmapped_count']}")
    if pack_meta.get("missing_upscaled_count", 0):
        print(f"  missing upscaled:   {pack_meta['missing_upscaled_count']}")
    if pack_meta.get("format_unsupported_count", 0):
        print(f"  unsupported format: {pack_meta['format_unsupported_count']}")
    if pack_meta.get("hash_collision_count", 0):
        print(f"  hash collisions:    {pack_meta['hash_collision_count']}")

    if mode == "staging":
        if cityhash_available():
            print(
                "\nWARNING: This is a STAGING pack. The manifest carries no\n"
                "azahar_hash_cityhash64 fields, which means it was extracted\n"
                "by an older Forge build. Re-extract this ROM with the\n"
                "current Forge to produce a drop-in Azahar pack -- no\n"
                "emulator dump needed."
            )
        else:
            print(
                "\nWARNING: This is a STAGING pack and no CityHash64 backend\n"
                "was available. Install the optional 'cityhash' module\n"
                "(`pip install cityhash`) and re-extract the ROM, or use\n"
                "the bundled pure-Python fallback (no extra installs needed)\n"
                "and re-extract."
            )
    elif mode == "azahar":
        print("\nDrop-in Azahar pack ready. Place `load_pack/load/` into Azahar's user dir.")
    if pack_meta.get("warning"):
        print(f"\n{pack_meta['warning']}")
    return 0
