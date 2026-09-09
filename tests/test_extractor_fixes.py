"""Regression tests for the 2026-06 review fixes.

Covers:
  * Normal-mode filename collision: two unnamed textures sharing a format and
    size in the same source dir must get DISTINCT paths (previously every one
    was named tex_0000_... and silently overwrote the last).
  * dump_raw: raw GPU bytes land under raw/ and the manifest records the path.
  * list_only: manifest written, nothing decoded, no PNGs on disk.
  * cancel_event: a set event stops the run and marks summary["canceled"].
  * FileFilter tail peek: BFLIM footers (magic at file end) are now reachable.

Same stub harness as test_pipeline_multicontent: RomFSParser and
extract_textures are patched in the extractor's namespace so the real
pipeline loop, counters, writers, and options run against synthetic blobs.
"""

import json
import os
import tempfile
import threading

import pytest

import tex_forge.pipeline.extractor as extractor
from tex_forge.core.types import Texture
from tex_forge.pipeline.extractor import ExtractionPipeline, ExtractOptions
from tex_forge.pipeline.filter import FileFilter
from tex_forge.textures.formats import PicaFormat


def _blob(fill: int) -> bytes:
    out = bytearray()
    for i in range(64):
        out.extend([fill, (i * 5) & 0xFF, 0x30, 0xFF])
    return bytes(out)


BLOB_A = _blob(0x10)
BLOB_B = _blob(0xEE)


class _OneFileRomFS:
    """Serves a single inner file; extract_textures is patched separately."""

    def __init__(self, data):
        self._data = data

    def list_files(self):
        yield ("ui/menu.bch", 0x100, 256)

    def read_file_by_index(self, idx):
        return None, b"x" * 256


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(extractor, "RomFSParser", _OneFileRomFS)
    monkeypatch.setattr(extractor, "smash_virtual_entries", lambda f, d: {})
    monkeypatch.setattr(extractor, "build_texturebin_index", lambda f: {})

    def fake_extract(file_data, file_path, title_id="", scan_all=False):
        for d in (BLOB_A, BLOB_B):  # two DIFFERENT unnamed textures
            yield Texture(name="", width=8, height=8,
                          format=int(PicaFormat.RGBA8), data=d,
                          parser_used="ctpk", source_file=file_path)

    monkeypatch.setattr(extractor, "extract_textures", fake_extract)
    return monkeypatch


def _run(out_dir, **opt_kwargs):
    pipe = ExtractionPipeline(
        romfs_data=b"r", title_id="TEST", chain="NCCH/RomFS",
        options=ExtractOptions(output_dir=out_dir, **opt_kwargs),
    )
    summary = pipe.run()
    return pipe, summary


def _pngs_on_disk(out_dir):
    found = []
    for root, _dirs, files in os.walk(out_dir):
        found.extend(f for f in files
                     if f.endswith(".png") and f.startswith("tex_"))
    return sorted(found)


def test_unnamed_same_format_textures_get_distinct_paths(patched):
    with tempfile.TemporaryDirectory() as td:
        pipe, summary = _run(td)
        assert summary["textures_decoded_ok"] == 2
        paths = [r["decoded_png_path"] for r in pipe.records]
        assert len(set(paths)) == 2, f"colliding output paths: {paths}"
        assert _pngs_on_disk(td) == ["tex_0000_RGBA8_8x8.png",
                                     "tex_0001_RGBA8_8x8.png"]


def test_dump_raw_writes_bin_and_manifest_path(patched):
    with tempfile.TemporaryDirectory() as td:
        pipe, _ = _run(td, dump_raw=True)
        raw_dir = os.path.join(td, "raw")
        assert os.path.isdir(raw_dir)
        bins = sorted(os.listdir(raw_dir))
        assert bins == ["tex_0000_8x8_RGBA8.bin", "tex_0001_8x8_RGBA8.bin"]
        with open(os.path.join(raw_dir, bins[0]), "rb") as f:
            assert f.read() == BLOB_A
        for rec in pipe.records:
            assert rec.get("raw_dump_path", "").startswith("raw")


