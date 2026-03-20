"""
Pipeline regression tests.

Tests manifest writing, contact sheet generation, TEX report generation,
pack.json generation, import-dump filename parsing, and duplicate detection.

Run with: python test_pipeline.py
"""

import sys
import os
import json
import shutil
import tempfile
import struct
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from output import (
    make_texture_record, write_manifest, write_failures,
    write_unknown_files, write_summary, sha1_bytes, sha1_rgba,
    save_texture_as_png,
)
from quality import compute_quality_metrics
from contact_sheet import generate_contact_sheet
from pack_builder import build_pack
from main import _parse_dump_filename
from textures.tex_capcom import parse_capcom_tex_strict, TexParseResult


def _tmpdir():
    d = tempfile.mkdtemp(prefix="3ds_test_")
    return d


def _make_rgba(w, h, r=128, g=64, b=32, a=255):
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    arr[:, :, 0] = r
    arr[:, :, 1] = g
    arr[:, :, 2] = b
    arr[:, :, 3] = a
    return arr


def _save_test_png(dirpath, name, w=32, h=32, **kwargs):
    rgba = _make_rgba(w, h, **kwargs)
    path = os.path.join(dirpath, name)
    save_texture_as_png(rgba, path)
    return path, rgba


# ─── Tests ────────────────────────────────────

def test_manifest_schema():
    """Verify manifest.json has all required fields."""
    print("Testing manifest schema...")
    d = _tmpdir()
    try:
        rec = make_texture_record(
            tex_id="tex_0000",
            source_rom="test.3ds",
            source_container_chain="NCSD/NCCH/RomFS",
            source_file_path="/tex/body.tex",
            source_offset=0x1000,
            detected_format="ETC1A4",
            width=256, height=256,
            mip_count=1,
            raw_data_size=65536,
            decoded_png_path="textures/tex/tex_0000_ETC1A4_256x256.png",
            confidence="high",
            parser_used="capcom_tex/standard_tex",
            notes="test note",
            sha1_rgba_val="abc123",
            sha1_source_val="def456",
            quality_metrics={"pct_transparent": 0, "variance_score": 100, "is_suspicious": False},
        )

        required_keys = [
            "id", "source_rom", "source_container_chain", "source_file_path",
            "source_offset", "detected_format", "width", "height", "mip_count",
            "raw_data_size", "decoded_png_path", "confidence", "parser_used",
            "notes", "sha1_rgba", "sha1_source_blob", "failed_reason", "quality",
        ]
        for k in required_keys:
            assert k in rec, f"Missing key: {k}"

        write_manifest(d, [rec], "test.3ds", "0004000000035D00", "RE_REV")
        with open(os.path.join(d, "manifest.json"), "r") as f:
            m = json.load(f)
        assert m["schema_version"] == 2
        assert len(m["textures"]) == 1
        assert m["textures"][0]["id"] == "tex_0000"
        print("  PASSED")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_failures_and_unknowns():
    """Verify failures.json and unknown_files.json output."""
    print("Testing failures/unknowns...")
    d = _tmpdir()
    try:
        write_failures(d, [{"id": "tex_0001", "reason": "bad data"}])
        write_unknown_files(d, [{"path": "/data/foo.bin", "size": 999}])

        with open(os.path.join(d, "failures.json"), "r") as f:
            fj = json.load(f)
        assert fj["count"] == 1

        with open(os.path.join(d, "unknown_files.json"), "r") as f:
            uj = json.load(f)
        assert uj["count"] == 1
        print("  PASSED")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_summary():
    """Verify summary.json output."""
    print("Testing summary...")
    d = _tmpdir()
    try:
        write_summary(d, {"files_scanned": 42, "textures_decoded_ok": 10})
        with open(os.path.join(d, "summary.json"), "r") as f:
            s = json.load(f)
        assert s["files_scanned"] == 42
        print("  PASSED")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_quality_metrics():
    """Verify quality metric computation."""
    print("Testing quality metrics...")

    # Normal texture with variance
    rgba = np.random.randint(0, 256, (32, 32, 4), dtype=np.uint8)
    rgba[:, :, 3] = 255
    qm = compute_quality_metrics(rgba)
    assert not qm["is_suspicious"], "Random texture should not be suspicious"
    assert qm["pct_transparent"] == 0.0

    # Solid color
    solid = np.full((16, 16, 4), 128, dtype=np.uint8)
    qm2 = compute_quality_metrics(solid)
    assert qm2["is_suspicious"], "Solid color should be suspicious"
    assert "solid_color" in qm2["flags"]

    # Mostly transparent
    trans = np.zeros((16, 16, 4), dtype=np.uint8)
    qm3 = compute_quality_metrics(trans)
    assert qm3["pct_transparent"] == 100.0

    print("  PASSED")


