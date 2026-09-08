"""ExtractionPipeline -- the single entry point for the whole tool.

Replaces v1's 1247-line `cmd_extract`. Same behaviour, but the loop body is
delegated to small, testable helpers:

    classify_file (scanner) -> archive recursion (scanner) -> texture decode
                            -> dedup -> quality metrics -> PNG write -> manifest record

Public usage:

    from tex_forge import ExtractionPipeline, ExtractOptions
    from tex_forge.rom import parse_rom

    romfs, title_id, product_code, chain = parse_rom("game.3ds")
    pipe = ExtractionPipeline(
        romfs_data=romfs, title_id=title_id, chain=chain,
        options=ExtractOptions(output_dir="out/", dedup=True),
    )
    summary = pipe.run()
"""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from tex_forge.core.types import Texture
from tex_forge.output import (
    build_output_path,
    generate_contact_sheet,
    generate_filename,
    make_record,
    sanitise_subdir,
    save_png,
    write_failures,
    write_manifest,
    write_quality_report,
    write_summary,
)
from tex_forge.output.manifest import sha1_bytes, sha1_rgba
from tex_forge.pipeline.adapters import (
    build_texturebin_index,
    decompress_smash_resource,
    parse_gdb1_pair_from_index,
    smash_virtual_entries,
)
from tex_forge.pipeline.dedup import Deduper
from tex_forge.pipeline.filter import FileFilter
from tex_forge.pipeline.progress import NullProgress, ProgressCallback
from tex_forge.pipeline.scanner import classify_file, extract_textures
from tex_forge.quality import compute_quality_metrics
from tex_forge.rom.romfs import RomFSParser
from tex_forge.textures.decoder import decode

logger = logging.getLogger(__name__)


def _write_raw(data: bytes, path: str) -> bool:
    """Write raw pre-decode texture bytes (dump_raw support)."""
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return True
    except OSError as e:
        logger.warning("Failed to write raw dump %s: %s", path, e)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Options
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class ExtractOptions:
    """All knobs the extractor accepts. Values match v1's CLI flags 1:1.

    Construct one of these and hand it to ExtractionPipeline.
    """

    output_dir: str = "output"
    output_mode: str = "normal"   # "normal" or "azahar"
    scan_all: bool = False
    dedup: bool = False
    dump_raw: bool = False
    list_only: bool = False
    verbose: bool = False
    quiet: bool = False
    write_png: bool = True
    write_manifest: bool = True
    write_contact_sheet: bool = True
    write_quality_report: bool = True
    skip_known_audio: bool = True