def test_list_only_records_without_decoding(patched):
    with tempfile.TemporaryDirectory() as td:
        pipe, summary = _run(td, list_only=True)
        assert summary["textures_decoded_ok"] == 2
        assert len(pipe.records) == 2
        assert all(r["decoded_png_path"] == "" for r in pipe.records)
        assert _pngs_on_disk(td) == []
        # manifest still written so `tex-forge report` can consume it
        with open(os.path.join(td, "manifest.json")) as f:
            assert json.load(f)["texture_count"] == 2
        # no quality/contact artifacts in list mode
        assert not os.path.exists(os.path.join(td, "contact_sheet.png"))
        assert not os.path.exists(os.path.join(td, "quality_report.json"))


def test_cancel_event_stops_run_and_marks_summary(patched):
    with tempfile.TemporaryDirectory() as td:
        ev = threading.Event()
        ev.set()  # canceled before the first file
        pipe = ExtractionPipeline(
            romfs_data=b"r", title_id="TEST", chain="NCCH/RomFS",
            options=ExtractOptions(output_dir=td),
            cancel_event=ev,
        )
        summary = pipe.run()
        assert summary.get("canceled") is True
        assert summary["textures_decoded_ok"] == 0
        # partial outputs still land: a canceled run is inspectable
        assert os.path.exists(os.path.join(td, "manifest.json"))


def test_azahar_hash_covers_mip0_only_for_mipped_texture(monkeypatch):
    """A mipped payload (data longer than the mip0 surface) must be hashed over
    the mip0 slice only; a single-surface texture must hash the whole buffer."""
    from tex_forge.textures.azahar_hash import azahar_hash_hex, is_available

    if not is_available():
        pytest.skip("no CityHash64 backend")

    # ETC1 is 4 bpp: mip0 for 64x64 = 64*64*4/8 = 2048 bytes. Append a fake mip
    # chain so tex.data is longer than mip0 (mirrors CGFX mip0..mipN payloads).
    mip0 = bytes((i * 7) & 0xFF for i in range(2048))
    mipped_data = mip0 + bytes((i * 3) & 0xFF for i in range(700))
    # RGBA8 is 32 bpp: 8x8 = 256 bytes, exactly one surface (no mips).
    single_data = _blob(0x10)  # 64 * 4 = 256 bytes

    monkeypatch.setattr(extractor, "RomFSParser", _OneFileRomFS)
    monkeypatch.setattr(extractor, "smash_virtual_entries", lambda f, d: {})
    monkeypatch.setattr(extractor, "build_texturebin_index", lambda f: {})

    def fake_extract(file_data, file_path, title_id="", scan_all=False):
        yield Texture(name="mipped", width=64, height=64,
                      format=int(PicaFormat.ETC1), data=mipped_data,
                      parser_used="cgfx", source_file=file_path)
        yield Texture(name="single", width=8, height=8,
                      format=int(PicaFormat.RGBA8), data=single_data,
                      parser_used="ctpk", source_file=file_path)

    monkeypatch.setattr(extractor, "extract_textures", fake_extract)

    with tempfile.TemporaryDirectory() as td:
        pipe, _ = _run(td, list_only=True)
        recs = list(pipe.records)
        mipped_rec = next(r for r in recs if r["width"] == 64)
        single_rec = next(r for r in recs if r["width"] == 8)

        # mipped: hash is over mip0 (2048), NOT the full 2748-byte buffer
        assert mipped_rec["azahar_hash_cityhash64"] == azahar_hash_hex(mip0)
        assert mipped_rec["azahar_hash_cityhash64"] != azahar_hash_hex(mipped_data)
        # but the recorded raw size is still the whole buffer
        assert mipped_rec["raw_data_size"] == len(mipped_data)

        # single surface: unchanged, whole buffer hashed
        assert single_rec["azahar_hash_cityhash64"] == azahar_hash_hex(single_data)


def test_filter_tail_peek_catches_bflim_footer():
    f = FileFilter()
    # extensionless path outside any texture dir: only magic can save it
    path = "stuff/blob001"
    head = b"\x00" * 0x30  # pixel data first; nothing recognisable up front
    tail = b"\x00" * 0  # build a real 0x28-byte footer, FLIM magic first
    tail = b"FLIM" + b"\x00" * 0x24
    assert len(tail) == 0x28
    assert f.should_peek(path, head, tail) is True
    assert f.should_peek(path, head) is False  # head alone still rejects
