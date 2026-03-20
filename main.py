"""
3ds-tex-extract: Extract textures from Nintendo 3DS ROMs.

Subcommands:
  scan        - Scan a ROM and report what's inside without extracting.
  extract     - Extract and decode textures to PNG.
  report      - Generate reports from a previous extraction.
  build-pack  - Build an Azahar/Citra custom-texture staging pack.
  import-dump - Import runtime-dumped textures from an emulator.

Backward compat: if no subcommand given and a positional ROM path is provided,
falls back to legacy extract behavior.
"""

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from typing import List, Dict, Any, Optional, Tuple

import numpy as np

from parsers.ncsd import NCSDParser
from parsers.cia import CIAParser
from parsers.ncch import NCCHParser
from parsers.romfs import RomFSParser
from textures.decoder import (
    decode_texture_fast, get_format_name, get_format_bpp,
    calculate_texture_size, FORMAT_NAMES,
)
from textures.scanner import (
    fingerprint_file, extract_textures_with_confidence, FileFingerprint,
)
from textures.tex_capcom import parse_capcom_tex_strict, TexParseResult
from output import (
    save_texture_as_png, generate_output_filename, build_output_path,
    save_raw_data, make_texture_record, write_manifest, write_failures,
    write_unknown_files, write_summary, sha1_bytes, sha1_rgba,
)
from quality import compute_quality_metrics
from contact_sheet import generate_contact_sheet
from pack_builder import build_pack

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False, quiet: bool = False):
    level = logging.ERROR if quiet else (logging.DEBUG if verbose else logging.INFO)
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s", stream=sys.stderr)


# ──────────────────────────────────────────────
# ROM parsing (shared across subcommands)
# ──────────────────────────────────────────────

def parse_rom(input_path: str) -> Tuple[bytes, str, str, str]:
    """
    Parse ROM -> RomFS bytes.
    Returns (romfs_data, title_id_str, product_code, container_chain).
    """
    logger.info(f"Reading: {input_path}")
    with open(input_path, "rb") as f:
        rom_data = f.read()
    logger.info(f"ROM size: {len(rom_data):,} bytes")

    ext = os.path.splitext(input_path)[1].lower()
    ncch_data = None
    title_id = 0
    chain = ""

    if ext == ".3ds":
        ncsd = NCSDParser(rom_data)
        ncch_data = ncsd.get_partition(0)
        title_id = ncsd.title_id
        chain = "NCSD/partition0/NCCH"
    elif ext == ".cia":
        cia = CIAParser(rom_data)
        ncch_data = cia.get_content(0)
        chain = "CIA/content0/NCCH"
    elif ext in (".cxi", ".app", ".ncch"):
        ncch_data = rom_data
        chain = "NCCH"
    else:
        # Auto-detect
        if len(rom_data) > 0x104 and rom_data[0x100:0x104] == b"NCSD":
            ncsd = NCSDParser(rom_data)
            ncch_data = ncsd.get_partition(0)
            title_id = ncsd.title_id
            chain = "NCSD/partition0/NCCH"
        elif len(rom_data) > 0x104 and rom_data[0x100:0x104] == b"NCCH":
            ncch_data = rom_data
            chain = "NCCH"
        else:
            try:
                cia = CIAParser(rom_data)
                ncch_data = cia.get_content(0)
                chain = "CIA/content0/NCCH"
            except Exception:
                raise ValueError(f"Cannot determine ROM format: {input_path}")

    if ncch_data is None:
        raise ValueError("Failed to extract NCCH data")

    ncch = NCCHParser(ncch_data)
    if title_id == 0:
        title_id = ncch.title_id
    product_code = ncch.product_code
    title_id_str = f"{title_id:016X}"
    chain += "/RomFS"

    logger.info(f"Title ID: {title_id_str}  Product: {product_code}")
    romfs_data = ncch.get_romfs()
    return romfs_data, title_id_str, product_code, chain


