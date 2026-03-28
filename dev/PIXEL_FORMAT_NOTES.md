# Pixel Format Notes

Technical details on PICA200 GPU texture formats and decoder implementation.

## Morton Order (Z-order) De-tiling

All PICA200 textures are stored in Morton order (Z-order curve) within 8x8 pixel tiles.
Tiles are laid out left-to-right, top-to-bottom across the texture.

The Morton index for pixel (x, y) within an 8x8 tile interleaves the bits of x and y:
```
morton(x, y) = (y0 << 1 | x0) | (y1 << 3 | x1 << 2) | (y2 << 5 | x2 << 4)
```

Pre-computed table (MORTON_TABLE[y*8+x]):
```
 0  1  4  5 16 17 20 21
 2  3  6  7 18 19 22 23
 8  9 12 13 24 25 28 29
10 11 14 15 26 27 30 31
32 33 36 37 48 49 52 53
34 35 38 39 50 51 54 55
40 41 44 45 56 57 60 61
42 43 46 47 58 59 62 63
```

### Validation
- Pixel (0,0) maps to morton index 0
- Pixel (1,0) maps to morton index 1
- Pixel (0,1) maps to morton index 2
- Pixel (7,7) maps to morton index 63

## ETC1 Block Decoding

ETC1 blocks are 8 bytes, stored as little-endian u64 on 3DS (NOT big-endian as in the Khronos spec).

Block layout after reading as LE u64:
- Upper 32 bits (word1): color data, table indices, diff/flip flags
- Lower 32 bits (word2): pixel index bits (MSB and LSB)

### Sub-block assignment
- flip=0: vertical split (left 2 cols = sub0, right 2 cols = sub1)
- flip=1: horizontal split (top 2 rows = sub0, bottom 2 rows = sub1)

### Pixel indices
For each pixel at (px, py), bit position = px*4 + py:
- MSB = word2 bit (pos + 16)
- LSB = word2 bit (pos)

Index mapping: 0 = +small, 1 = +large, 2 = -small, 3 = -large

### ETC1 Morton tiling
ETC1 4x4 blocks are grouped into 2x2 macro-tiles (8x8 pixels).
Within each macro-tile, blocks are in Z-order: (0,0), (1,0), (0,1), (1,1).
Macro-tiles are laid out left-to-right, top-to-bottom.

### ETC1A4
16 bytes per block: first 8 bytes = alpha (4-bit per pixel, column-major LE), next 8 = ETC1 color.

## RGBA8 Byte Order

PICA200 stores RGBA8 as: byte0=A, byte1=B, byte2=G, byte3=R (ABGR).
Decoder reverses to standard RGBA.

## RGB8 Byte Order

Stored as: byte0=B, byte1=G, byte2=R (BGR). Decoder reverses to RGB.

## 16-bit Formats

All 16-bit formats (RGB565, RGBA5551, RGBA4, LA8, HILO8) are stored as little-endian u16.

### RGB565
Bits: [15:11]=R5, [10:5]=G6, [4:0]=B5

### RGBA5551
Bits: [15:11]=R5, [10:6]=G5, [5:1]=B5, [0]=A1

### RGBA4
Bits: [15:12]=R4, [11:8]=G4, [7:4]=B4, [3:0]=A4

## 4-bit Formats

### LA4
Single byte: high nibble = luminance, low nibble = alpha.
Both expanded: val8 = (nibble << 4) | nibble.

### L4, A4
Two pixels per byte. Even pixel = low nibble, odd pixel = high nibble.

## Alternate Format IDs

Some game engines use non-standard format IDs that map to standard PICA200 formats:
- 0x14 -> RGBA8 (Capcom MT Framework)
- 0x19 -> ETC1 (Atlus)
- 0x1A -> ETC1A4 (Atlus)

These are resolved transparently in the decoder via FORMAT_ALIASES.