def test_contact_sheet():
    """Verify contact sheet generation."""
    print("Testing contact sheet...")
    d = _tmpdir()
    try:
        tex_dir = os.path.join(d, "textures")
        os.makedirs(tex_dir)

        records = []
        for i in range(4):
            png_path, _ = _save_test_png(tex_dir, f"tex_{i:04d}.png",
                                          r=i * 60, g=255 - i * 60)
            records.append({
                "decoded_png_path": os.path.relpath(png_path, d),
                "width": 32,
                "height": 32,
                "detected_format": "RGBA8",
                "source_file_path": f"/tex/file{i}.tex",
            })

        cs_path = generate_contact_sheet(records, d, columns=2)
        assert cs_path, "Contact sheet path should not be empty"
        assert os.path.isfile(cs_path), f"Contact sheet file missing: {cs_path}"

        from PIL import Image
        img = Image.open(cs_path)
        assert img.width > 0 and img.height > 0
        print(f"  Sheet size: {img.width}x{img.height}")
        print("  PASSED")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_tex_report():
    """Verify Capcom TEX parse result serialization."""
    print("Testing TEX report generation...")

    # Construct a minimal valid TEX file
    header = bytearray(16)
    header[0:4] = b"TEX\x00"
    header[4:6] = struct.pack("<H", 1)   # version
    header[6:8] = struct.pack("<H", 64)  # width
    header[8:10] = struct.pack("<H", 64) # height
    header[10] = 1                        # mip count
    header[11] = 0x0B                     # format: ETC1 in Capcom mapping
    header[12:16] = struct.pack("<I", 16) # data offset

    # Fake pixel data (ETC1: 4bpp, 64x64 = 2048 bytes)
    pixel_data = os.urandom(2048)
    tex_data = bytes(header) + pixel_data

    result = parse_capcom_tex_strict(tex_data, "/tex/test.tex")
    assert result.status == "parsed", f"Expected parsed, got {result.status}"
    assert result.width == 64
    assert result.height == 64
    assert result.confidence in ("high", "medium")

    d = result.to_dict()
    assert "path" in d
    assert "status" in d
    assert d["status"] == "parsed"
    print(f"  Parsed: {d['width']}x{d['height']} fmt={d['format_raw']} conf={d['confidence']}")
    print("  PASSED")


def test_tex_report_bad_file():
    """Verify TEX parser logs failure cleanly for garbage data."""
    print("Testing TEX report for bad file...")
    result = parse_capcom_tex_strict(b"\x00" * 32, "/tex/garbage.tex")
    assert result.status == "failed", f"Expected failed, got {result.status}"
    assert len(result.notes) > 0
    d = result.to_dict()
    assert d["status"] == "failed"
    print(f"  Notes: {result.notes}")
    print("  PASSED")


