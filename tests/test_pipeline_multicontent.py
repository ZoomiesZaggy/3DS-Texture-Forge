"""Multi-content extraction orchestration, without a real ROM.

We can't synthesize a full 3DS RomFS cheaply, so we stub `RomFSParser` and
`extract_textures` in the extractor's namespace to feed one known-decodable
RGBA8 texture per content. That still drives the real code under test:
ExtractionPipeline.run() looping over [primary] + extra_contents, the shared
texture counter, the shared deduper, per-content manifest tagging, and the
normal-mode output-path namespacing.
"""

import tempfile

import pytest

import tex_forge.pipeline.extractor as extractor
from tex_forge.core.types import Texture
from tex_forge.pipeline.extractor import (
    ContentSource,
    ExtractionPipeline,
    ExtractOptions,
)
from tex_forge.textures.formats import PicaFormat


def _rgba8_blob(fill: int) -> bytes:
    # 8x8 RGBA8 = 256 bytes, varied enough not to trip the solid-color filters.
    out = bytearray()
    for i in range(64):
        out.extend([fill, (i * 3) & 0xFF, 0x20, 0xFF])
    return bytes(out)


class _FakeRomFS:
    """Serves exactly one file whose bytes are the content's marker blob."""

    _blobs = {}  # romfs_data -> file bytes

    def __init__(self, data):
        self._data = data

    def list_files(self):
        # (path, offset, size) -- the same internal path in every content, so
        # the namespacing logic is actually exercised.
        yield ("a/0/0/0/tex.bin", 0x100, len(self._blobs[self._data]))

    def read_file_by_index(self, idx):
        return None, self._blobs[self._data]


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(extractor, "RomFSParser", _FakeRomFS)
    monkeypatch.setattr(extractor, "smash_virtual_entries", lambda files, data: {})
    monkeypatch.setattr(extractor, "build_texturebin_index", lambda files: {})

    def fake_extract(file_data, file_path, title_id="", scan_all=False):
        yield Texture(
            name="t", width=8, height=8, format=int(PicaFormat.RGBA8),
            data=file_data, parser_used="ctpk", source_file=file_path,
        )

    monkeypatch.setattr(extractor, "extract_textures", fake_extract)
    return monkeypatch


def _run_two_contents(out_dir, dedup=False, mode="normal"):
    main = _rgba8_blob(0xA0)
    dlc = _rgba8_blob(0xB0)
    _FakeRomFS._blobs = {main: main, dlc: dlc}

    pipe = ExtractionPipeline(
        romfs_data=main,
        title_id="0004000000055D00",
        product_code="CTR-P-EKJE",
        chain="CIA/content0(main)/NCCH/RomFS",
        rom_path="game.cia",
        options=ExtractOptions(
            output_dir=out_dir, output_mode=mode, dedup=dedup,
            write_png=False, write_contact_sheet=False,
            write_quality_report=False,
        ),
        content_source="content0(main)",
        extra_contents=[ContentSource(dlc, "CIA/content1(DLC)/NCCH/RomFS", "content1(DLC)")],
    )
    return pipe.run(), pipe.records


def test_records_tagged_per_content_and_ids_unique(patched):
    with tempfile.TemporaryDirectory() as td:
        summary, records = _run_two_contents(td)

    assert summary["content_count"] == 2
    assert len(summary["contents"]) == 2
    assert summary["textures_decoded_ok"] == 2

    # Unique IDs across contents (shared counter).
    assert [r["id"] for r in records] == ["tex_0000", "tex_0001"]

    by_content = {r["source_content"]: r for r in records}
    assert set(by_content) == {"content0(main)", "content1(DLC)"}
    assert "content0(main)" in by_content["content0(main)"]["source_container_chain"]
    assert "content1(DLC)" in by_content["content1(DLC)"]["source_container_chain"]


def test_normal_mode_namespaces_dlc_path(patched):
    with tempfile.TemporaryDirectory() as td:
        _summary, records = _run_two_contents(td, mode="normal")

    dlc = next(r for r in records if r["source_content"] == "content1(DLC)")
    main = next(r for r in records if r["source_content"] == "content0(main)")
    # DLC output is namespaced; main is not, so they can't collide despite the
    # identical internal RomFS path.
    assert dlc["decoded_png_path"].startswith("content1_DLC")
    assert not main["decoded_png_path"].startswith("content1_DLC")
    assert dlc["decoded_png_path"] != main["decoded_png_path"]


def test_shared_dedup_across_contents(patched):
    # Same bytes in both contents -> with dedup on, the second is flagged a
    # duplicate of the first even though it came from a different content.
    with tempfile.TemporaryDirectory() as td:
        same = _rgba8_blob(0xC0)
        _FakeRomFS._blobs = {same: same}
        pipe = ExtractionPipeline(
            romfs_data=same,
            title_id="0004000000055D00",
            chain="CIA/content0(main)/NCCH/RomFS",
            options=ExtractOptions(
                output_dir=td, dedup=True, write_png=False,
                write_contact_sheet=False, write_quality_report=False,
            ),
            content_source="content0(main)",
            extra_contents=[ContentSource(same, "CIA/content1(DLC)/NCCH/RomFS", "content1(DLC)")],
        )
        # Distinct dict identity for the second blob so the fake serves it too.
        second = bytes(same)
        _FakeRomFS._blobs[second] = same
        pipe.extra_contents[0] = ContentSource(second, "CIA/content1(DLC)/NCCH/RomFS", "content1(DLC)")
        summary = pipe.run()
        records = pipe.records

    assert len(records) == 2
    assert summary["textures_unique"] == 1
    assert any(r.get("duplicate_of") for r in records)
