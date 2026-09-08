"""Pure-Python port of Google CityHash64.

Byte-exact match for the C++ reference implementation; vendored so Forge
can compute Azahar's runtime texture lookup hash without forcing users
to install the `cityhash` PyPI package (which has no prebuilt wheel for
Python 3.14 and would otherwise require an MSVC toolchain).

The C extension is preferred when available -- this module is the
fallback. Throughput is ~100x slower than the native version, which is
still microseconds per texture and invisible at extract time.

Reference: https://github.com/google/cityhash (cityhash.cc, version 1.1.1)

Smoke test:
    CityHash64(b"") == 0x9AE16A3B2F90404F  (== _K2)
"""

from __future__ import annotations

import struct

__all__ = ["CityHash64"]


_MASK64 = (1 << 64) - 1
_MASK32 = (1 << 32) - 1

_K0 = 0xC3A5C85C97CB3127
_K1 = 0xB492B66FBE98F273
_K2 = 0x9AE16A3B2F90404F
_MUL = 0x9DDFEA08EB382D69


def _fetch64(buf: bytes, off: int) -> int:
    return struct.unpack_from("<Q", buf, off)[0]


def _fetch32(buf: bytes, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


def _rotate(val: int, shift: int) -> int:
    val &= _MASK64
    return ((val >> shift) | (val << (64 - shift))) & _MASK64


def _shift_mix(val: int) -> int:
    val &= _MASK64
    return (val ^ (val >> 47)) & _MASK64


def _hash_len_16(u: int, v: int, mul: int = _MUL) -> int:
    a = ((u ^ v) * mul) & _MASK64
    a ^= a >> 47
    a &= _MASK64
    b = ((v ^ a) * mul) & _MASK64
    b ^= b >> 47
    b &= _MASK64
    b = (b * mul) & _MASK64
    return b


def _hash_len_0_to_16(s: bytes, length: int) -> int:
    if length >= 8:
        mul = (_K2 + length * 2) & _MASK64
        a = (_fetch64(s, 0) + _K2) & _MASK64
        b = _fetch64(s, length - 8)
        c = (_rotate(b, 37) * mul + a) & _MASK64
        d = ((_rotate(a, 25) + b) * mul) & _MASK64
        return _hash_len_16(c, d, mul)
    if length >= 4:
        mul = (_K2 + length * 2) & _MASK64
        a = _fetch32(s, 0)
        return _hash_len_16(
            (length + (a << 3)) & _MASK64,
            _fetch32(s, length - 4),
            mul,
        )
    if length > 0:
        a = s[0]
        b = s[length >> 1]
        c = s[length - 1]
        y = (a + (b << 8)) & _MASK32
        z = (length + (c << 2)) & _MASK32
        return (_shift_mix(((y * _K2) ^ (z * _K0)) & _MASK64) * _K2) & _MASK64
    return _K2


def _hash_len_17_to_32(s: bytes, length: int) -> int:
    mul = (_K2 + length * 2) & _MASK64
    a = (_fetch64(s, 0) * _K1) & _MASK64
    b = _fetch64(s, 8)
    c = (_fetch64(s, length - 8) * mul) & _MASK64
    d = (_fetch64(s, length - 16) * _K2) & _MASK64
    return _hash_len_16(
        (_rotate((a + b) & _MASK64, 43) + _rotate(c, 30) + d) & _MASK64,
        (a + _rotate((b + _K2) & _MASK64, 18) + c) & _MASK64,
        mul,
    )


def _weak_hash_len_32_with_seeds_raw(
    w: int, x: int, y: int, z: int, a: int, b: int
) -> tuple[int, int]:
    a = (a + w) & _MASK64
    b = _rotate((b + a + z) & _MASK64, 21)
    c = a
    a = (a + x) & _MASK64
    a = (a + y) & _MASK64
    b = (b + _rotate(a, 44)) & _MASK64
    return ((a + z) & _MASK64, (b + c) & _MASK64)


def _weak_hash_len_32_with_seeds(s: bytes, off: int, a: int, b: int) -> tuple[int, int]:
    return _weak_hash_len_32_with_seeds_raw(
        _fetch64(s, off),
        _fetch64(s, off + 8),
        _fetch64(s, off + 16),
        _fetch64(s, off + 24),
        a,
        b,
    )


def _hash_len_33_to_64(s: bytes, length: int) -> int:
    mul = (_K2 + length * 2) & _MASK64
    a = (_fetch64(s, 0) * _K2) & _MASK64
    b = _fetch64(s, 8)
    c = (_fetch64(s, length - 24)) & _MASK64
    d = _fetch64(s, length - 32)
    e = (_fetch64(s, 16) * _K2) & _MASK64
    f = (_fetch64(s, 24) * 9) & _MASK64
    g = _fetch64(s, length - 8)
    h = (_fetch64(s, length - 16) * mul) & _MASK64
    u = (_rotate((a + g) & _MASK64, 43) + ((_rotate(b, 30) + c) * 9 & _MASK64)) & _MASK64
    v = (((a + g) ^ d) + f + 1) & _MASK64
    w = (_bswap64(((u + v) * mul) & _MASK64) + h) & _MASK64
    x = (_rotate((e + f) & _MASK64, 42) + c) & _MASK64
    y = ((_bswap64(((v + w) * mul) & _MASK64) + g) * mul) & _MASK64
    z = (e + f + c) & _MASK64
    a2 = (_bswap64(((x + z) * mul + y) & _MASK64) + b) & _MASK64
    b2 = (_shift_mix(((z + a2) * mul + d + h) & _MASK64) * mul) & _MASK64
    return (b2 + x) & _MASK64


def _bswap64(val: int) -> int:
    val &= _MASK64
    return int.from_bytes(val.to_bytes(8, "little"), "big")


def CityHash64(data: bytes) -> int:
    """64-bit CityHash of the given bytes."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("CityHash64 expects bytes-like input")
    if isinstance(data, memoryview):
        data = bytes(data)
    elif isinstance(data, bytearray):
        data = bytes(data)

    length = len(data)
    if length <= 32:
        if length <= 16:
            return _hash_len_0_to_16(data, length)
        return _hash_len_17_to_32(data, length)
    if length <= 64:
        return _hash_len_33_to_64(data, length)

    # For strings longer than 64 bytes, use the main loop.
    x = _fetch64(data, length - 40)
    y = (_fetch64(data, length - 16) + _fetch64(data, length - 56)) & _MASK64
    z = _hash_len_16(
        (_fetch64(data, length - 48) + length) & _MASK64,
        _fetch64(data, length - 24),
    )
    v = _weak_hash_len_32_with_seeds(data, length - 64, length, z)
    w = _weak_hash_len_32_with_seeds(data, length - 32, (y + _K1) & _MASK64, x)
    x = (x * _K1 + _fetch64(data, 0)) & _MASK64

    # Decrease length to a multiple of 64, then iterate in 64-byte chunks.
    remaining = (length - 1) & ~63
    pos = 0
    while remaining > 0:
        x = (_rotate((x + y + v[0] + _fetch64(data, pos + 8)) & _MASK64, 37) * _K1) & _MASK64
        y = (_rotate((y + v[1] + _fetch64(data, pos + 48)) & _MASK64, 42) * _K1) & _MASK64
        x ^= w[1]
        x &= _MASK64
        y = (y + v[0] + _fetch64(data, pos + 40)) & _MASK64
        z = (_rotate((z + w[0]) & _MASK64, 33) * _K1) & _MASK64
        v = _weak_hash_len_32_with_seeds(data, pos, (v[1] * _K1) & _MASK64, (x + w[0]) & _MASK64)
        w = _weak_hash_len_32_with_seeds(
            data, pos + 32, (z + w[1]) & _MASK64, (y + _fetch64(data, pos + 16)) & _MASK64
        )
        # Swap z and x
        x, z = z, x
        pos += 64
        remaining -= 64

    return _hash_len_16(
        (_hash_len_16(v[0], w[0]) + (_shift_mix(y) * _K1 & _MASK64) + z) & _MASK64,
        (_hash_len_16(v[1], w[1]) + x) & _MASK64,
    )


if __name__ == "__main__":
    # Inline smoke test: CityHash64 of the empty string is the constant K2.
    assert CityHash64(b"") == 0x9AE16A3B2F90404F, "empty-string hash mismatch"
    print("OK")