def should_process_file(file_path: str, scan_all: bool) -> bool:
    if scan_all:
        return True
    ext = ""
    if "." in file_path:
        ext = "." + file_path.rsplit(".", 1)[-1].lower()
    if ext in {".tex", ".bch", ".bcres", ".bflim", ".ctpk", ".cgfx",
               ".bin", ".raw", ".dat", ".img"}:
        return True
    path_lower = file_path.lower()
    for d in ["/tex/", "/texture/", "/textures/", "/gui/", "/effect/",
              "/model/", "/chr/", "/bg/", "/ui/", "/font/"]:
        if d in path_lower:
            return True
    return False


# ──────────────────────────────────────────────
# SCAN subcommand
# ──────────────────────────────────────────────

def cmd_scan(args):
    setup_logging(args.verbose, args.quiet)
    t0 = time.time()

    romfs_data, title_id, product_code, chain = parse_rom(args.input)

    logger.info("Parsing RomFS filesystem...")
    romfs = RomFSParser(romfs_data)
    files = romfs.list_files()

    type_counts: Dict[str, int] = {}
    ext_counts: Dict[str, int] = {}
    tex_file_candidates = 0

    for path, offset, size in files:
        ext = ""
        if "." in path:
            ext = "." + path.rsplit(".", 1)[-1].lower()
        ext_counts[ext] = ext_counts.get(ext, 0) + 1

        if should_process_file(path, args.scan_all):
            tex_file_candidates += 1
            # Quick fingerprint
            _, fdata = romfs.read_file_by_index(
                next(i for i, (p, _, _) in enumerate(files) if p == path)
            )
            fp = fingerprint_file(fdata, path)
            t = fp.detected_type or "unknown"
            type_counts[t] = type_counts.get(t, 0) + 1

    elapsed = time.time() - t0

    print(f"\n--- Scan Results ---")
    print(f"ROM:        {args.input}")
    print(f"Title ID:   {title_id}")
    print(f"Product:    {product_code}")
    print(f"Container:  {chain}")
    print(f"Total files: {len(files)}")
    print(f"Texture candidates: {tex_file_candidates}")
    print(f"\nExtension breakdown:")
    for ext, cnt in sorted(ext_counts.items(), key=lambda x: -x[1]):
        print(f"  {ext or '(none)':12s} {cnt:5d}")
    print(f"\nDetected container types:")
    for t, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {t:16s} {cnt:5d}")
    print(f"\nElapsed: {elapsed:.1f}s")


# ──────────────────────────────────────────────
# EXTRACT subcommand
# ──────────────────────────────────────────────

