"""Validate the Morton de-tiling table against its mathematical definition.

The table interleaves bits of x and y to produce a Z-order curve. We
double-check by computing the morton index for every (x,y) in 0..7
using bit-arithmetic and asserting it matches the table value.
"""

from tex_forge.textures.morton import (
    INV_MORTON_X,
    INV_MORTON_Y,
    MORTON_TABLE,
    etc1_block_order,
    scatter_map,
)


def _expected_morton(x: int, y: int) -> int:
    """morton(x,y) = bit-interleave: y0 x0 y1 x1 y2 x2."""
    out = 0
    for i in range(3):  # 8x8 tile -> 3 bits each
        out |= ((x >> i) & 1) << (2 * i)
        out |= ((y >> i) & 1) << (2 * i + 1)
    return out


def test_morton_table_values():
    for y in range(8):
        for x in range(8):
            assert MORTON_TABLE[y * 8 + x] == _expected_morton(x, y), (x, y)


def test_inv_morton_consistent():
    """INV_MORTON_X[i], INV_MORTON_Y[i] should round-trip via MORTON_TABLE."""
    for i in range(64):
        x = int(INV_MORTON_X[i])
        y = int(INV_MORTON_Y[i])
        assert MORTON_TABLE[y * 8 + x] == i


def test_scatter_map_8x8():
    dst_y, dst_x, src_idx = scatter_map(8, 8)
    # 8x8 = 1 tile = 64 pixels, all valid.
    assert len(src_idx) == 64
    assert dst_y.shape == (64,)
    assert set(zip(dst_y.tolist(), dst_x.tolist())) == {(y, x) for y in range(8) for x in range(8)}


def test_scatter_map_drops_padding_pixels():
    """A 5x5 texture should yield 25 (not 64) entries -- padding dropped."""
    dst_y, dst_x, src_idx = scatter_map(5, 5)
    assert len(src_idx) == 25
    assert dst_y.max() < 5 and dst_x.max() < 5


def test_etc1_block_order_8x8():
    bx, by = etc1_block_order(8, 8)
    # 8x8 = one 2x2 macro of 4 blocks -> 4 entries
    assert len(bx) == 4
    assert sorted(zip(bx.tolist(), by.tolist())) == [(0, 0), (0, 1), (1, 0), (1, 1)]
