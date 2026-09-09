"""CRILAYLA decompression tests.

The v1 test built only all-literal streams (its own docstring admitted "no
backrefs"), so it passed while the back-reference path was completely broken.
This suite exercises real back-references three ways:

  1. A real Dragon Ball Fusions CPK entry (tests/fixtures/crilayla_dbf_*.bin)
     with its known-good decompressed output, captured after the fix and
     cross-checked against two independent reference ports. This is the ground
     -truth backref test. (Persona Q would be the reference source but is not
     available in this environment; Dragon Ball Fusions uses the same CRI CPK
     + CRILAYLA path -- see docs/CODE_OVERVIEW.md.)
  2. Hand-encoded synthetic streams built by a small CRILAYLA encoder in this
     file, so the exact bit-level token format is human-auditable.
  3. An assertion that the standalone codec and the vendored copy the live CPK
     path calls (_cpk_v1._decompress_crilayla) produce identical output.

CRILAYLA fills its output from the high address downward, so the encoder emits
tokens in fill order (the first token produces the LAST output byte).
"""

import struct
from pathlib import Path

from tex_forge.compression.crilayla import _decompress, decompress_crilayla
from tex_forge.archives._cpk_v1 import _decompress_crilayla as _cpk_decompress

_FIXTURES = Path(__file__).parent / "fixtures"


# ── minimal CRILAYLA encoder (for human-auditable synthetic streams) ─────────

def _enc_count(count: int):
    """Encode a back-reference length count (length - 3) as CRILAYLA's
    2/3/5/8-bit variable-length chunks."""
    toks = []
    for width in (2, 3, 5, 8):
        maxv = (1 << width) - 1
        if count < maxv:
            toks.append((width, count))
            return toks
        toks.append((width, maxv))
        count -= maxv
    while True:
        if count < 255:
            toks.append((8, count))
            return toks
        toks.append((8, 255))
        count -= 255


def _build(decomp_len: int, prefix: bytes, ops):
    """Build a CRILAYLA blob. `ops` are (kind, ...) in *fill* order:
    ('lit', byte) or ('ref', distance, length)."""
    tokens = []
    for op in ops:
        if op[0] == "lit":
            tokens.append((1, 0))
            tokens.append((8, op[1]))
        else:
            _, dist, length = op
            tokens.append((1, 1))
            tokens.append((13, dist - 3))
            tokens += _enc_count(length - 3)

    bits = []
    for nbits, val in tokens:
        for i in range(nbits - 1, -1, -1):
            bits.append((val >> i) & 1)
    while len(bits) % 8:
        bits.append(0)

    nbytes = len(bits) // 8
    body = bytearray(nbytes)
    for k in range(nbytes):
        b = 0
        for j in range(8):
            b = (b << 1) | bits[8 * k + j]
        body[nbytes - 1 - k] = b  # first bit-group -> last (first-read) byte

    return (b"CRILAYLA" + struct.pack("<I", decomp_len)
            + struct.pack("<I", len(body)) + bytes(body) + prefix)


# ── real fixture ─────────────────────────────────────────────────────────────

def test_real_dbf_entry_with_backrefs():
    blob = (_FIXTURES / "crilayla_dbf_in.bin").read_bytes()
    expected = (_FIXTURES / "crilayla_dbf_out.bin").read_bytes()
    # This entry compresses 100 body bytes into 68, so it necessarily uses
    # back-references -- exactly the path the old fixed-2-byte code got wrong.
    comp = struct.unpack_from("<I", blob, 0x0C)[0]
    decomp = struct.unpack_from("<I", blob, 8)[0]
    assert comp < decomp
    assert _decompress(blob) == expected


def test_real_dbf_entry_both_copies_agree():
    """The standalone codec and the vendored CPK copy must not drift."""
    blob = (_FIXTURES / "crilayla_dbf_in.bin").read_bytes()
    expected = (_FIXTURES / "crilayla_dbf_out.bin").read_bytes()
    assert _decompress(blob) == _cpk_decompress(blob) == expected


# ── synthetic streams ────────────────────────────────────────────────────────

def test_all_literals():
    payload = b"Hello"
    blob = _build(len(payload), b"", [("lit", c) for c in reversed(payload)])
    assert _decompress(blob) == payload


def test_short_backref():
    # "ABCABCABC" = literals C,B,A (fill order) then dist=3 length=6 copy.
    ops = [("lit", ord("C")), ("lit", ord("B")), ("lit", ord("A")),
           ("ref", 3, 6)]
    assert _decompress(_build(9, b"", ops)) == b"ABCABCABC"


def test_long_backref_crosses_vle_chunks():
    # 40 'Q's: three seed literals then a dist=3 copy of length 37 (the minimum
    # encodable distance is 3). count = 34 spills past the 2- and 3-bit chunks
    # into the 5-bit chunk, exercising the variable-length count assembly.
    ops = [("lit", ord("Q"))] * 3 + [("ref", 3, 37)]
    assert _decompress(_build(40, b"", ops)) == b"Q" * 40


def test_backref_with_prefix():
    ops = [("lit", ord("o")), ("lit", ord("o")), ("lit", ord("f"))]
    assert _decompress(_build(3, b"HDR:", ops)) == b"HDR:foo"


def test_detect_rejects_non_crilayla():
    assert _decompress(b"NOPE" + bytes(50)) is None


def test_public_alias_matches_private():
    blob = _build(5, b"", [("lit", c) for c in reversed(b"world")])
    assert decompress_crilayla(blob) == _decompress(blob) == b"world"
