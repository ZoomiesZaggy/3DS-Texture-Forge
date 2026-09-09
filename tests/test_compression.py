"""Round-trip the compressors we ship: LZ10, LZ11, Yaz0 (against known fixtures)."""

import struct

from tex_forge.compression import try_decompress
from tex_forge.compression.lz_nintendo import _decompress_lz10, _decompress_lz11


def test_lz10_all_literals():
    hdr = struct.pack("<I", 0x10 | (5 << 8))
    payload = bytes([0x00]) + b"AAAAA"
    assert _decompress_lz10(hdr + payload) == b"AAAAA"


def test_lz11_all_literals_fast_path():
    hdr = struct.pack("<I", 0x11 | (5 << 8))
    payload = bytes([0x00]) + b"AAAAA"
    assert _decompress_lz11(hdr + payload) == b"AAAAA"


def test_lz11_backref_top2():
    """Encode 'ABCABC' as 3 literals + 1 backref(len=3, dist=3)."""
    hdr = struct.pack("<I", 0x11 | (6 << 8))
    # flag=0b00010000 -> bits[7..4]=0,0,0,1 = literal,literal,literal,backref
    # backref top=2, length=3, distance=3 -> indicator=0x20, b2=0x02
    payload = bytes([0x10, ord("A"), ord("B"), ord("C"), 0x20, 0x02])
    assert _decompress_lz11(hdr + payload) == b"ABCABC"


def test_dispatcher_picks_lz11():
    hdr = struct.pack("<I", 0x11 | (5 << 8))
    payload = bytes([0x00]) + b"AAAAA"
    result = try_decompress(hdr + payload)
    assert result is not None
    assert result.codec == "lz_nintendo_lz11"
    assert result.data == b"AAAAA"


def test_unknown_data_yields_none():
    assert try_decompress(b"random non-magic bytes here") is None


# ── Level-5 / Nintendo Huffman child-offset correctness ──────────────────────
#
# The canonical Nintendo Huffman node layout (GBATEK) computes a node's child
# pair as:  child_base = (node_off & ~1) + (node & 0x3F) * 2 + 2  with the left
# child at child_base and the right at child_base + 1. The v1 code added the
# 0x3F offset as a byte count (not 16-bit words) and aligned on the
# tree-relative offset instead of the node's absolute offset, so it walked to
# the wrong children.
#
# These fixtures are hand-laid trees that follow the canonical formula exactly
# (real, spec-compliant streams -- not arbitrary bytes). A real captured game
# entry would be preferable, but no ROM reachable in this environment exercises
# the Level-5 Huffman path (Fantasy Life's archive is LZ + ztex; see
# docs/CODE_OVERVIEW.md), so the correctness proof is pinned to two minimal
# streams whose expected output is verified by hand. Each fixture is chosen to
# fail under exactly one of the two original bugs.

from tex_forge.textures.containers._v1_level5 import decompress_l5


def _l5_huffman_blob(method_nibble, dec_size, body):
    return struct.pack("<I", (dec_size << 3) | method_nibble) + body


# Fixture 1: 8-bit Huffman, root child pair placed at word-offset 2 (rel=2).
#   [0]=3   tree-size byte -> (3+1)*2 = 8 tree bytes
#   [1]=0xC2 root: left leaf | right leaf | rel=2
#   [6]=0x41 'A' left child  (child_base = (1&~1)+2*2+2 = 6)
#   [7]=0x42 'B' right child (child_base+1 = 7)
#   bitstream @ offset 12 = 0x40000000 LE -> first two bits 0,1
# Decodes to 'A' (bit 0 -> left leaf) then 'B' (bit 1 -> right leaf). Under the
# old byte-count formula the root child_base is 5, landing on padding, so this
# isolates the word-multiply fix.
HUFF8_BLOB = _l5_huffman_blob(
    3, 2,
    bytes([3, 0xC2, 0, 0, 0, 0, 0x41, 0x42, 0, 0, 0, 0])
    + bytes([0x00, 0x00, 0x00, 0x40]))
HUFF8_EXPECT = b"AB"