def test_pack_json_generation():
    """Verify pack.json is created with correct structure."""
    print("Testing pack.json generation...")
    d = _tmpdir()
    try:
        tex_dir = os.path.join(d, "textures")
        os.makedirs(tex_dir)
        png_path, _ = _save_test_png(tex_dir, "tex_0000.png")

        records = [{
            "id": "tex_0000",
            "decoded_png_path": os.path.relpath(png_path, d),
            "source_file_path": "/tex/body.tex",
            "width": 32, "height": 32,
            "detected_format": "ETC1A4",
        }]

        pack_dir = build_pack(d, "0004000000035D00", records, mode="staging")
        pack_json = os.path.join(pack_dir, "pack.json")
        assert os.path.isfile(pack_json), "pack.json not created"

        with open(pack_json, "r") as f:
            pj = json.load(f)

        assert pj["pack_mode"] == "staging"
        assert pj["texture_count"] == 1
        assert pj["unmapped_count"] == 1
        assert pj["warning"] is not None
        assert "STAGING" in pj["warning"]
        print("  PASSED")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_pack_mapped_mode():
    """Verify mapped pack with a dump hash."""
    print("Testing mapped pack generation...")
    d = _tmpdir()
    try:
        tex_dir = os.path.join(d, "textures")
        os.makedirs(tex_dir)
        png_path, _ = _save_test_png(tex_dir, "tex_0000.png")

        records = [{
            "id": "tex_0000",
            "decoded_png_path": os.path.relpath(png_path, d),
            "source_file_path": "/tex/body.tex",
            "width": 32, "height": 32,
            "detected_format": "ETC1A4",
            "dump_hash": "deadbeef01234567",
        }]

        pack_dir = build_pack(d, "0004000000035D00", records, mode="mapped")
        pack_json = os.path.join(pack_dir, "pack.json")
        with open(pack_json, "r") as f:
            pj = json.load(f)

        assert pj["pack_mode"] == "mapped"
        assert pj["mapped_count"] == 1
        assert pj["unmapped_count"] == 0
        assert pj["warning"] is None

        # Check that the hash-named PNG exists
        hash_png = os.path.join(pack_dir, "deadbeef01234567.png")
        assert os.path.isfile(hash_png), "Hash-named PNG not found"
        print("  PASSED")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_import_dump_filename_parsing():
    """Verify dump filename parsing handles various patterns."""
    print("Testing import-dump filename parsing...")

    # Pattern: tex1_256x256_DEADBEEF_ETC1_mip0.png
    r = _parse_dump_filename("tex1_256x256_DEADBEEF01234567_ETC1_mip0.png")
    assert r["width"] == 256
    assert r["height"] == 256
    assert r["hash"] == "deadbeef01234567"
    assert r["format"] == "ETC1"
    assert r["mip"] == 0

    # Pattern: plain hex hash
    r2 = _parse_dump_filename("ABCDEF0123456789.png")
    assert r2["hash"] == "abcdef0123456789"

    # Pattern: 0xHASH_WxH.png
    r3 = _parse_dump_filename("0xDEADBEEF_512x512.png")
    assert r3["width"] == 512
    assert r3["height"] == 512
    assert "deadbeef" in r3["hash"]

    print("  PASSED")


def test_duplicate_detection():
    """Verify sha1 hashing catches duplicates."""
    print("Testing duplicate detection via sha1...")

    data1 = b"\x01\x02\x03" * 100
    data2 = b"\x01\x02\x03" * 100
    data3 = b"\x04\x05\x06" * 100

    assert sha1_bytes(data1) == sha1_bytes(data2)
    assert sha1_bytes(data1) != sha1_bytes(data3)

    rgba1 = np.full((8, 8, 4), 42, dtype=np.uint8)
    rgba2 = np.full((8, 8, 4), 42, dtype=np.uint8)
    rgba3 = np.full((8, 8, 4), 99, dtype=np.uint8)

    assert sha1_rgba(rgba1) == sha1_rgba(rgba2)
    assert sha1_rgba(rgba1) != sha1_rgba(rgba3)

    print("  PASSED")


def run_all():
    print("=" * 56)
    print("Pipeline Regression Tests")
    print("=" * 56)
    print()

    tests = [
        test_manifest_schema,
        test_failures_and_unknowns,
        test_summary,
        test_quality_metrics,
        test_contact_sheet,
        test_tex_report,
        test_tex_report_bad_file,
        test_pack_json_generation,
        test_pack_mapped_mode,
        test_import_dump_filename_parsing,
        test_duplicate_detection,
    ]

    passed = failed = 0
    errors = []
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            failed += 1
            errors.append((t.__name__, str(e)))
            print(f"  FAILED: {e}")

    print()
    print("=" * 56)
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)} tests")
    if errors:
        print("\nFailures:")
        for name, err in errors:
            print(f"  {name}: {err}")
    print("=" * 56)
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
