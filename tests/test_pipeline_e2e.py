"""End-to-end smoke test that does NOT need a real ROM.

We can't ship 3DS game data in tests, so we exercise as much of the pipeline
as possible against synthetic blobs and minimal RomFS structure.

What's covered:
  * Texture plugin registry actually decodes a real 8x8 RGBA8 BCH-like blob.
  * Output writers produce valid JSON.
  * Quality report runs and emits both JSON and TXT.
  * Build pack creates a load_pack/load/textures/<title>/ tree.
"""

import json
import os
import tempfile

import numpy as np

from tex_forge.output import (
    build_pack,
    make_record,
    save_png,
    write_failures,
    write_manifest,
    write_quality_report,
    write_summary,
)
from tex_forge.quality import compute_quality_metrics
from tex_forge.textures.decoder import decode
from tex_forge.textures.formats import PicaFormat


def test_decoder_then_save_png_then_quality():
    """Full per-texture pipeline: decode -> save_png -> quality_metrics."""
    pix = bytearray()
    for i in range(64):
        pix.extend([0xFF, 0x10, 0x20, 0x30])  # opaque-ish, varied
    rgba = decode(bytes(pix), 8, 8, int(PicaFormat.RGBA8))
    assert rgba is not None and rgba.shape == (8, 8, 4)

    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "out.png")
        assert save_png(rgba, path)
        assert os.path.getsize(path) > 0

    qm = compute_quality_metrics(rgba, pica_format=int(PicaFormat.RGBA8))
    assert "is_suspicious" in qm
    assert "flags" in qm


def test_manifest_writers_produce_valid_json():
    with tempfile.TemporaryDirectory() as td:
        rec = make_record(
            tex_id="tex_0001", detected_format="RGBA8", width=64, height=64,
            parser_used="cgfx", decoded_png_path="textures/0001.png",
            content_hash="abc123",
        )
        write_manifest(td, [rec], rom_file="game.3ds",
                       title_id="0004000000055E00",
                       game_title="Pokemon Y", summary={"foo": 1})
        write_failures(td, [{"id": "tex_0002", "reason": "decoder returned None"}])
        write_summary(td, {"x": "y"})

        with open(os.path.join(td, "manifest.json")) as f:
            m = json.load(f)
        assert m["schema_version"] == 2
        assert m["texture_count"] == 1
        assert m["textures"][0]["id"] == "tex_0001"

        with open(os.path.join(td, "failures.json")) as f:
            ff = json.load(f)
        assert ff["count"] == 1


def test_quality_report_writer():
    rec_good = make_record(tex_id="tex_a", detected_format="RGBA8",
                           width=64, height=64, parser_used="cgfx",
                           quality={"is_suspicious": False, "flags": []})
    rec_bad = make_record(tex_id="tex_b", detected_format="RGBA8",
                          width=64, height=64, parser_used="cgfx",
                          quality={"is_suspicious": True,
                                   "flags": ["SUSPICIOUS_SOLID"]})
    with tempfile.TemporaryDirectory() as td:
        report = write_quality_report(
            [rec_good, rec_bad],
            output_dir=td, game_name="TestGame", rom_file="x.3ds",
        )
        assert report["total_textures"] == 2
        assert report["valid"] == 1
        assert report["suspicious"] == 1
        assert os.path.isfile(os.path.join(td, "quality_report.json"))
        assert os.path.isfile(os.path.join(td, "quality_report.txt"))


def test_build_pack_staging_mode():
    with tempfile.TemporaryDirectory() as td:
        # Drop a synthetic PNG in textures/ so pack_builder has something to copy.
        tex_dir = os.path.join(td, "textures")
        os.makedirs(tex_dir, exist_ok=True)
        png_path = os.path.join(tex_dir, "test.png")
        rgba = np.full((8, 8, 4), 64, dtype=np.uint8)
        rgba[..., 3] = 255
        save_png(rgba, png_path)

        manifest_textures = [{
            "id": "tex_0001",
            "decoded_png_path": "textures/test.png",
            "width": 8, "height": 8,
            "detected_format": "RGBA8",
            "source_file_path": "fake/source.bch",
        }]
        pack_dir, pack_meta = build_pack(
            td, "0004000000055E00", manifest_textures, mode="staging",
        )
        assert os.path.isdir(pack_dir)
        # Staging is not a drop-in pack: Forge metadata only, no Azahar pack.json.
        assert os.path.isfile(os.path.join(pack_dir, "forge_pack_meta.json"))
        assert not os.path.isfile(os.path.join(pack_dir, "pack.json"))
        with open(os.path.join(pack_dir, "forge_pack_meta.json")) as f:
            pack_meta = json.load(f)
        assert pack_meta["pack_mode"] == "staging"
        assert pack_meta["unmapped_count"] == 1


def test_imgc_plugin_registered():
    """Level-5 IMGC plugin should appear in the texture registry."""
    from tex_forge.textures.registry import iter_plugins
    names = {r.name for r in iter_plugins()}
    assert "imgc" in names


def test_crilayla_codec_registered():
    from tex_forge.compression import iter_codecs
    names = {c.name for c in iter_codecs()}
    assert "crilayla" in names
