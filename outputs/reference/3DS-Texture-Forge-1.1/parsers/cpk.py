"""CRI CPK archive parser for 3DS games.

CPK is CRI Middleware's streaming archive format. The entire RomFS is often
a single .cpk file containing thousands of game assets (Persona Q, 7th Dragon
III, Sonic Lost World, Dragon Ball Fusions, Rhythm Thief, etc.).

Structure:
  [0x00] CPK header chunk
         magic: "CPK " (4) + 0xFF (1) + pad (3) + utf_size (u32 LE) + pad (4)
         @UTF table starting at 0x10 — 1 row, describes the CPK itself.
         Key columns: TocOffset (u64), ContentOffset (u64), TocSize (u64)

  [TocOffset] TOC chunk — starts with "TOC " + @UTF table
              One row per file. Key columns per row:
              DirName (string), FileName (string),
              FileOffset (u64, relative to ContentOffset or TocOffset),
              FileSize (u32), ExtractSize (u32), ID (u32)

  [ContentOffset + FileOffset] file data, possibly CRILAYLA-compressed

@UTF encoding:
  All integer fields are big-endian. Strings are null-terminated in a
  string pool. Blobs reference a separate data section.
"""

import struct
import logging
from typing import List, Dict, Optional, Any, Tuple, Iterator

logger = logging.getLogger(__name__)

CPK_MAGIC = b'CPK '
TOC_MAGIC = b'TOC '
UTF_MAGIC = b'@UTF'

# PICA200 / common texture extensions we want to extract from CPK archives
_TEX_EXTS = frozenset({
    'ctpk', 'bch', 'bcres', 'cgfx', 'bflim', 'bclim', 'ctxb',
    'sarc', 'arc', 'garc', 'narc', 'szs', 'zar', 'gar', 'darc',
    'bin', 'dat',
    # NintendoWare model/texture containers
    'bcmdl', 'bctex', 'stex',
    # Bandai Namco jIMG textures
    'jtex', 'jarc',
    # CRI archives containing textures
    'cpk',
})


# ─── @UTF table parser ────────────────────────────────────────────────────────

_TYPE_SIZE = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 8, 7: 8,
              8: 4, 9: 8, 0xA: 4, 0xB: 8}  # type → byte size of value

_TYPE_UNPACK = {
    0: '>B', 1: '>b', 2: '>H', 3: '>h', 4: '>I', 5: '>i',
    6: '>Q', 7: '>q', 8: '>f', 9: '>d',
}

# Column storage flags (bits [5:4] of the flags byte, mask 0x30):
#   0x00 = zero (always zero, not stored)
#   0x10 = constant (value stored in column definition)
#   0x30 = per-row (value stored in the row data section)
# Some CRI tools use 0x50 for per-row as well.
_STORAGE_ZERO  = 0x00
_STORAGE_CONST = 0x10
_STORAGE_ROW   = 0x30  # also 0x20 in some variants


class UtfTable:
    """Parsed @UTF table — list of row dicts with column name → value."""

    def __init__(self, rows: List[Dict[str, Any]], name: str = ""):
        self.rows = rows
        self.name = name

    def get(self, col: str, default=None, row: int = 0):
        if not self.rows:
            return default
        return self.rows[row].get(col, default)


