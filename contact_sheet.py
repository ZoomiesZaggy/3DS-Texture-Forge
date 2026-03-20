"""Contact sheet generation for visual proof of extracted textures."""

import os
import logging
from typing import List, Dict, Any
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Thumbnail size and layout
THUMB_SIZE = 128
LABEL_HEIGHT = 36
CELL_PADDING = 4
DEFAULT_COLUMNS = 6
BG_COLOR = (32, 32, 32)
LABEL_BG = (24, 24, 24)
LABEL_COLOR = (200, 200, 200)
SUBLABEL_COLOR = (140, 140, 140)


def generate_contact_sheet(
    texture_records: List[Dict[str, Any]],
    output_dir: str,
    filename: str = "contact_sheet.png",
    columns: int = DEFAULT_COLUMNS,
    max_textures: int = 600,
) -> str:
    """
    Generate a contact sheet PNG from extracted texture records.

    Each record must have 'decoded_png_path' (absolute or relative to output_dir),
    'width', 'height', 'detected_format', and optionally 'source_file_path'.

    Returns the path to the generated contact sheet, or "" on failure.
    """
    # Filter to records that have a valid decoded PNG
    valid = []
    for rec in texture_records:
        png_path = rec.get("decoded_png_path", "")
        if not png_path:
            continue
        abs_path = png_path if os.path.isabs(png_path) else os.path.join(output_dir, png_path)
        if os.path.isfile(abs_path):
            valid.append((rec, abs_path))

    if not valid:
        logger.warning("No valid textures for contact sheet")
        return ""

    if len(valid) > max_textures:
        logger.info(f"Limiting contact sheet to first {max_textures} of {len(valid)} textures")
        valid = valid[:max_textures]

    count = len(valid)
    rows = (count + columns - 1) // columns
    cell_w = THUMB_SIZE + CELL_PADDING * 2
    cell_h = THUMB_SIZE + LABEL_HEIGHT + CELL_PADDING * 2
    sheet_w = cell_w * columns + CELL_PADDING
    sheet_h = cell_h * rows + CELL_PADDING

    sheet = Image.new("RGB", (sheet_w, sheet_h), BG_COLOR)
    draw = ImageDraw.Draw(sheet)

    # Try to get a small font; fall back to default
    try:
        font = ImageFont.truetype("arial.ttf", 10)
        font_small = ImageFont.truetype("arial.ttf", 9)
    except Exception:
        font = ImageFont.load_default()
        font_small = font

    for idx, (rec, abs_path) in enumerate(valid):
        col = idx % columns
        row = idx // columns
        x0 = CELL_PADDING + col * cell_w
        y0 = CELL_PADDING + row * cell_h

        # Load and thumbnail
        try:
            img = Image.open(abs_path)
            img.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
            # Center the thumbnail in the cell
            tx = x0 + (THUMB_SIZE - img.width) // 2 + CELL_PADDING
            ty = y0 + (THUMB_SIZE - img.height) // 2 + CELL_PADDING
            # Handle RGBA by compositing onto cell bg
            if img.mode == "RGBA":
                bg = Image.new("RGBA", img.size, BG_COLOR + (255,))
                bg.paste(img, (0, 0), img)
                img = bg.convert("RGB")
            sheet.paste(img, (tx, ty))
        except Exception as e:
            logger.debug(f"Could not load thumbnail for {abs_path}: {e}")
            # Draw placeholder
            draw.rectangle([x0 + CELL_PADDING, y0 + CELL_PADDING,
                            x0 + THUMB_SIZE + CELL_PADDING, y0 + THUMB_SIZE + CELL_PADDING],
                           fill=(60, 20, 20))

        # Label area
        label_y = y0 + THUMB_SIZE + CELL_PADDING * 2
        draw.rectangle([x0, label_y, x0 + cell_w, label_y + LABEL_HEIGHT], fill=LABEL_BG)

        # Filename label (truncated)
        src = rec.get("source_file_path", "")
        if src:
            label = os.path.basename(src)
        else:
            label = os.path.basename(abs_path)
        if len(label) > 20:
            label = label[:17] + "..."
        draw.text((x0 + 3, label_y + 2), label, fill=LABEL_COLOR, font=font)

        # Dimensions + format sublabel
        w = rec.get("width", "?")
        h = rec.get("height", "?")
        fmt = rec.get("detected_format", "?")
        sublabel = f"{w}x{h} {fmt}"
        draw.text((x0 + 3, label_y + 16), sublabel, fill=SUBLABEL_COLOR, font=font_small)

    out_path = os.path.join(output_dir, filename)
    os.makedirs(output_dir, exist_ok=True)
    sheet.save(out_path, "PNG")
    logger.info(f"Contact sheet saved: {out_path} ({count} textures, {rows}x{columns} grid)")
    return out_path
