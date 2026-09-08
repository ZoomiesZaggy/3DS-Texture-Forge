"""Tests for `tex-forge batch` and `tex-forge verify`.

batch: discovery, continue-on-error, duplicate-title skipping, summary JSON,
exit codes. The ROM loader is stubbed per fake file; the REAL
ExtractionPipeline runs underneath (extractor namespace patched the same way
as test_pipeline_multicontent).

verify: synthetic project dirs covering clean output, the pre-fix
filename-collision signature (shared decoded_png_path), missing PNGs, orphan
PNGs, and confirmation that legit dedup duplicates are not flagged.
"""

import json
import os
import tempfile

import pytest

import tex_forge.commands.batch as batch
import tex_forge.pipeline.extractor as extractor
from tex_forge.cli import main as cli_main
from tex_forge.commands.batch import discover_rom_files
from tex_forge.commands.verify import verify_project
from tex_forge.core.exceptions import ROMParseError
from tex_forge.core.types import Texture
from tex_forge.textures.formats import PicaFormat


# ---------------------------------------------------------------- batch ----

def _blob(fill: int) -> bytes:
    out = bytearray()
    for i in range(64):
        out.extend([fill, (i * 5) & 0xFF, 0x30, 0xFF])
    return bytes(out)


class _OneFileRomFS:
    def __init__(self, data):
        pass

    def list_files(self):
        yield ("ui/menu.bch", 0x100, 256)

    def read_file_by_index(self, idx):
        return None, b"x" * 256


@pytest.fixture
def batch_env(monkeypatch):
    """Fake loader keyed by ROM basename + real pipeline with stub RomFS."""
    monkeypatch.setattr(extractor, "RomFSParser", _OneFileRomFS)
    monkeypatch.setattr(extractor, "smash_virtual_entries", lambda f, d: {})
    monkeypatch.setattr(extractor, "build_texturebin_index", lambda f: {})
    monkeypatch.setattr(
        extractor, "extract_textures",
        lambda d, p, title_id="", scan_all=False: iter([Texture(
            name="", width=8, height=8, format=int(PicaFormat.RGBA8),
            data=_blob(0x40), parser_used="ctpk", source_file=p)]))

    def fake_iter(path):
        base = os.path.basename(path)
        if base.startswith("bad"):
            raise ROMParseError("synthetic parse failure")
        # title id derives from the first letter, so dupA1/dupA2 share one
        tid = "AAAA00000000" + base[3].upper() * 4 if base.startswith("dup") \
            else f"{abs(hash(base)) % (16**16):016X}"
        yield (b"romfs", tid, "CTR-P-TEST", "NCSD/partition0/NCCH/RomFS")

    monkeypatch.setattr(batch, "iter_rom_contents", fake_iter)
    return monkeypatch


def _touch(folder, name):
    p = os.path.join(folder, name)
    with open(p, "wb") as f:
        f.write(b"\x00" * 16)
    return p


def test_discover_rom_files_walks_dedups_and_rejects():
    with tempfile.TemporaryDirectory() as td:
        sub = os.path.join(td, "nested")
        os.makedirs(sub)
        a = _touch(td, "GameA.3ds")
        b = _touch(sub, "GameB.cia")
        _touch(td, "notes.txt")
        roms, missing = discover_rom_files([td, a, os.path.join(td, "gone.3ds")])
        assert sorted(os.path.basename(r) for r in roms) == \
            ["GameA.3ds", "GameB.cia"]  # folder walk + explicit file de-duped
        assert len(missing) == 1
        assert b in roms


def test_batch_continues_on_error_and_writes_summary(batch_env, capsys):
    with tempfile.TemporaryDirectory() as td:
        lib = os.path.join(td, "lib")
        os.makedirs(lib)
        _touch(lib, "GameA.3ds")
        _touch(lib, "bad_rom.3ds")
        out = os.path.join(td, "out")
        rc = cli_main(["batch", lib, "-o", out, "--quiet",
                       "--no-contact-sheet", "--no-quality-report"])
        assert rc == 1  # a failure occurred, but the batch finished
        with open(os.path.join(out, "batch_summary.json")) as f:
            s = json.load(f)
        assert s["rom_count"] == 2
        assert s["extracted"] == 1 and s["failed"] == 1
        ok = next(r for r in s["results"] if r["status"] == "ok")
        assert os.path.isfile(os.path.join(ok["output_dir"], "manifest.json"))
        assert ok["textures_decoded_ok"] == 1
        bad = next(r for r in s["results"] if r["status"] == "failed")
        assert "synthetic parse failure" in bad["error"]