def _parse_utf(data: bytes, base_off: int) -> Optional[UtfTable]:
    """Parse a @UTF table starting at base_off within data."""
    if base_off + 8 > len(data):
        return None
    if data[base_off:base_off + 4] != UTF_MAGIC:
        return None

    table_size = struct.unpack_from('>I', data, base_off + 4)[0]
    # All offsets inside @UTF are relative to (base_off + 8).
    rel = base_off + 8
    end = rel + table_size
    if end > len(data):
        end = len(data)

    if rel + 24 > end:
        return None

    rows_off = rel + struct.unpack_from('>I', data, rel + 0)[0]
    str_off  = rel + struct.unpack_from('>I', data, rel + 4)[0]
    dat_off  = rel + struct.unpack_from('>I', data, rel + 8)[0]
    name_str_off = struct.unpack_from('>I', data, rel + 12)[0]
    field_count  = struct.unpack_from('>H', data, rel + 16)[0]
    row_size     = struct.unpack_from('>H', data, rel + 18)[0]
    row_count    = struct.unpack_from('>I', data, rel + 20)[0]

    table_name = _read_cstr(data, str_off + name_str_off)

    # Parse column definitions (start immediately after the 24-byte header).
    col_defs = []
    cpos = rel + 24
    for _ in range(field_count):
        if cpos >= end:
            break
        flags = data[cpos]; cpos += 1
        type_id = flags & 0x0F   # low 4 bits = data type (0x00–0x0B)
        storage = flags >> 5     # top 3 bits: 0=zero, 1=const-inline, 2=per-row
        if cpos + 4 > end:
            break
        name_off = struct.unpack_from('>I', data, cpos)[0]; cpos += 4
        col_name = _read_cstr(data, str_off + name_off)

        const_val = None
        if storage == 1:  # constant — value stored inline in column def
            const_val, cpos = _read_typed(data, cpos, type_id, dat_off, str_off)

        col_defs.append((col_name, type_id, storage, const_val))

    # Parse rows.
    rows = []
    for r in range(row_count):
        row_base = rows_off + r * row_size
        rpos = row_base
        row_dict: Dict[str, Any] = {}
        for col_name, type_id, storage, const_val in col_defs:
            if storage == 1:  # constant — use inline value from col def
                row_dict[col_name] = const_val
            elif storage == 0:  # zero — always 0, not stored anywhere
                row_dict[col_name] = 0
            else:  # 2 = per-row (also 3 in some variants)
                val, rpos = _read_typed(data, rpos, type_id, dat_off, str_off)
                row_dict[col_name] = val
        rows.append(row_dict)

    return UtfTable(rows, table_name)


def _read_cstr(data: bytes, off: int) -> str:
    """Read null-terminated ASCII/Latin-1 string at offset."""
    if off < 0 or off >= len(data):
        return ""
    end = data.index(b'\x00', off) if b'\x00' in data[off:off + 1024] else off + 64
    try:
        return data[off:end].decode('ascii', errors='replace')
    except Exception:
        return ""


def _read_typed(data: bytes, pos: int, type_id: int,
                dat_off: int, str_off: int = 0) -> Tuple[Any, int]:
    """Read one typed value from pos, return (value, new_pos)."""
    if type_id == 0xA:  # string — offset into strings section
        if pos + 4 > len(data):
            return ("", pos + 4)
        soff = struct.unpack_from('>I', data, pos)[0]
        return (_read_cstr(data, str_off + soff), pos + 4)
    elif type_id == 0xB:  # blob
        if pos + 8 > len(data):
            return (None, pos + 8)
        boff = struct.unpack_from('>I', data, pos)[0]
        bsz  = struct.unpack_from('>I', data, pos + 4)[0]
        blob = data[dat_off + boff: dat_off + boff + bsz] if boff < len(data) else b''
        return (blob, pos + 8)
    else:
        sz = _TYPE_SIZE.get(type_id, 0)
        if sz == 0 or pos + sz > len(data):
            return (0, pos + sz)
        fmt = _TYPE_UNPACK.get(type_id)
        if fmt:
            val = struct.unpack_from(fmt, data, pos)[0]
        else:
            val = 0
        return (val, pos + sz)


# ─── CRILAYLA decompressor ────────────────────────────────────────────────────

