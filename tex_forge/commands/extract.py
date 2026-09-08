"""`tex-forge extract ROM -o OUT` -- decode every texture to PNG."""

from __future__ import annotations

import argparse
import os

from tex_forge.commands._common import load_all_contents_or_die, setup
from tex_forge.pipeline.extractor import ContentSource, ExtractionPipeline, ExtractOptions
from tex_forge.pipeline.progress import CLIBarProgress, NullProgress
from tex_forge.rom.loader import content_label_from_chain as _content_label


def add_subparser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("extract", help="Extract textures to PNG")
    p.add_argument("input")
    p.add_argument("-o", "--output", metavar="DIR", default=None)
    p.add_argument("--scan-all",     action="store_true")
    p.add_argument("--dump-raw",     action="store_true")
    p.add_argument("--list-files",   action="store_true")
    p.add_argument("--dedup",        action="store_true",
                   help="Skip writing duplicate textures (keep first copy only)")
    p.add_argument("--output-mode",  choices=["normal", "azahar"], default="normal")
    p.add_argument("--report",       action="store_true",
                   help="Write report.json with parser/format breakdowns")
    p.add_argument("--no-contact-sheet", action="store_true",
                   help="Skip contact-sheet PNG generation")
    p.add_argument("--no-quality-report", action="store_true",
                   help="Skip quality_report.{json,txt} generation")
    p.add_argument("--verbose",      action="store_true")
    p.add_argument("--quiet",        action="store_true")
    p.set_defaults(_handler=_run)


def _run(args: argparse.Namespace) -> int:
    setup(args.verbose, args.quiet)
    contents = load_all_contents_or_die(args.input)

    # Title metadata comes from content 0 (the main NCCH).
    romfs0, title_id, product_code, chain0 = contents[0]
    multi = len(contents) > 1

    output_dir = args.output or os.path.join("output", title_id)
    if args.output_mode == "azahar":
        output_dir = os.path.join(output_dir, title_id)

    options = ExtractOptions(
        output_dir=output_dir,
        output_mode=args.output_mode,
        scan_all=args.scan_all,
        dedup=args.dedup,
        dump_raw=args.dump_raw,
        list_only=args.list_files,
        verbose=args.verbose,
        quiet=args.quiet,
        write_contact_sheet=not args.no_contact_sheet,
        write_quality_report=not args.no_quality_report,
    )

    extra_contents = [
        ContentSource(romfs_data=c[0], chain=c[3], source_content=_content_label(c[3]))
        for c in contents[1:]
    ]
    pipe = ExtractionPipeline(
        romfs_data=romfs0,
        title_id=title_id,
        product_code=product_code,
        chain=chain0,
        rom_path=args.input,
        options=options,
        progress=NullProgress() if args.quiet else CLIBarProgress(),
        content_source=_content_label(chain0) if multi else "",
        extra_contents=extra_contents,
    )
    if multi and not args.quiet:
        print(f"  CIA: {len(contents)} contents with RomFS "
              f"({', '.join(_content_label(c[3]) or 'content?' for c in contents)})")
    summary = pipe.run()

    # --report: parser/format/confidence breakdowns alongside the manifest.
    # (This flag was previously parsed but never consumed.)
    if args.report:
        import json
        from collections import Counter
        fmt_c, parser_c, conf_c = Counter(), Counter(), Counter()
        for r in pipe.records:
            fmt_c[r.get("detected_format", "?")] += 1
            parser_c[r.get("parser_used", "?")] += 1
            conf_c[r.get("confidence", "?")] += 1
        report_path = os.path.join(output_dir, "report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump({
                "title_id": title_id,
                "by_format": dict(fmt_c.most_common()),
                "by_parser": dict(parser_c.most_common()),
                "by_confidence": dict(conf_c.most_common()),
                "failure_count": len(pipe.failures),
            }, f, indent=2)
        if not args.quiet:
            print(f"  Report written: {report_path}")

    print()
    print("=" * 56)
    print("  Extraction Results")
    print("=" * 56)
    print(f"  Files scanned:       {summary['files_scanned']}")
    print(f"  Textures decoded OK: {summary['textures_decoded_ok']:,}")
    print(f"  Textures unique:     {summary['textures_unique']:,}")
    if summary["textures_duplicate"]:
        print(f"  Textures duplicate:  {summary['textures_duplicate']:,} ({summary['duplicate_pct']}%)")
    print(f"  Suspicious outputs:  {summary['suspicious_outputs']}")
    if "quality_score" in summary:
        print(f"  Quality score:       {summary['quality_score'] * 100:.1f}%")
    print(f"  Textures failed:     {summary['textures_failed']}")
    if summary.get("contents"):
        for c in summary["contents"]:
            print(f"    - {c['source_content']}: "
                  f"{c['textures_decoded_ok']:,} decoded / {c['files_scanned']} files")
    print(f"  Output:              {summary['output_dir']}")
    print(f"  Elapsed:             {summary['elapsed_seconds']:.1f}s")
    print("=" * 56)
    return 0
