"""CRILAYLA round-trip on a hand-built minimal stream.

The codec reads the body BACKWARDS from the last byte. Each iteration of
the outer loop reads one flag byte and then (up to) 8 literal/backref
bytes BEFORE that flag byte. Because we work backward, the ORDER of
literal bytes within a group matches the output order: the byte at the
LOWEST body address writes to the LOWEST output position.

For the test we build all-literal streams (no backrefs):

    body = [partial leading chunk][flag=0x00]
           [chunk of 8 from output][flag=0x00]
           [chunk of 8 from output][flag=0x00] ...

`partial leading chunk` is empty when len(output) % 8 == 0; otherwise it
holds the leftmost `len(output) % 8` bytes so the splits land cleanly.
"""

import struct

from tex_forge.compression.crilayla import _decompress, decompress_crilayla


def _build_stream(prefix: bytes, decompressed: bytes) -> bytes:
    n = len(decompressed)
    body = bytearray()
    pos = 0
    leftover = n % 8
    if leftover:
        body.extend(decompressed[0:leftover])
        body.append(0x00)
        pos = leftover
    while pos < n:
        body.extend(decompressed[pos:pos + 8])
        body.append(0x00)
        pos += 8
    header = b"CRILAYLA" + struct.pack("<I", n) + struct.pack("<I", len(body))
    return header + bytes(body) + prefix


def test_decompress_8_byte_payload():
    payload = b"abcdefgh"  # exact multiple of 8 -- no leading partial
    blob = _build_stream(b"", payload)
    assert _decompress(blob) == payload


def test_decompress_partial_first_group():
    payload = b"HelloWorld"  # 10 bytes -- 2-byte leading partial + one 8-byte group
    blob = _build_stream(b"", payload)
    assert _decompress(blob) == payload


def test_decompress_with_prefix():
    prefix = b"PREFIX_"
    payload = b"BodyData"
    blob = _build_stream(prefix, payload)
    assert _decompress(blob) == prefix + payload


def test_detect_rejects_non_crilayla():
    assert _decompress(b"NOPE" + bytes(50)) is None


def test_public_alias_matches_private():
    blob = _build_stream(b"", b"abcdefgh")
    assert decompress_crilayla(blob) == _decompress(blob)