def _decompress_crilayla(data: bytes) -> Optional[bytes]:
    """Decompress CRILAYLA-compressed data.

    CRILAYLA layout:
      [0x00] magic "CRILAYLA" (8)
      [0x08] decomp_size u32 LE  (size of compressed body's decompressed output)
      [0x0C] comp_size   u32 LE  (size of the compressed body)
      [0x10] compressed body     (comp_size bytes, read backwards)
      [0x10 + comp_size] prefix  (uncompressed header of original file)

    Final output = prefix + decompressed_body
    """
    if len(data) < 0x10:
        return None
    if data[:8] != b'CRILAYLA':
        return None

    decomp_size = struct.unpack_from('<I', data, 8)[0]
    comp_size   = struct.unpack_from('<I', data, 0xC)[0]

    if decomp_size > 64 * 1024 * 1024:
        logger.debug(f"CRILAYLA: decomp_size {decomp_size:,} too large, skipping")
        return None

    # Prefix: bytes after the compressed body (uncompressed header of original file)
    prefix_off = 0x10 + comp_size
    prefix = data[prefix_off:] if prefix_off < len(data) else b''

    out = bytearray(decomp_size)
    out_pos = decomp_size
    # Read compressed body backwards: from byte (0x10 + comp_size - 1) down to 0x10
    in_pos = min(0x10 + comp_size - 1, len(data) - 1)

    while out_pos > 0 and in_pos >= 0x10:
        flag = data[in_pos]; in_pos -= 1
        for bit in range(8):
            if out_pos <= 0 or in_pos < 0x10:
                break
            if flag & (0x80 >> bit):
                # Back-reference: 2 bytes encode length and distance
                if in_pos < 0x11:
                    break
                hi = data[in_pos]; in_pos -= 1
                lo = data[in_pos]; in_pos -= 1
                length = (hi >> 3) + 3
                dist   = ((hi & 0x07) << 8) | lo
                for _ in range(length):
                    if out_pos <= 0:
                        break
                    out_pos -= 1
                    out[out_pos] = out[out_pos + dist + 1] if (out_pos + dist + 1) < decomp_size else 0
            else:
                # Literal byte
                out_pos -= 1
                out[out_pos] = data[in_pos]; in_pos -= 1

    return bytes(prefix) + bytes(out)


# Known texture container magics to locate inside multi-segment CRILAYLA output
_CONTAINER_MAGICS = (b'CTPK', b'CGFX', b'BCH\x00', b'SARC', b'darc')


def _find_container_in(data: bytes) -> Optional[bytes]:
    """Locate a texture container inside combined CRILAYLA output.

    CRI CPK entries can store [uncompressed header][CRILAYLA pixel data].
    The texture container (e.g. CTPK) starts at some offset within the
    combined output. Returns data from that offset, or None if not found.
    """
    for magic in _CONTAINER_MAGICS:
        pos = data.find(magic)
        if pos >= 0 and pos + 16 < len(data):
            return data[pos:]
    return None


# ─── CPK file extraction ──────────────────────────────────────────────────────

def _is_known_container(data: bytes) -> bool:
    """Check if data starts with a known texture container magic."""
    if len(data) < 4:
        return False
    return data[:4] in _CONTAINER_MAGICS


def _resolve_crilayla_entry(cpk: bytes, cri_abs: int, file_size: int,
                            extract_size: int) -> Optional[bytes]:
    """Decompress a CRILAYLA entry, handling extended and grouped reads.

    Three cases:
    1. Normal: comp_sz fits within file_size → standard decompress
    2. Extended: comp_sz > file_size, decomp_sz <= extract_size → read more bytes
    3. Grouped: decomp_sz > extract_size → multi-texture block, try prefix probing
    """
    if cri_abs + 16 > len(cpk) or cpk[cri_abs:cri_abs + 8] != b'CRILAYLA':
        return None

    decomp_sz = struct.unpack_from('<I', cpk, cri_abs + 8)[0]
    comp_sz   = struct.unpack_from('<I', cpk, cri_abs + 0xC)[0]

    if decomp_sz <= extract_size:
        # Normal or extended: prefix = extract_size - decomp_sz
        prefix_sz = extract_size - decomp_sz
        total = 0x10 + comp_sz + prefix_sz
        if cri_abs + total > len(cpk):
            total = len(cpk) - cri_abs
        cri_data = cpk[cri_abs:cri_abs + total]
        return _decompress_crilayla(cri_data)
    else:
        # Grouped: decomp_sz > extract_size → probe small prefix sizes
        for prefix_sz in (256, 128, 512, 0, 1024, 2048):
            total = 0x10 + comp_sz + prefix_sz
            if cri_abs + total > len(cpk):
                continue
            cri_data = cpk[cri_abs:cri_abs + total]
            dec = _decompress_crilayla(cri_data)
            if dec and _is_known_container(dec):
                return dec
        return None


