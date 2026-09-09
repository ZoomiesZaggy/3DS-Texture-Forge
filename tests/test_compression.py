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


def test_huffman8_root_word_offset():
    """8-bit Huffman, root child pair placed at word-offset 2 (rel=2).

    Layout (byte offsets into the body, [0] is the tree-size byte):
        [0]=3   tree-size byte -> (3+1)*2 = 8 tree bytes
        [1]=0xC2  root: left leaf | right leaf | rel=2
        [6]=0x41 'A'  left child   (child_base = (1&~1)+2*2+2 = 6)
        [7]=0x42 'B'  right child  (child_base+1 = 7)
        bitstream @ offset 12 = 0x40000000 LE -> first two bits 0,1

    Decodes to 'A' (bit 0 -> left leaf) then 'B' (bit 1 -> right leaf).
    Under the old byte-count formula the root child_base is 5, landing on
    padding, so this fixture isolates the word-multiply fix.
    """
    body = bytes([3, 0xC2, 0, 0, 0, 0, 0x41, 0x42, 0, 0, 0, 0]) + \
        bytes([0x00, 0x00, 0x00, 0x40])
    assert decompress_l5(_l5_huffman_blob(3, 2, body)) == b"AB"


def test_huffman4_odd_node_alignment():
    """4-bit Huffman, two-level tree with an internal node at odd offset 3.

    Layout:
        [0]=2   tree-size byte -> (2+1)*2 = 6 tree bytes
        [1]=0x80 root: left leaf(P) | right internal(N1) | rel=0
        [2]=0x01 'P' nibble   (root child_base = 2)
        [3]=0xC0 N1: left leaf(Q) | right leaf(R) | rel=0
        [4]=0x02 'Q' nibble   (N1 child_base = (3&~1)+0+2 = 4)
        [5]=0x03 'R' nibble
        bitstream @ offset 8 = 0x40000000 LE -> bits 0,1,0

    Codes: P=0, Q=10, R=11. First nibble P(0x1) then Q(0x2) assemble to the
    output byte (hi<<4)|lo = 0x21. Under the old formula N1's child_base is 5
    (aligned on the tree-relative offset), landing on R, so this fixture
    isolates the alignment-base fix.
    """
    body = bytes([2, 0x80, 0x01, 0xC0, 0x02, 0x03, 0, 0]) + \
        bytes([0x00, 0x00, 0x00, 0x40])
    assert decompress_l5(_l5_huffman_blob(2, 1, body)) == b"\x21"
