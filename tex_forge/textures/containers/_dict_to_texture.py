"""Helper: convert the dict-of-fields output emitted by v1 texture parsers
into a Texture dataclass.

The v1 parsers return List[Dict[str, Any]] where each dict has keys:

    name, width, height, format, mip_count
    data_offset, data_size  (slice into the source blob to extract pixels)
    OR
    data                    (already extracted pixel bytes)

    crop_width, crop_height (optional: for BFLIM/BCLIM with non-power-of-two
                             visible region inside a power-of-2 atlas)

We slice when needed and return Texture instances.
"""

from __future__ import annotations

from typing import Iterable, Iterator

from tex_forge.core.types import Texture


def dict_to_texture(d: dict, source_data: bytes, source_path: str, *,
                    parser: str, confidence: str = "high") -> Texture:
    """Convert one v1 dict to a Texture, slicing source_data when needed."""
    pixel_data = d.get("data")
    if pixel_data is None:
        offset = int(d.get("data_offset", 0))
        size = int(d.get("data_size", 0))
        if size > 0 and offset + size <= len(source_data):
            pixel_data = bytes(source_data[offset:offset + size])
        elif offset < len(source_data):
            pixel_data = bytes(source_data[offset:])
        else:
            pixel_data = b""
    else:
        pixel_data = bytes(pixel_data)

    notes = d.get("capcom_parse_notes") or []
    if isinstance(notes, str):
        notes = [notes]

    return Texture(
        name=str(d.get("name", "")),
        width=int(d.get("width", 0)),
        height=int(d.get("height", 0)),
        format=int(d.get("format", 0)),
        data=pixel_data,
        mip_count=int(d.get("mip_count", 1)),
        crop_width=int(d.get("crop_width", 0)),
        crop_height=int(d.get("crop_height", 0)),
        parser_used=parser,
        confidence=str(d.get("confidence", confidence)),
        source_file=source_path,
        notes=list(notes),
        extra={k: v for k, v in d.items() if k not in {
            "name", "width", "height", "format", "data",
            "data_offset", "data_size", "mip_count",
            "crop_width", "crop_height", "confidence", "parser_used",
            "source_file", "capcom_parse_notes",
        }},
    )


def dicts_to_textures(dicts: Iterable[dict], source_data: bytes, source_path: str,
                      *, parser: str, confidence: str = "high") -> Iterator[Texture]:
    for d in dicts:
        yield dict_to_texture(d, source_data, source_path,
                              parser=parser, confidence=confidence)
