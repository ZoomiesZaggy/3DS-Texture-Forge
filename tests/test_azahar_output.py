"""Azahar drop-in correctness: filename hash/format/mip and pack config.

The failure mode these guard against is silent: a texture whose filename
hash or format code is even slightly wrong simply never matches Azahar's
runtime lookup, so the replacement is ignored with no error. We lock:

  * azahar_filename emits the dumper-exact `..._<code>_mip0.png` shape.
  * `extract --output-mode azahar` names files by CityHash64 (Azahar's
    legacy lookup hash) -- NOT xxhash, the bug this replaced -- and produces
    byte-identical names to build-pack.
  * build-pack ships a tiny Azahar pack.json pinning use_new_hash=false, with
    Forge's verbose metadata kept out of pack.json (so it can neither flip
    Azahar to the new hash nor trip the large-pack.json crash).
"""

import json
import os
import tempfile

import numpy as np
import pytest

import tex_forge.pipeline.extractor as extractor
from tex_forge.core.types import Texture
from tex_forge.output import save_png
from tex_forge.output.pack_builder import build_pack
from tex_forge.pipeline.extractor import ExtractionPipeline, ExtractOptions
from tex_forge.textures.azahar_hash import azahar_filename, azahar_hash_hex
from tex_forge.textures.formats import PicaFormat


def _rgba8_8x8(fill: int) -> bytes:
    return b"".join(bytes([fill, (i * 7) & 0xFF, 0x33, 0xFF]) for i in range(64))


# ── azahar_filename shape ────────────────────────────────────────────────────

def test_azahar_filename_shape():
    h = 0x543624189C94B105
    assert azahar_filename(256, 256, h, "RGBA8") == "tex1_256x256_543624189C94B105_0_mip0.png"
    assert azahar_filename(64, 64, h, "ETC1A4") == "tex1_64x64_543624189C94B105_13_mip0.png"
    # Forge alias names resolve to the same Azahar code as canonical names.
    assert azahar_filename(8, 8, h, "RGBA5551") == azahar_filename(8, 8, h, "RGB5A1")
    assert azahar_filename(8, 8, h, "NOT_A_FORMAT") is None


# ── extract azahar mode uses CityHash64, matches build-pack ──────────────────

class _FakeRomFS:
    blob = b""

    def __init__(self, data):
        pass

    def list_files(self):
        return [("a/0/0/0/t.bin", 0x100, len(_FakeRomFS.blob))]

    def read_file_by_index(self, idx):
        return None, _FakeRomFS.blob


def _run_azahar(monkeypatch, out_dir, blob):
    _FakeRomFS.blob = blob
    monkeypatch.setattr(extractor, "RomFSParser", _FakeRomFS)
    monkeypatch.setattr(extractor, "smash_virtual_entries", lambda f, d: {})
    monkeypatch.setattr(extractor, "build_texturebin_index", lambda f: {})
    monkeypatch.setattr(
        extractor, "extract_textures",
        lambda fd, fp, title_id="", scan_all=False: [
            Texture(width=8, height=8, format=int(PicaFormat.RGBA8),
                    data=fd, parser_used="ctpk", source_file=fp)
        ],
    )
    pipe = ExtractionPipeline(
        romfs_data=blob, title_id="0004000000055D00",
        chain="NCSD/partition0/NCCH/RomFS",
        options=ExtractOptions(output_dir=out_dir, output_mode="azahar",
                               write_png=False, write_contact_sheet=False,
                               write_quality_report=False),
    )
    pipe.run()
    return pipe.records[0]


def test_extract_azahar_names_by_cityhash_not_xxhash(monkeypatch):
    blob = _rgba8_8x8(0xA0)
    with tempfile.TemporaryDirectory() as td:
        rec = _run_azahar(monkeypatch, td, blob)

    city = azahar_hash_hex(blob)
    assert rec["azahar_hash_cityhash64"] == city

    expected = azahar_filename(8, 8, int(city, 16), "RGBA8")
    assert os.path.basename(rec["decoded_png_path"]) == expected

    # Regression guard: the old code used xxh64 here. Make sure that value
    # does NOT appear in the filename.
    import xxhash
    assert xxhash.xxh64(blob).hexdigest().upper() not in rec["decoded_png_path"]


# ── build-pack config + filename agreement ───────────────────────────────────

def test_build_pack_azahar_config_and_filenames():
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "textures"))
        png_rel = "textures/x.png"
        rgba = np.full((8, 8, 4), 50, dtype=np.uint8)
        rgba[..., 3] = 255
        save_png(rgba, os.path.join(td, png_rel))

        h = "543624189C94B105"
        manifest = [{
            "id": "tex_0000", "decoded_png_path": png_rel,
            "width": 8, "height": 8, "detected_format": "RGBA8",
            "azahar_hash_cityhash64": h,
        }]
        pack_dir, _meta = build_pack(td, "0004000000055D00", manifest, mode="azahar")

        # Azahar config: tiny, pins legacy hash, kept separate from Forge meta.
        cfg_path = os.path.join(pack_dir, "pack.json")
        cfg = json.load(open(cfg_path))
        assert cfg["use_new_hash"] is False
        assert "name" in cfg and "author" in cfg
        assert os.path.getsize(cfg_path) < 2000          # nowhere near the crash size
        assert os.path.isfile(os.path.join(pack_dir, "forge_pack_meta.json"))

        # The shipped PNG is named exactly as Azahar will look it up.
        assert os.path.isfile(os.path.join(pack_dir, azahar_filename(8, 8, int(h, 16), "RGBA8")))


def test_build_pack_staging_has_no_azahar_pack_json():
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "textures"))
        rgba = np.full((8, 8, 4), 50, dtype=np.uint8); rgba[..., 3] = 255
        save_png(rgba, os.path.join(td, "textures/x.png"))
        manifest = [{
            "id": "tex_0000", "decoded_png_path": "textures/x.png",
            "width": 8, "height": 8, "detected_format": "RGBA8",
            "source_file_path": "f.cgfx",
        }]
        pack_dir, _ = build_pack(td, "0004000000055D00", manifest, mode="staging")
        # Not a drop-in: no Azahar pack.json should be written.
        assert not os.path.isfile(os.path.join(pack_dir, "pack.json"))
        assert os.path.isfile(os.path.join(pack_dir, "forge_pack_meta.json"))