# Fixture 2: 4-bit Huffman, two-level tree with an internal node at odd offset 3.
#   [0]=2   tree-size byte -> (2+1)*2 = 6 tree bytes
#   [1]=0x80 root: left leaf(P) | right internal(N1) | rel=0
#   [2]=0x01 'P' nibble  (root child_base = 2)
#   [3]=0xC0 N1: left leaf(Q) | right leaf(R) | rel=0
#   [4]=0x02 'Q' nibble  (N1 child_base = (3&~1)+0+2 = 4)
#   [5]=0x03 'R' nibble
#   bitstream @ offset 8 = 0x40000000 LE -> bits 0,1,0
# Codes P=0, Q=10, R=11. First nibble P(0x1) then Q(0x2) assemble to output byte
# (hi<<4)|lo = 0x21. Under the old formula N1's child_base is 5, landing on R,
# so this isolates the alignment-base fix.
HUFF4_BLOB = _l5_huffman_blob(
    2, 1,
    bytes([2, 0x80, 0x01, 0xC0, 0x02, 0x03, 0, 0])
    + bytes([0x00, 0x00, 0x00, 0x40]))
HUFF4_EXPECT = b"\x21"


def test_huffman8_root_word_offset():
    assert decompress_l5(HUFF8_BLOB) == HUFF8_EXPECT


def test_huffman4_odd_node_alignment():
    assert decompress_l5(HUFF4_BLOB) == HUFF4_EXPECT


# ── Independent cross-check against a from-GBATEK-spec decoder ────────────────
#
# The two fixtures above are canonical trees this project authored. To rule out
# a shared blind spot (the same treatment CRILAYLA got with two independent
# ports), decode them with a Huffman decompressor written fresh from the GBATEK
# BIOS HuffUnComp spec, WITHOUT reading _v1_level5.py. ndspy has no Huffman
# codec, so this is the from-spec option the task allows. It is deliberately
# structured differently from the shipped decoder: a stateless index-based bit
# reader `bit_at(k)` and a fresh node walk, rather than the shipped stateful
# read_bit / decode_symbol.
#
# GBATEK reference (BIOS HuffUnComp): the tree starts with a size byte; the root
# node is the byte right after it. For a node at absolute offset `pos`,
#   next = (pos & ~1) + (node & 0x3F) * 2 + 2
# with the left child at `next` (a data node when bit 0x80 is set) and the right
# child at `next + 1` (a data node when bit 0x40 is set). The bitstream is a run
# of 32-bit little-endian words consumed most-significant-bit first. 4-bit mode
# emits two symbols per output byte, first symbol in the low nibble.

def _gbatek_huffman_decode(blob: bytes) -> bytes:
    val = int.from_bytes(blob[0:4], "little")
    method = val & 7
    bit_width = 4 if method == 2 else 8  # L5 method 2 = 4-bit, 3 = 8-bit
    out_size = val >> 3
    tree = blob[4:]                      # tree[0] = size byte, tree[1] = root

    tree_size = tree[0]
    bit_start = (1 + (tree_size + 1) * 2 + 3) & ~3

    def bit_at(k: int) -> int:
        base = bit_start + (k >> 5) * 4
        word = int.from_bytes(tree[base:base + 4], "little")
        return (word >> (31 - (k & 31))) & 1

    counter = [0]

    def decode_symbol() -> int:
        pos = 1  # root node
        while True:
            node = tree[pos]
            nxt = (pos & ~1) + (node & 0x3F) * 2 + 2
            b = bit_at(counter[0])
            counter[0] += 1
            if b == 0:
                if node & 0x80:
                    return tree[nxt]
                pos = nxt
            else:
                if node & 0x40:
                    return tree[nxt + 1]
                pos = nxt + 1

    out = bytearray()
    while len(out) < out_size:
        if bit_width == 8:
            out.append(decode_symbol() & 0xFF)
        else:
            lo = decode_symbol() & 0xF
            hi = decode_symbol() & 0xF
            out.append((hi << 4) | lo)
    return bytes(out[:out_size])


def test_huffman_fixtures_match_independent_gbatek_decoder():
    """Both fixtures decode identically under the shipped decoder and a fresh
    from-GBATEK-spec decoder, and both equal the hand-derived expected output."""
    for blob, expect in ((HUFF8_BLOB, HUFF8_EXPECT), (HUFF4_BLOB, HUFF4_EXPECT)):
        shipped = decompress_l5(blob)
        independent = _gbatek_huffman_decode(blob)
        assert independent == expect
        assert shipped == independent
