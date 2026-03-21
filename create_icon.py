"""Generate 3DS Texture Forge icon."""
from PIL import Image, ImageDraw


def draw_icon(size):
    """Draw the cartridge portal icon at the given size."""
    img = Image.new('RGBA', (size, size), (8, 8, 26, 255))
    d = ImageDraw.Draw(img)

    # Scale factor relative to 256
    s = size / 256

    # Cartridge body
    body_x = int(48 * s)
    body_y = int(22 * s)
    body_w = int(160 * s)
    body_h = int(210 * s)
    body_r = max(int(10 * s), 1)
    d.rounded_rectangle([body_x, body_y, body_x + body_w, body_y + body_h],
                         radius=body_r, fill=(26, 26, 50), outline=(58, 58, 94), width=max(int(1.5*s), 1))

    # Top tab
    tab_x = int(80 * s)
    tab_y = int(10 * s)
    tab_w = int(96 * s)
    tab_h = int(24 * s)
    tab_r = max(int(5 * s), 1)
    d.rounded_rectangle([tab_x, tab_y, tab_x + tab_w, tab_y + tab_h],
                        radius=tab_r, fill=(26, 26, 50), outline=(58, 58, 94), width=max(int(1.5*s), 1))
    # Cover the seam between tab and body
    d.rectangle([tab_x, int(24*s), tab_x + tab_w, int(34*s)], fill=(26, 26, 50))

    # Label area
    if size >= 32:
        lbl_x = int(62 * s)
        lbl_y = int(40 * s)
        lbl_w = int(132 * s)
        lbl_h = int(28 * s)
        d.rounded_rectangle([lbl_x, lbl_y, lbl_x + lbl_w, lbl_y + lbl_h],
                            radius=max(int(3*s), 1), fill=(34, 34, 68))

    # Portal window
    pw_x = int(62 * s)
    pw_y = int(76 * s)
    pw_w = int(132 * s)
    pw_h = int(136 * s)
    pw_r = max(int(5 * s), 1)
    d.rounded_rectangle([pw_x, pw_y, pw_x + pw_w, pw_y + pw_h],
                        radius=pw_r, fill=(2, 2, 16))
    # Glow border
    d.rounded_rectangle([pw_x, pw_y, pw_x + pw_w, pw_y + pw_h],
                        radius=pw_r, fill=None, outline=(85, 72, 160, 80), width=max(int(s), 1))

    # Inner pixel world
    ix = pw_x + max(int(2*s), 1)
    iw = pw_w - max(int(4*s), 2)

    # Define layers: (y_offset fraction, height fraction, colors)
    layers = [
        (0.00, 0.12, [(26, 58, 110)]),                                          # Sky
        (0.12, 0.10, None),                                                      # Mountains (special)
        (0.22, 0.12, [(29, 158, 117), (15, 110, 86), (93, 202, 165)]),          # Grass
        (0.34, 0.10, [(133, 79, 11), (99, 56, 6)]),                             # Dirt
        (0.44, 0.10, [(216, 90, 48), (232, 89, 60)]),                           # Warm stone
        (0.54, 0.10, [(240, 149, 149), (226, 75, 74)]),                         # Lava
        (0.64, 0.12, [(212, 83, 126), (127, 119, 221), (83, 74, 183)]),        # Crystals
        (0.76, 0.12, [(38, 33, 92), (60, 52, 137)]),                           # Deep
        (0.88, 0.12, [(23, 20, 40)]),                                           # Bedrock
    ]

    for y_frac, h_frac, colors in layers:
        if colors is None:
            continue  # Mountains handled separately
        ly = pw_y + int(y_frac * pw_h)
        lh = max(int(h_frac * pw_h), 1)
        num_colors = len(colors)
        for i, color in enumerate(colors):
            bx = ix + (i * iw // num_colors)
            bw = iw // num_colors if i < num_colors - 1 else (ix + iw - bx)
            d.rectangle([bx, ly, bx + bw, ly + lh], fill=color)

    # Mountains
    if size >= 24:
        mt_y = pw_y + int(0.12 * pw_h)
        mt_h = int(0.10 * pw_h)
        mt_base = mt_y + mt_h
        peaks = [
            (ix + iw * 1//6, mt_y, (60, 52, 137)),
            (ix + iw * 3//6, mt_y - int(2*s), (83, 74, 183)),
            (ix + iw * 5//6, mt_y + int(1*s), (60, 52, 137)),
        ]
        for px, py, color in peaks:
            spread = int(iw * 0.15)
            d.polygon([(px - spread, mt_base), (px, py), (px + spread, mt_base)], fill=color)

    # Contact pins at bottom
    if size >= 48:
        pin_y = body_y + body_h - int(6 * s)
        pin_h = int(10 * s)
        num_pins = 7 if size >= 128 else (5 if size >= 64 else 3)
        pin_w = max(int(8 * s), 2)
        total_pin_width = num_pins * pin_w + (num_pins - 1) * max(int(6*s), 2)
        pin_start = body_x + (body_w - total_pin_width) // 2
        for i in range(num_pins):
            px = pin_start + i * (pin_w + max(int(6*s), 2))
            d.rectangle([px, pin_y, px + pin_w, pin_y + pin_h], fill=(242, 166, 35, 76))

    return img


# Generate all sizes
sizes = [256, 128, 64, 48, 32, 16]
images = [draw_icon(s) for s in sizes]

# Save as .ico
images[0].save('icon.ico', format='ICO', sizes=[(s, s) for s in sizes],
                append_images=images[1:])

# Also save the 256px as PNG for reference
images[0].save('icon_256.png')

print(f"Created icon.ico with sizes: {sizes}")
print(f"Created icon_256.png for reference")

# Verify
ico = Image.open('icon.ico')
print(f"ICO sizes: {ico.info.get('sizes', 'unknown')}")