def test_batch_skips_duplicate_titles(batch_env):
    with tempfile.TemporaryDirectory() as td:
        lib = os.path.join(td, "lib")
        os.makedirs(lib)
        _touch(lib, "dupA1.3ds")
        _touch(lib, "dupA2.cia")  # same synthetic title id as dupA1
        out = os.path.join(td, "out")
        rc = cli_main(["batch", lib, "-o", out, "--quiet",
                       "--no-contact-sheet", "--no-quality-report"])
        assert rc == 0
        with open(os.path.join(out, "batch_summary.json")) as f:
            s = json.load(f)
        assert s["extracted"] == 1 and s["skipped_duplicates"] == 1
        skip = next(r for r in s["results"]
                    if r["status"] == "skipped_duplicate")
        assert skip["duplicate_of"] == "dupA1.3ds"


def test_batch_limit(batch_env):
    with tempfile.TemporaryDirectory() as td:
        lib = os.path.join(td, "lib")
        os.makedirs(lib)
        for n in ("GameA.3ds", "GameB.3ds", "GameC.3ds"):
            _touch(lib, n)
        out = os.path.join(td, "out")
        rc = cli_main(["batch", lib, "-o", out, "--quiet", "--limit", "2",
                       "--no-contact-sheet", "--no-quality-report"])
        assert rc == 0
        with open(os.path.join(out, "batch_summary.json")) as f:
            assert json.load(f)["rom_count"] == 2


# --------------------------------------------------------------- verify ----

def _write_project(td, records, pngs=()):
    for rel in pngs:
        full = os.path.join(td, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(b"\x89PNG fake")
    with open(os.path.join(td, "manifest.json"), "w") as f:
        json.dump({"schema_version": 2, "texture_count": len(records),
                   "textures": records}, f)


def test_verify_clean_project():
    with tempfile.TemporaryDirectory() as td:
        recs = [
            {"id": "tex_0000", "decoded_png_path": "textures/tex_0000_a.png"},
            {"id": "tex_0001", "decoded_png_path": "",
             "duplicate_of": "tex_0000"},  # legit dedup duplicate
        ]
        _write_project(td, recs, pngs=["textures/tex_0000_a.png"])
        rep = verify_project(td)
        assert rep["ok"] is True
        assert rep["shared_paths"] == {} and rep["missing_pngs"] == []


def test_verify_flags_collision_signature_and_missing_and_orphans():
    with tempfile.TemporaryDirectory() as td:
        recs = [
            {"id": "tex_0000", "decoded_png_path": "textures/tex_0000_x.png"},
            {"id": "tex_0001", "decoded_png_path": "textures/tex_0000_x.png"},
            {"id": "tex_0002", "decoded_png_path": "textures/tex_gone.png"},
        ]
        _write_project(td, recs, pngs=[
            "textures/tex_0000_x.png",
            "textures/tex_orphan.png",      # on disk, never referenced
        ])
        rep = verify_project(td)
        assert rep["ok"] is False
        assert list(rep["shared_paths"].values()) == [["tex_0000", "tex_0001"]]
        assert rep["missing_pngs"][0]["id"] == "tex_0002"
        assert rep["orphan_pngs"] == [os.path.join("textures",
                                                   "tex_orphan.png")]


def test_verify_cli_exit_codes():
    with tempfile.TemporaryDirectory() as td:
        _write_project(td, [{"id": "tex_0000",
                             "decoded_png_path": "textures/tex_0000.png"}],
                       pngs=["textures/tex_0000.png"])
        assert cli_main(["verify", td, "--quiet"]) == 0
    with tempfile.TemporaryDirectory() as td:
        assert cli_main(["verify", td, "--quiet"]) == 1  # no manifest