def cmd_extract(args):
    setup_logging(args.verbose, args.quiet)
    t0 = time.time()

    romfs_data, title_id, product_code, chain = parse_rom(args.input)

    logger.info("Parsing RomFS filesystem...")
    romfs = RomFSParser(romfs_data)
    files = romfs.list_files()

    output_dir = args.output or os.path.join("output", title_id)
    os.makedirs(output_dir, exist_ok=True)
    logger.info(f"Output: {output_dir}")

    if args.list_files:
        print(f"\nRomFS: {len(files)} files\n")
        for p, _, s in sorted(files):
            print(f"  {s:>10,d}  {p}")
        return

    rom_basename = os.path.basename(args.input)
    records: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    unknowns: List[Dict[str, Any]] = []
    tex_reports: List[Dict[str, Any]] = []  # RE:Revelations TEX report

    # Stats
    files_scanned = 0
    containers_recognized = 0
    decoded_ok = 0
    decoded_fail = 0
    suspicious_count = 0
    unknown_types = 0
    tex_global_idx = 0

    for file_idx, (file_path, file_offset, file_size) in enumerate(files):
        if not should_process_file(file_path, args.scan_all):
            continue

        files_scanned += 1
        try:
            _, file_data = romfs.read_file_by_index(file_idx)
        except Exception as e:
            logger.warning(f"Cannot read {file_path}: {e}")
            continue

        if len(file_data) < 8:
            continue

        # --- Capcom .tex special handling for RE:Revelations ---
        ext = ""
        if "." in file_path:
            ext = "." + file_path.rsplit(".", 1)[-1].lower()

        if ext == ".tex" or file_data[:4] in (b"TEX\x00", b"\x00XET"):
            tex_result = parse_capcom_tex_strict(file_data, file_path,
                                                  title_id=title_id)
            tex_reports.append(tex_result.to_dict())

        # --- General extraction ---
        textures, fp = extract_textures_with_confidence(
            file_data, file_path, scan_all=args.scan_all,
            title_id=title_id,
        )

        if fp.detected_type:
            containers_recognized += 1
        elif not textures:
            unknown_types += 1
            unknowns.append(fp.to_dict())

        for tex_info in textures:
            fmt = tex_info.get("format", 0)
            w = tex_info.get("width", 0)
            h = tex_info.get("height", 0)
            pixel_data = tex_info.get("data", b"")
            confidence = tex_info.get("confidence", "low")
            parser_used = tex_info.get("parser_used", "unknown")
            notes_list = tex_info.get("capcom_parse_notes", [])
            notes_str = "; ".join(notes_list) if isinstance(notes_list, list) else str(notes_list)

            tex_id = f"tex_{tex_global_idx:04d}"
            source_blob_sha1 = sha1_bytes(pixel_data) if pixel_data else ""

            if not pixel_data or w < 1 or h < 1:
                failures.append({
                    "id": tex_id,
                    "source_file_path": file_path,
                    "reason": "no pixel data or invalid dims",
                    "width": w, "height": h,
                    "parser_used": parser_used,
                })
                decoded_fail += 1
                tex_global_idx += 1
                continue

            try:
                rgba = decode_texture_fast(pixel_data, w, h, fmt)
            except Exception as e:
                rgba = None
                fail_reason = str(e)

            if rgba is None:
                fail_reason = fail_reason if "fail_reason" in dir() else "decoder returned None"
                failures.append({
                    "id": tex_id,
                    "source_file_path": file_path,
                    "detected_format": get_format_name(fmt),
                    "width": w, "height": h,
                    "reason": fail_reason,
                    "parser_used": parser_used,
                })
                decoded_fail += 1
                tex_global_idx += 1
                continue

            # Quality check
            qm = compute_quality_metrics(rgba)

            # Save PNG
            fname = generate_output_filename(tex_global_idx, tex_info, file_path)
            out_path = build_output_path(output_dir, file_path, fname)

            if not save_texture_as_png(rgba, out_path):
                failures.append({
                    "id": tex_id,
                    "source_file_path": file_path,
                    "reason": "PNG save failed",
                })
                decoded_fail += 1
                tex_global_idx += 1
                continue

            if args.dump_raw and pixel_data:
                save_raw_data(pixel_data, out_path)

            decoded_ok += 1
            if qm["is_suspicious"]:
                suspicious_count += 1

            rel_png = os.path.relpath(out_path, output_dir)
            rec = make_texture_record(
                tex_id=tex_id,
                source_rom=rom_basename,
                source_container_chain=chain,
                source_file_path=file_path,
                source_offset=file_offset,
                detected_format=get_format_name(fmt),
                width=w,
                height=h,
                mip_count=tex_info.get("mip_count", 1),
                raw_data_size=len(pixel_data),
                decoded_png_path=rel_png,
                confidence=confidence,
                parser_used=parser_used,
                notes=notes_str,
                sha1_rgba_val=sha1_rgba(rgba),
                sha1_source_val=source_blob_sha1,
                quality_metrics=qm,
            )
            records.append(rec)
            tex_global_idx += 1

    # --- Write outputs ---
    game_title = product_code or title_id
    write_manifest(output_dir, records, args.input, title_id, game_title)
    write_failures(output_dir, failures)
    write_unknown_files(output_dir, unknowns)

    # Contact sheet
    cs_path = generate_contact_sheet(records, output_dir)

    # RE:Revelations TEX report
    if tex_reports:
        tex_report_path = os.path.join(output_dir, "re_revelations_tex_report.json")
        with open(tex_report_path, "w", encoding="utf-8") as f:
            json.dump({
                "title_id": title_id,
                "tex_files_found": len(tex_reports),
                "parsed": sum(1 for t in tex_reports if t["status"] == "parsed"),
                "partial": sum(1 for t in tex_reports if t["status"] == "partial"),
                "failed": sum(1 for t in tex_reports if t["status"] == "failed"),
                "files": tex_reports,
            }, f, indent=2)
        logger.info(f"Wrote re_revelations_tex_report.json ({len(tex_reports)} files)")

    elapsed = time.time() - t0

    summary = {
        "title_id": title_id,
        "game_title": game_title,
        "rom_file": rom_basename,
        "files_scanned": files_scanned,
        "containers_recognized": containers_recognized,
        "textures_decoded_ok": decoded_ok,
        "textures_failed": decoded_fail,
        "suspicious_outputs": suspicious_count,
        "unknown_file_types": unknown_types,
        "elapsed_seconds": round(elapsed, 1),
        "contact_sheet": cs_path if cs_path else None,
    }
    write_summary(output_dir, summary)

    # CLI output
    print(f"\n{'='*56}")
    print(f"  Extraction Results")
    print(f"{'='*56}")
    print(f"  Files scanned:          {files_scanned}")
    print(f"  Recognized containers:  {containers_recognized}")
    print(f"  Textures decoded OK:    {decoded_ok}")
    print(f"  Textures failed:        {decoded_fail}")
    print(f"  Suspicious outputs:     {suspicious_count}")
    print(f"  Unknown file types:     {unknown_types}")
    print(f"  Elapsed:                {elapsed:.1f}s")
    print(f"  Output:                 {output_dir}")
    if cs_path:
        print(f"  Contact sheet:          {cs_path}")
    print(f"{'='*56}")