def _build_crilayla_index(cpk: bytes, start: int, end: int) -> List[Tuple[int, int, int]]:
    """Scan a region of the CPK and return all CRILAYLA headers as (abs_off, decomp_sz, comp_sz)."""
    index = []
    pos = start
    while pos < end:
        idx = cpk.find(b'CRILAYLA', pos, end)
        if idx < 0:
            break
        if idx + 16 <= len(cpk):
            dsz = struct.unpack_from('<I', cpk, idx + 8)[0]
            csz = struct.unpack_from('<I', cpk, idx + 0xC)[0]
            if dsz > 0 and csz > 0 and dsz < 64 * 1024 * 1024:
                index.append((idx, dsz, csz))
        pos = idx + 1
    return index


def _search_preceding_crilayla(cpk: bytes, entry_abs: int,
                               extract_size: int,
                               cri_index: List[Tuple[int, int, int]],
                               cache: Dict) -> Optional[bytes]:
    """Search the pre-built CRILAYLA index for a stream that spans this entry."""
    import bisect
    # Binary search: index is sorted by offset (first element of tuple)
    right = bisect.bisect_right(cri_index, (entry_abs, float('inf'), float('inf')))

    misses = 0
    for i in range(right - 1, max(right - 200, -1), -1):
        cri_abs, decomp_sz, comp_sz = cri_index[i]

        # Quick skip: decomp_sz must plausibly relate to extract_size
        if decomp_sz > 8 * extract_size and decomp_sz > 1024 * 1024:
            continue

        # Positive cache: return immediately
        cached = cache.get(cri_abs)
        if isinstance(cached, bytes):
            return cached
        # Negative cache: skip if already tried with this extract_size
        neg_key = (cri_abs, extract_size)
        if neg_key in cache:
            body_end = cri_abs + 0x10 + comp_sz
            if body_end < entry_abs:
                misses += 1
                if misses > 8:
                    break
            continue

        result = _resolve_crilayla_entry(cpk, cri_abs, comp_sz + 0x10,
                                         extract_size)
        if result and _is_known_container(result):
            cache[cri_abs] = result
            return result
        cache[neg_key] = None

        body_end = cri_abs + 0x10 + comp_sz
        if body_end < entry_abs:
            misses += 1
            if misses > 8:
                break

    return None


def is_cpk(data: bytes) -> bool:
    return len(data) >= 4 and data[:4] == CPK_MAGIC


