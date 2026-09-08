"""Top-level ROM loader -- file path in, RomFS bytes out.

Auto-detects the outer container by extension first, then by magic bytes.
Supports:

  .3ds / .cci         -> NCSD -> partition 0 (NCCH) -> RomFS
  .cia                -> CIA  -> content 0  (NCCH) -> RomFS
  .cxi / .app / .ncch -> NCCH (raw)                -> RomFS

`parse_rom` returns content 0's RomFS only. `iter_rom_contents` yields every
RomFS-bearing content of a CIA (content 0 plus update/DLC CFAs).

Returns:
    (romfs_bytes, title_id_str, product_code, container_chain)

container_chain is a slash-separated breadcrumb for logs and the manifest,
e.g. "NCSD/partition0/NCCH/RomFS".
"""

from __future__ import annotations

import logging
import os
import re
from typing import Iterator, Tuple

from tex_forge.core.exceptions import EncryptedROMError, ROMParseError
from tex_forge.rom.cia import CIAParser
from tex_forge.rom.ncch import NCCHParser
from tex_forge.rom.ncsd import NCSDParser

logger = logging.getLogger(__name__)

# Every outer-container extension parse_rom understands. Single source of
# truth for ROM discovery: the GUI library walker and `tex-forge batch` both
# import this so they can never drift apart. (Additive constant only; parser
# behavior is unchanged.)
ROM_EXTENSIONS = (".3ds", ".cci", ".cia", ".cxi", ".app", ".ncch")

# (romfs_bytes, title_id_str, product_code, chain)
RomContent = Tuple[bytes, str, str, str]


def parse_rom(path: str) -> Tuple[bytes, str, str, str]:
    """Open *path*, walk down to RomFS, return its bytes plus title metadata.

    Raises:
      EncryptedROMError -- partition is encrypted and can't be read.
      ROMParseError     -- container layout is unrecognized.
    """
    logger.info("Reading ROM: %s", path)
    with open(path, "rb") as f:
        rom = f.read()
    logger.info("ROM size: %d bytes", len(rom))

    ext = os.path.splitext(path)[1].lower()
    ncch_data, title_id, chain = _route(rom, ext)
    if ncch_data is None:
        raise ROMParseError(f"Cannot determine outer container for {path}")

    ncch = NCCHParser(ncch_data)
    if title_id == 0:
        title_id = ncch.title_id
    title_id_str = f"{title_id:016X}"
    product_code = ncch.product_code

    romfs = ncch.get_romfs()  # may raise EncryptedROMError
    chain += "/RomFS"
    logger.info("Title=%s product=%s chain=%s", title_id_str, product_code, chain)
    return romfs, title_id_str, product_code, chain


def iter_rom_contents(path: str) -> Iterator[RomContent]:
    """Yield every RomFS-bearing content in *path*.

    For .3ds/.cci/.cxi/.app/.ncch this yields exactly one item, identical to
    `parse_rom`. For .cia it walks all TMD contents: content 0 (the main
    NCCH), plus any update/DLC contents (CFAs) that carry their own RomFS.
    Contents that are encrypted or have no RomFS are skipped with a log line
    rather than aborting the whole title.

    `parse_rom` is unchanged and remains the single-RomFS entry point; this is
    the additive multi-content path.
    """
    ext = os.path.splitext(path)[1].lower()

    if ext == ".cia":
        with open(path, "rb") as f:
            rom = f.read()
        logger.info("Reading CIA (multi-content): %s (%d bytes)", path, len(rom))
        yield from _iter_cia_contents(rom, path)
        return

    # Single-content containers (.3ds/.cci/.cxi/.app/.ncch and auto-detect):
    # defer to parse_rom. Encrypted is a definitive answer -- never reinterpret
    # it as a CIA, so the GodMode9 hint is preserved. Only a generic parse
    # failure triggers the "maybe it's a CIA with an odd extension" probe.
    try:
        yield parse_rom(path)
        return
    except EncryptedROMError:
        raise
    except ROMParseError as orig:
        with open(path, "rb") as f:
            rom = f.read()
        try:
            CIAParser(rom)
        except Exception:
            raise orig  # genuinely not a CIA -- surface the original error
        logger.info("Container re-detected as CIA: %s", path)
        yield from _iter_cia_contents(rom, path)


def content_label_from_chain(chain: str) -> str:
    """Extract the 'contentN(role)' provenance token from a container chain.

    Returns "" when the chain has no content token (e.g. an NCSD .3ds), which
    is the signal callers use to mean "single, unlabelled content".
    """
    m = re.search(r"content\d+\([^)]*\)", chain)
    return m.group(0) if m else ""


def _iter_cia_contents(rom: bytes, path: str) -> Iterator[RomContent]:
    cia = CIAParser(rom)
    yielded = 0
    saw_encrypted = False
    for meta, blob in cia.iter_contents():
        label = "DLC" if meta.optional else ("update" if meta.chunk_index else "main")
        try:
            ncch = NCCHParser(blob)
        except ROMParseError as e:
            logger.info("CIA content %d (%s): not an NCCH, skipping (%s)",
                        meta.chunk_index, label, e)
            continue
        try:
            romfs = ncch.get_romfs()
        except EncryptedROMError:
            saw_encrypted = True
            logger.warning("CIA content %d (%s): encrypted, skipping", meta.chunk_index, label)
            continue
        except ROMParseError:
            logger.info("CIA content %d (%s): no RomFS, skipping", meta.chunk_index, label)
            continue

        title_id_str = f"{ncch.title_id:016X}"
        chain = f"CIA/content{meta.chunk_index}({label})/NCCH/RomFS"
        logger.info("CIA content %d -> title=%s product=%s chain=%s",
                    meta.chunk_index, title_id_str, ncch.product_code, chain)
        yielded += 1
        yield romfs, title_id_str, ncch.product_code, chain

    if yielded == 0:
        if saw_encrypted:
            # Nothing readable and at least one content was encrypted: surface
            # the encrypted signal so the CLI/GUI show the GodMode9 hint.
            raise EncryptedROMError(
                "CIA contents are encrypted. Decrypt with GodMode9 first: "
                "https://3ds.hacks.guide/godmode9-usage.html"
            )
        raise ROMParseError(f"No RomFS-bearing content found in CIA {path}")


def _route(rom: bytes, ext: str):
    """Pick the right outer container based on extension + magic.

    Returns (ncch_data, title_id_or_zero, chain_string) or (None, 0, "").
    """
    if ext in (".3ds", ".cci"):
        ncsd = NCSDParser(rom)
        return ncsd.get_partition(0), ncsd.title_id, "NCSD/partition0/NCCH"

    if ext == ".cia":
        cia = CIAParser(rom)
        return cia.get_content(0), 0, "CIA/content0/NCCH"

    if ext in (".cxi", ".app", ".ncch"):
        return rom, 0, "NCCH"

    # Auto-detect by magic.
    if len(rom) > 0x104:
        if rom[0x100:0x104] == b"NCSD":
            ncsd = NCSDParser(rom)
            return ncsd.get_partition(0), ncsd.title_id, "NCSD/partition0/NCCH"
        if rom[0x100:0x104] == b"NCCH":
            return rom, 0, "NCCH"

    # Final fallback: try to parse as CIA -- those don't have a stable magic at byte 0.
    try:
        cia = CIAParser(rom)
        return cia.get_content(0), 0, "CIA/content0/NCCH"
    except Exception:
        return None, 0, ""