# ──────────────────────────────────────────────
# REPORT subcommand
# ──────────────────────────────────────────────

def cmd_report(args):
    setup_logging(args.verbose, args.quiet)
    project_dir = args.project_dir

    manifest_path = os.path.join(project_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        logger.error(f"No manifest.json in {project_dir}")
        sys.exit(1)

    with open(manifest_path, "r") as f:
        manifest = json.load(f)

    textures = manifest.get("textures", [])
    print(f"\n--- Report for {project_dir} ---")
    print(f"Title ID:     {manifest.get('title_id', '?')}")
    print(f"Game:         {manifest.get('game_title', '?')}")
    print(f"Textures:     {len(textures)}")

    # Confidence breakdown
    conf = {}
    fmt_counts = {}
    suspicious = 0
    for t in textures:
        c = t.get("confidence", "unknown")
        conf[c] = conf.get(c, 0) + 1
        f = t.get("detected_format", "?")
        fmt_counts[f] = fmt_counts.get(f, 0) + 1
        if t.get("quality", {}).get("is_suspicious"):
            suspicious += 1

    print(f"\nConfidence breakdown:")
    for c, n in sorted(conf.items()):
        print(f"  {c:12s} {n:5d}")

    print(f"\nFormat breakdown:")
    for f, n in sorted(fmt_counts.items(), key=lambda x: -x[1]):
        print(f"  {f:12s} {n:5d}")

    print(f"\nSuspicious:   {suspicious}")

    # Failures
    fail_path = os.path.join(project_dir, "failures.json")
    if os.path.isfile(fail_path):
        with open(fail_path, "r") as f:
            fail_data = json.load(f)
        print(f"Failures:     {fail_data.get('count', 0)}")

    # Unknowns
    unk_path = os.path.join(project_dir, "unknown_files.json")
    if os.path.isfile(unk_path):
        with open(unk_path, "r") as f:
            unk_data = json.load(f)
        print(f"Unknown files: {unk_data.get('count', 0)}")

    # TEX report
    tex_path = os.path.join(project_dir, "re_revelations_tex_report.json")
    if os.path.isfile(tex_path):
        with open(tex_path, "r") as f:
            tex_data = json.load(f)
        print(f"\nCapcom TEX report:")
        print(f"  Files found:  {tex_data.get('tex_files_found', 0)}")
        print(f"  Parsed:       {tex_data.get('parsed', 0)}")
        print(f"  Partial:      {tex_data.get('partial', 0)}")
        print(f"  Failed:       {tex_data.get('failed', 0)}")


# ──────────────────────────────────────────────
# BUILD-PACK subcommand
# ──────────────────────────────────────────────

def cmd_build_pack(args):
    setup_logging(args.verbose, args.quiet)
    project_dir = args.project_dir

    manifest_path = os.path.join(project_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        logger.error(f"No manifest.json in {project_dir}")
        sys.exit(1)

    with open(manifest_path, "r") as f:
        manifest = json.load(f)

    title_id = manifest.get("title_id", "0000000000000000")
    textures = manifest.get("textures", [])

    # Check if any textures have dump hashes (from import-dump)
    has_hashes = any(t.get("dump_hash") for t in textures)
    mode = "mapped" if has_hashes else "staging"

    pack_dir = build_pack(project_dir, title_id, textures, mode=mode)

    print(f"\nPack built: {pack_dir}")
    print(f"Mode: {mode}")
    if mode == "staging":
        print(
            "WARNING: This is a STAGING pack. It does not contain runtime texture hashes.\n"
            "It cannot be used as a drop-in Azahar/Citra custom texture pack.\n"
            "To make it usable:\n"
            "  1. Run the emulator with texture dumping enabled.\n"
            "  2. Use 'import-dump <dump_folder> <project_dir>' to merge hashes.\n"
            "  3. Re-run 'build-pack <project_dir>'."
        )


# ──────────────────────────────────────────────
# IMPORT-DUMP subcommand
# ──────────────────────────────────────────────

def cmd_import_dump(args):
    setup_logging(args.verbose, args.quiet)
    dump_folder = args.dump_folder
    project_dir = args.project_dir

    if not os.path.isdir(dump_folder):
        logger.error(f"Dump folder not found: {dump_folder}")
        sys.exit(1)

    manifest_path = os.path.join(project_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        logger.error(f"No manifest.json in {project_dir}")
        sys.exit(1)

    with open(manifest_path, "r") as f:
        manifest = json.load(f)

    textures = manifest.get("textures", [])

    # Scan dump folder for PNG files
    dump_files = []
    for fname in os.listdir(dump_folder):
        if not fname.lower().endswith(".png"):
            continue
        info = _parse_dump_filename(fname)
        info["full_path"] = os.path.join(dump_folder, fname)
        dump_files.append(info)

    print(f"Found {len(dump_files)} dumped textures in {dump_folder}")

    # Try to match dump files to manifest textures by dimensions + format
    matched = 0
    unmatched_dumps = []

    for dump_info in dump_files:
        dump_w = dump_info.get("width", 0)
        dump_h = dump_info.get("height", 0)
        dump_hash = dump_info.get("hash", "")
        dump_fmt = dump_info.get("format", "")

        best_match = None
        for tex in textures:
            tw = tex.get("width", 0)
            th = tex.get("height", 0)
            if tw == dump_w and th == dump_h:
                # Prefer format match too
                if dump_fmt and dump_fmt.upper() in tex.get("detected_format", "").upper():
                    best_match = tex
                    break
                elif best_match is None:
                    best_match = tex

        if best_match and dump_hash:
            best_match["dump_hash"] = dump_hash
            matched += 1
        else:
            unmatched_dumps.append(dump_info)

    # Write updated manifest
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # Write import report
    import_report = {
        "dump_folder": dump_folder,
        "dump_files_found": len(dump_files),
        "matched_to_manifest": matched,
        "unmatched": len(unmatched_dumps),
        "unmatched_files": [d.get("filename", "") for d in unmatched_dumps],
    }
    report_path = os.path.join(project_dir, "import_dump_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(import_report, f, indent=2)

    print(f"Matched {matched} of {len(dump_files)} dump files to manifest textures")
    print(f"Unmatched: {len(unmatched_dumps)}")
    print(f"Report: {report_path}")
    if matched > 0:
        print("Run 'build-pack' again to produce a mapped pack with real hashes.")


def _parse_dump_filename(fname: str) -> Dict[str, Any]:
    """
    Parse emulator-dumped texture filenames.

    Common patterns:
      tex1_256x256_DEADBEEF_ETC1_mip0.png
      DEADBEEF01234567.png
      0xDEADBEEF_256x256.png
    """
    info = {"filename": fname, "hash": "", "width": 0, "height": 0, "format": "", "mip": 0}

    base = fname.rsplit(".", 1)[0]
    parts = base.replace("-", "_").split("_")

    for part in parts:
        # Dimension pattern: NNNxNNN
        if "x" in part:
            try:
                wh = part.lower().split("x")
                if len(wh) == 2 and wh[0].isdigit() and wh[1].isdigit():
                    info["width"] = int(wh[0])
                    info["height"] = int(wh[1])
                    continue
            except ValueError:
                pass

        # Mip level
        if part.lower().startswith("mip"):
            try:
                info["mip"] = int(part[3:])
                continue
            except ValueError:
                pass

        # Format name
        if part.upper() in FORMAT_NAMES.values():
            info["format"] = part.upper()
            continue

        # Hash: hex string, at least 8 chars
        clean = part.lower().lstrip("0x")
        if len(clean) >= 8 and all(c in "0123456789abcdef" for c in clean):
            info["hash"] = clean
            continue

    # If the whole basename is a hex hash (Citra format)
    if not info["hash"] and len(base) >= 8:
        clean = base.lower().lstrip("0x")
        if all(c in "0123456789abcdef" for c in clean):
            info["hash"] = clean

    return info


# ──────────────────────────────────────────────
# CLI parser
# ──────────────────────────────────────────────

def build_parser():
    top = argparse.ArgumentParser(
        prog="3ds-tex-extract",
        description="Extract textures from 3DS ROMs for Azahar/Citra texture packs.",
    )
    sub = top.add_subparsers(dest="command")

    # --- scan ---
    p_scan = sub.add_parser("scan", help="Scan a ROM and report contents")
    p_scan.add_argument("input", help="Path to ROM file")
    p_scan.add_argument("--scan-all", action="store_true")
    p_scan.add_argument("--verbose", action="store_true")
    p_scan.add_argument("--quiet", action="store_true")

    # --- extract ---
    p_ext = sub.add_parser("extract", help="Extract textures to PNG")
    p_ext.add_argument("input", help="Path to ROM file")
    p_ext.add_argument("-o", "--output", metavar="DIR")
    p_ext.add_argument("--scan-all", action="store_true")
    p_ext.add_argument("--dump-raw", action="store_true")
    p_ext.add_argument("--list-files", action="store_true")
    p_ext.add_argument("--verbose", action="store_true")
    p_ext.add_argument("--quiet", action="store_true")

    # --- report ---
    p_rep = sub.add_parser("report", help="Report on a previous extraction")
    p_rep.add_argument("project_dir", help="Extraction output directory")
    p_rep.add_argument("--verbose", action="store_true")
    p_rep.add_argument("--quiet", action="store_true")

    # --- build-pack ---
    p_pack = sub.add_parser("build-pack", help="Build Azahar/Citra texture pack")
    p_pack.add_argument("project_dir", help="Extraction output directory")
    p_pack.add_argument("--verbose", action="store_true")
    p_pack.add_argument("--quiet", action="store_true")

    # --- import-dump ---
    p_imp = sub.add_parser("import-dump", help="Import emulator texture dump")
    p_imp.add_argument("dump_folder", help="Folder with dumped PNGs")
    p_imp.add_argument("project_dir", help="Extraction output directory")
    p_imp.add_argument("--verbose", action="store_true")
    p_imp.add_argument("--quiet", action="store_true")

    return top


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        # Backward compat: treat first positional as ROM, run extract
        if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
            maybe_rom = sys.argv[1]
            if os.path.isfile(maybe_rom):
                sys.argv.insert(1, "extract")
                args = parser.parse_args()
            else:
                parser.print_help()
                sys.exit(1)
        else:
            parser.print_help()
            sys.exit(0)

    dispatch = {
        "scan": cmd_scan,
        "extract": cmd_extract,
        "report": cmd_report,
        "build-pack": cmd_build_pack,
        "import-dump": cmd_import_dump,
    }

    handler = dispatch.get(args.command)
    if handler:
        try:
            handler(args)
        except RuntimeError as e:
            logger.error(str(e))
            sys.exit(1)
        except Exception as e:
            logger.error(f"Fatal: {e}")
            if getattr(args, "verbose", False):
                import traceback
                traceback.print_exc()
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