def iter_cpk_textures(data: bytes) -> Iterator[Tuple[str, bytes]]:
    """Yield (path, file_data) for every texture-relevant file in a CPK archive.

    Yields raw bytes for each candidate entry so the caller can run the normal
    texture scanner on them.  Skips audio, video, and script files to keep
    memory usage manageable.
    """
    if not is_cpk(data):
        return

    # ── Parse CPK header @UTF to get TocOffset and ContentOffset ──────────────
    cpk_utf = _parse_utf(data, 0x10)
    if cpk_utf is None:
        logger.debug("CPK: failed to parse header @UTF")
        return

    toc_offset     = cpk_utf.get('TocOffset')     or 0
    content_offset = cpk_utf.get('ContentOffset') or 0
    etoc_offset    = cpk_utf.get('EtocOffset')    or 0

    if toc_offset == 0:
        logger.debug("CPK: TocOffset is 0, nothing to read")
        return

    # ── Find the TOC @UTF table (magic "TOC " precedes the @UTF) ─────────────
    toc_start = toc_offset
    if toc_start + 4 > len(data):
        return
    if data[toc_start:toc_start + 4] == TOC_MAGIC:
        toc_utf_off = toc_start + 0x10  # skip "TOC \xFF\x00\x00\x00 size(4) pad(4)"
    else:
        toc_utf_off = toc_start  # @UTF directly

    toc_utf = _parse_utf(data, toc_utf_off)
    if toc_utf is None or not toc_utf.rows:
        logger.debug(f"CPK: failed to parse TOC @UTF at 0x{toc_utf_off:X}")
        return

    logger.debug(f"CPK: {len(toc_utf.rows)} TOC entries, ContentOffset=0x{content_offset:X}")

    # FileOffset in the TOC can be relative to ContentOffset or TocOffset.
    # Most CPKs use content_offset; some older ones use toc_offset.
    # We try content_offset first and fall back to toc_offset if the read
    # lands outside the file.
    offset_base = content_offset if content_offset else toc_offset

    # Pre-build CRILAYLA index over the texture-entry region for fast fragment resolution.
    # Find the byte range spanned by texture entries to avoid scanning the whole CPK.
    _tex_min = _tex_max = 0
    for _row in toc_utf.rows:
        _fn = _row.get('FileName', '') or ''
        _ext = _fn.rsplit('.', 1)[-1].lower() if '.' in _fn else ''
        if _ext in ('ctpk', 'bch', 'bcres', 'cgfx'):
            _off = offset_base + (_row.get('FileOffset') or 0)
            _sz = _row.get('FileSize') or 0
            if _tex_min == 0 or _off < _tex_min:
                _tex_min = _off
            if _off + _sz > _tex_max:
                _tex_max = _off + _sz
    _cri_index = _build_crilayla_index(data, _tex_min, min(len(data), _tex_max + 65536)) if _tex_max > _tex_min else []
    _cri_cache: Dict = {}  # cri_abs -> decompressed data (or None)

    found = yielded = 0
    for row in toc_utf.rows:
        dir_name  = row.get('DirName', '') or ''
        file_name = row.get('FileName', '') or ''
        if not file_name:
            continue

        # Determine extension.
        ext = file_name.rsplit('.', 1)[-1].lower() if '.' in file_name else ''
        # Skip audio, video, shader, config — keep only potential texture carriers.
        if ext in ('acb', 'awb', 'bcstm', 'bcsnd', 'bcsar', 'moflex',
                   'txt', 'csv', 'xml', 'lua', 'shbin', 'msbt', 'msbp',
                   'mp4', 'adx', 'hca', 'usm'):
            continue
        if ext and ext not in _TEX_EXTS:
            continue
        found += 1

        file_offset  = row.get('FileOffset')  or 0
        file_size    = row.get('FileSize')     or 0
        extract_size = row.get('ExtractSize')  or 0
        if extract_size == 0:
            extract_size = file_size

        if file_size == 0:
            continue

        abs_off = offset_base + file_offset
        if abs_off + file_size > len(data):
            # Try alternate base
            alt_off = toc_offset + file_offset
            if alt_off + file_size <= len(data):
                abs_off = alt_off
            else:
                continue

        raw = data[abs_off: abs_off + file_size]

        # Decompress if CRILAYLA-compressed.
        if len(raw) >= 0x10 and raw[:8] == b'CRILAYLA':
            raw = _resolve_crilayla_entry(data, abs_off, file_size, extract_size) or raw
        elif extract_size > file_size:
            # Compressed but CRILAYLA not at offset 0.
            # CRI CPK entries can store: [uncompressed header] [CRILAYLA pixel data]
            # Combine both regions and locate the texture container within.
            cri_off = raw.find(b'CRILAYLA')
            if cri_off > 0:
                resolved = _resolve_crilayla_entry(data, abs_off + cri_off,
                                                   file_size - cri_off, extract_size)
                if resolved is not None:
                    # Combine uncompressed header with CRILAYLA output
                    combined = raw[:cri_off] + resolved
                    container = _find_container_in(combined)
                    raw = container if container is not None else resolved
            if not _is_known_container(raw):
                # Try finding a matching CRILAYLA before this entry
                resolved = _search_preceding_crilayla(data, abs_off, extract_size, _cri_index, _cri_cache)
                if resolved is not None:
                    raw = resolved

        path = f"{dir_name}/{file_name}" if dir_name else file_name
        yielded += 1
        yield path, raw

    logger.info(f"CPK: {len(toc_utf.rows)} entries, {found} non-audio candidates, "
                f"{yielded} yielded")