@dataclass(slots=True)
class ContentSource:
    """One RomFS to process within a single extraction run.

    For .3ds/.cxi and single-content .cia there is exactly one of these. For
    multi-content .cia (update/DLC) there is one per RomFS-bearing content;
    `source_content` is a short provenance label (e.g. "content1(DLC)") that
    is stamped onto each manifest record and used to namespace normal-mode
    output paths so two contents can't collide on the same internal path.
    """

    romfs_data: bytes
    chain: str = ""
    source_content: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# The pipeline
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ExtractionPipeline:
    """Top-level extractor.

    Wire:
      RomFS -> FileFilter -> classify_file -> extract_textures (recursive)
            -> dedup -> decode -> quality metrics -> PNG write -> manifest record

    `options.output_dir` is created on .run() if it doesn't exist. PNG writes
    happen in a background ThreadPoolExecutor since they're I/O-bound.
    """

    romfs_data: bytes
    title_id: str = ""
    product_code: str = ""
    chain: str = ""
    rom_path: str = ""              # so manifest can record the source filename
    options: ExtractOptions = field(default_factory=ExtractOptions)
    file_filter: FileFilter = field(default_factory=FileFilter)
    progress: ProgressCallback = field(default_factory=NullProgress)

    # Multi-content (CIA update/DLC) support. The primary content is the
    # romfs_data/chain above; `content_source` labels it (empty for the common
    # single-content case). `extra_contents` holds any additional RomFS to
    # process into the same output dir, sharing dedup state and the tex
    # counter. Leave both at defaults for identical single-content behaviour.
    content_source: str = ""
    extra_contents: List["ContentSource"] = field(default_factory=list)

    # Cooperative cancellation. Callers (the GUI Stop button, Ctrl-C handlers)
    # set this Event; the pipeline checks it between files and stops cleanly,
    # draining the PNG pool and writing partial outputs with a `canceled`
    # marker in the summary. This replaces thread termination, which could
    # leave PNG-writer threads running and corrupt interpreter state.
    cancel_event: Optional[threading.Event] = None

    # Populated after .run()
    records: List[Dict[str, Any]] = field(default_factory=list, init=False)
    failures: List[Dict[str, Any]] = field(default_factory=list, init=False)
    summary:  Dict[str, Any]      = field(default_factory=dict, init=False)

    # ── public entry ─────────────────────────────────────────────────────

    def run(self) -> Dict[str, Any]:
        self.file_filter.scan_all = self.options.scan_all
        dedup = Deduper(enabled=self.options.dedup)

        os.makedirs(self.options.output_dir, exist_ok=True)
        t0 = time.time()

        png_pool = (ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 4))
                    if self.options.write_png and not self.options.list_only
                    else None)
        png_futures: list = []

        # The primary content plus any extra CIA contents, processed in order
        # into the same output dir with shared dedup + a shared tex counter.
        sources: List[ContentSource] = [
            ContentSource(self.romfs_data, self.chain, self.content_source)
        ] + list(self.extra_contents)

        self._tex_counter = 0
        files_scanned = 0
        decoded_ok = 0
        decoded_fail = 0
        suspicious_count = 0
        per_content: List[Dict[str, Any]] = []

        for src in sources:
            if self._is_canceled():
                break
            stats = self._process_content(src, dedup, png_pool, png_futures)
            files_scanned   += stats["files_scanned"]
            decoded_ok       += stats["decoded_ok"]
            decoded_fail     += stats["decoded_fail"]
            suspicious_count += stats["suspicious"]
            if src.source_content:
                per_content.append({
                    "source_content":      src.source_content,
                    "container_chain":     src.chain,
                    "files_scanned":       stats["files_scanned"],
                    "textures_decoded_ok": stats["decoded_ok"],
                    "textures_failed":     stats["decoded_fail"],
                })

        # Drain the PNG-writer pool
        if png_pool is not None:
            for f in png_futures:
                try:
                    f.result()
                except Exception:
                    pass
            png_pool.shutdown(wait=False)

        elapsed = time.time() - t0

        # Aggregate stats
        unique_count = len({r.get("content_hash", "") for r in self.records
                            if r.get("content_hash") and not r.get("duplicate_of")})
        dup_count = decoded_ok - unique_count
        dup_pct = round(dup_count / decoded_ok * 100, 1) if decoded_ok else 0.0

        self.summary = {
            "title_id":           self.title_id,
            "product_code":       self.product_code,
            "container_chain":    self.chain,
            "rom_file":           os.path.basename(self.rom_path) if self.rom_path else "",
            "files_scanned":      files_scanned,
            "textures_decoded_ok": decoded_ok,
            "textures_unique":    unique_count,
            "textures_duplicate": dup_count,
            "duplicate_pct":      dup_pct,
            "textures_failed":    decoded_fail,
            "suspicious_outputs": suspicious_count,
            "elapsed_seconds":    round(elapsed, 1),
            "output_dir":         self.options.output_dir,
            "dedup_active":       self.options.dedup,
        }
        if per_content:
            self.summary["content_count"] = len(sources)
            self.summary["contents"] = per_content
        if self._is_canceled():
            self.summary["canceled"] = True

        self._write_outputs()
        return self.summary

    def _is_canceled(self) -> bool:
        return self.cancel_event is not None and self.cancel_event.is_set()

    # ── internal: one RomFS (one CIA content) ────────────────────────────

    def _process_content(
        self,
        src: "ContentSource",
        dedup: Deduper,
        png_pool: Optional[ThreadPoolExecutor],
        png_futures: list,
    ) -> Dict[str, int]:
        """Scan and decode every texture in a single RomFS.

        Appends to self.records / self.failures and advances self._tex_counter
        so texture IDs stay unique across contents. Returns this content's
        scan/decode tallies for the caller to aggregate.
        """
        romfs_data = src.romfs_data
        romfs = RomFSParser(romfs_data)
        files = list(romfs.list_files())
        smash_virtual = smash_virtual_entries(files, romfs_data) or {}
        bin_index = build_texturebin_index(files)

        files_scanned = 0
        decoded_ok = 0
        decoded_fail = 0
        suspicious_count = 0

        for file_idx, (file_path, file_offset, file_size) in enumerate(files):
            if self._is_canceled():
                logger.info("Extraction canceled at %s", file_path)
                break
            # Filter pass: extension/path. Only peek at magic if needed.
            if not self.file_filter.should_peek(file_path):
                peek = (romfs_data[file_offset:file_offset + min(file_size, 0x30)]
                        if file_size > 0 and file_offset > 0 else b"")
                # BFLIM/BCLIM carry their magic in a footer at file end, so a
                # head peek alone can never match them; hand the filter the
                # last 0x28 bytes as well (cheap: romfs_data is in memory).
                tail = (romfs_data[max(file_offset, file_offset + file_size - 0x28):
                                   file_offset + file_size]
                        if file_size > 0 and file_offset > 0 else b"")
                if not self.file_filter.should_peek(file_path, peek, tail):
                    continue

            files_scanned += 1
            self.progress(files_scanned, len(files), file_path, decoded_ok)

            if self.options.skip_known_audio and file_idx not in smash_virtual:
                if file_size > 0 and file_offset > 0:
                    peek4 = romfs_data[file_offset:file_offset + 4]
                    if self.file_filter.is_definitely_not_texture(peek4):
                        continue

            if file_idx in smash_virtual:
                file_data = decompress_smash_resource(romfs_data,
                                                      smash_virtual[file_idx])
                if not file_data:
                    continue
                file_offset = 0  # virtual entry has no real ROM offset
            else:
                try:
                    _, file_data = romfs.read_file_by_index(file_idx)
                except Exception as e:
                    logger.warning("Cannot read %s: %s", file_path, e)
                    continue
            if len(file_data) < 8:
                continue

            ext = "." + file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
            if ext == ".texturegdb":
                textures = list(parse_gdb1_pair_from_index(
                    file_data, file_path, bin_index, romfs.read_file_by_index,
                ))
            else:
                textures = list(extract_textures(
                    file_data, file_path,
                    title_id=self.title_id,
                    scan_all=self.options.scan_all,
                ))

            for tex in textures:
                ok, was_suspicious = self._handle_texture(
                    tex, dedup, png_pool, png_futures, self._tex_counter,
                    file_offset, src.chain, src.source_content,
                )
                self._tex_counter += 1
                if ok:
                    decoded_ok += 1
                    if was_suspicious:
                        suspicious_count += 1
                else:
                    decoded_fail += 1

        return {
            "files_scanned": files_scanned,
            "decoded_ok": decoded_ok,
            "decoded_fail": decoded_fail,
            "suspicious": suspicious_count,
        }


    # ── internal: per-texture processing ─────────────────────────────────

    def _handle_texture(
        self,
        tex: Texture,
        dedup: Deduper,
        png_pool: Optional[ThreadPoolExecutor],
        png_futures: list,
        tex_idx: int,
        source_offset: int,
        chain: str = "",
        source_content: str = "",
    ) -> tuple[bool, bool]:
        """Process one Texture. Returns (ok, was_suspicious)."""
        from tex_forge.textures.formats import name as fmt_name
        from tex_forge.textures.azahar_hash import azahar_hash_hex

        tex_id = f"tex_{tex_idx:04d}"
        notes_str = "; ".join(tex.notes)
        rom_basename = os.path.basename(self.rom_path) if self.rom_path else ""

        if not tex.data or tex.width < 1 or tex.height < 1:
            self.failures.append({
                "id": tex_id, "source_file_path": tex.source_file,
                "reason": "no pixel data or invalid dims",
                "parser_used": tex.parser_used,
            })
            return False, False

        # Azahar runtime lookup hash (CityHash64 of the raw GPU bytes).
        # Computed once and attached to the manifest in both code paths
        # below, so build-pack can produce drop-in packs offline.
        azahar_h = azahar_hash_hex(tex.data) or ""

        # list_only: record what was found, skip decode / quality / PNG.
        if self.options.list_only:
            self.records.append(make_record(
                tex_id=tex_id,
                source_rom=rom_basename,
                source_container_chain=chain,
                source_file_path=tex.source_file,
                source_offset=source_offset,
                detected_format=fmt_name(tex.format),
                width=tex.width, height=tex.height,
                mip_count=tex.mip_count,
                raw_data_size=len(tex.data),
                decoded_png_path="",
                confidence=tex.confidence,
                parser_used=tex.parser_used,
                notes=notes_str,
                sha1_source_blob=sha1_bytes(tex.data),
                raw_data_hash_xxh64=dedup.raw_hash(tex.data),
                azahar_hash_cityhash64=azahar_h,
                source_content=source_content,
            ))
            return True, False

        # Pre-decode dedup
        hit = dedup.check_raw(tex.data) if dedup.enabled else None
        if hit is not None:
            self.records.append(make_record(
                tex_id=tex_id,
                source_rom=rom_basename,
                source_container_chain=chain,
                source_file_path=tex.source_file,
                source_offset=source_offset,
                detected_format=fmt_name(tex.format),
                width=tex.width, height=tex.height,
                mip_count=tex.mip_count,
                raw_data_size=len(tex.data),
                decoded_png_path="",
                confidence=tex.confidence,
                parser_used=tex.parser_used,
                notes=notes_str,
                sha1_source_blob=sha1_bytes(tex.data),
                content_hash=hit.content_hash,
                raw_data_hash_xxh64=dedup.raw_hash(tex.data),
                azahar_hash_cityhash64=azahar_h,
                duplicate_of=hit.first_tex_id,
                source_content=source_content,
            ))
            return True, False

        # Decode
        try:
            rgba = decode(tex.data, tex.width, tex.height, tex.format)
        except Exception as e:
            rgba = None
            decode_err = str(e)
        else:
            decode_err = ""
        if rgba is None:
            self.failures.append({
                "id": tex_id, "source_file_path": tex.source_file,
                "detected_format": fmt_name(tex.format),
                "width": tex.width, "height": tex.height,
                "reason": decode_err or "decoder returned None",
                "parser_used": tex.parser_used,
            })
            return False, False

        # Apply BFLIM-style crop
        if tex.crop_width and tex.crop_height:
            if tex.crop_width < tex.width or tex.crop_height < tex.height:
                rgba = rgba[:tex.crop_height, :tex.crop_width]
                tex.width = tex.crop_width
                tex.height = tex.crop_height

        # BCH heuristic filter -- reject solid-color decodes
        if tex.parser_used == "bch":
            flat = rgba.reshape(-1, 4)
            sample_u32 = np.ascontiguousarray(flat[:min(2000, len(flat))]).view(np.uint32).ravel()
            if sample_u32.min() == sample_u32.max():
                logger.debug("BCH filter: skip %dx%d solid color", tex.width, tex.height)
                return False, False
            # Thin-strip + few-colors check
            aspect = max(tex.width, tex.height) / max(min(tex.width, tex.height), 1)
            if aspect > 8 and len(np.unique(sample_u32)) <= 3:
                logger.debug("BCH filter: skip %dx%d thin strip", tex.width, tex.height)
                return False, False

        # Content dedup
        content_hash, prev_id = dedup.check_content(rgba)
        if prev_id is None:
            dedup.remember_content(content_hash, tex_id)

        # Quality metrics (skip for duplicates -- we won't write them)
        if prev_id is None:
            quality = compute_quality_metrics(rgba, pica_format=tex.format)
        else:
            quality = {"is_suspicious": False, "pct_transparent": 0.0,
                       "variance_score": 0.0, "flags": []}
        was_suspicious = bool(quality.get("is_suspicious"))

        # PNG path + asynchronous write
        out_path = self._build_output_path(tex_id, tex, source_content,
                                           azahar_h, tex_idx)
        rel_png = ""
        raw_rel = ""
        if not (self.options.dedup and prev_id is not None):
            if self.options.write_png and png_pool is not None:
                png_futures.append(png_pool.submit(save_png, rgba, out_path))
            rel_png = os.path.relpath(out_path, self.options.output_dir)
            # dump_raw: keep the pre-decode GPU bytes for round-trip and
            # debugging work. Always under raw/ (never beside Azahar-named
            # PNGs, so a pack folder stays drop-in clean).
            if self.options.dump_raw and tex.data:
                raw_name = f"{tex_id}_{tex.width}x{tex.height}_{fmt_name(tex.format)}.bin"
                raw_path = os.path.join(self.options.output_dir, "raw", raw_name)
                if png_pool is not None:
                    png_futures.append(png_pool.submit(_write_raw, tex.data, raw_path))
                else:
                    _write_raw(tex.data, raw_path)
                raw_rel = os.path.relpath(raw_path, self.options.output_dir)

        # Remember raw hash on first occurrence for future raw-byte dedup
        if dedup.enabled and prev_id is None:
            dedup.remember_raw(tex.data, tex_id, content_hash)

        self.records.append(make_record(
            tex_id=tex_id,
            source_rom=rom_basename,
            source_container_chain=chain,
            source_file_path=tex.source_file,
            source_offset=source_offset,
            detected_format=fmt_name(tex.format),
            width=tex.width, height=tex.height,
            mip_count=tex.mip_count,
            raw_data_size=len(tex.data),
            decoded_png_path=rel_png,
            confidence=tex.confidence,
            parser_used=tex.parser_used,
            notes=notes_str,
            sha1_rgba=sha1_rgba(rgba),
            sha1_source_blob=sha1_bytes(tex.data),
            quality=quality,
            content_hash=content_hash,
            raw_data_hash_xxh64=dedup.raw_hash(tex.data),
            azahar_hash_cityhash64=azahar_h,
            duplicate_of=prev_id or "",
            source_content=source_content,
            raw_dump_path=raw_rel,
        ))
        return True, was_suspicious

    # ── output dir / filename composition ─────────────────────────────────

    def _build_output_path(self, tex_id: str, tex: Texture,
                           source_content: str = "", azahar_hash_hex: str = "",
                           tex_idx: int = 0) -> str:
        if self.options.output_mode == "azahar":
            # Drop-in Azahar naming: tex1_<W>x<H>_<CityHash64>_<code>_mip0.png.
            # MUST use the CityHash64 (Azahar's legacy lookup hash), never a
            # different algorithm, or the emulator silently won't match it.
            # Routed through azahar_filename so this is byte-identical to what
            # build-pack emits. All contents share one flat tree; identical
            # textures collapse to the same filename, which is what Azahar wants.
            from tex_forge.textures.azahar_hash import azahar_filename
            from tex_forge.textures.formats import name as fmt_name

            fname = None
            if azahar_hash_hex:
                try:
                    fname = azahar_filename(
                        tex.width, tex.height, int(azahar_hash_hex, 16),
                        fmt_name(tex.format),
                    )
                except ValueError:
                    fname = None
            if fname is None:
                # No CityHash backend, or an unsupported format. Fall back to a
                # clearly non-loadable name so the failure is visible rather
                # than masquerading as a valid (but wrong-hash) Azahar file.
                logger.warning(
                    "azahar mode: no usable hash/format for %s (%s %dx%d); "
                    "writing non-droppable name",
                    tex_id, fmt_name(tex.format), tex.width, tex.height,
                )
                fname = f"UNRESOLVED_{tex_id}_{tex.width}x{tex.height}.png"
            return os.path.join(self.options.output_dir, fname)

        # tex_idx is the pipeline-wide running counter; without it every
        # unnamed texture sharing a format and size in the same source dir
        # composed the identical filename and silently overwrote the previous
        # one on disk (manifest then pointed N records at one file).
        fname = generate_filename(tex_idx, {
            "format": tex.format, "width": tex.width, "height": tex.height,
            "name": tex.name,
        })
        # In normal mode, namespace extra CIA contents under their own subdir so
        # an update/DLC RomFS can't overwrite the main game's identical paths.
        base_dir = self.options.output_dir
        if source_content:
            safe = "".join(ch if ch.isalnum() else "_" for ch in source_content).strip("_")
            if safe:
                base_dir = os.path.join(base_dir, safe)
        return build_output_path(base_dir, tex.source_file, fname)

    # ── final outputs (manifest + quality + contact sheet) ────────────────

    def _write_outputs(self) -> None:
        if not self.options.write_manifest:
            return

        rom_file = self.rom_path or self.summary.get("rom_file", "")
        from tex_forge.metadata.games import get_game_name
        game_title = get_game_name(self.title_id, self.product_code)

        write_manifest(
            self.options.output_dir, self.records,
            rom_file=rom_file, title_id=self.title_id,
            game_title=game_title, summary=self.summary,
            container_chain=self.chain,
        )
        write_failures(self.options.output_dir, self.failures)
        write_summary(self.options.output_dir, self.summary)

        if (self.options.write_quality_report and self.records
                and not self.options.list_only):
            try:
                fmt_dist: Dict[str, int] = {}
                for r in self.records:
                    fmt_dist[r.get("detected_format", "?")] = fmt_dist.get(
                        r.get("detected_format", "?"), 0) + 1
                report = write_quality_report(
                    self.records,
                    output_dir=self.options.output_dir,
                    game_name=game_title,
                    rom_file=rom_file,
                    format_distribution=fmt_dist,
                )
                self.summary["quality_score"] = report.get("quality_score", 0.0)
            except Exception as e:
                logger.warning("Quality report failed: %s", e)

        if (self.options.write_contact_sheet and self.records
                and not self.options.list_only):
            try:
                generate_contact_sheet(self.records, self.options.output_dir)
            except Exception as e:
                logger.warning("Contact sheet failed: %s", e)
