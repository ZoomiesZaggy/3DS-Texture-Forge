"""
End-to-end test using a synthetic 3DS ROM fixture.

Builds a minimal valid NCSD+NCCH+RomFS in memory with embedded .tex files,
then runs the full scan/extract/report/build-pack pipeline.
"""

import sys
import os
import json
import struct
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MEDIA_UNIT = 0x200


def _align(val, alignment):
    r = val % alignment
    return val if r == 0 else val + (alignment - r)


def build_romfs_level3(files):
    """
    Build a minimal RomFS Level 3 blob from a dict of {path: bytes}.
    All files go in the root directory for simplicity.
    """
    # Level 3 header: 0x28 bytes
    # dir_hash_table, dir_meta, file_hash_table, file_meta, file_data

    dir_hash_size = 4  # one bucket
    dir_meta_entries = []
    file_meta_entries = []
    file_data_parts = []

    # Root directory entry: parent=0, sibling=FFFFFFFF, first_child=FFFFFFFF, first_file=0
    # name_len=0 (root has no name)
    root_dir = struct.pack("<IIIIiI",
                           0,           # parent
                           0xFFFFFFFF,  # sibling
                           0xFFFFFFFF,  # first child dir
                           0,           # first file (offset in file meta)
                           0,           # hash next
                           0)           # name length

    dir_meta_data = root_dir

    # Build file entries
    file_data_blob = bytearray()
    prev_sibling_fixups = []
    file_entries = list(files.items())

    for idx, (fname, fdata) in enumerate(file_entries):
        name_utf16 = fname.encode("utf-16-le")
        data_offset = len(file_data_blob)
        data_size = len(fdata)
        file_data_blob.extend(fdata)
        # Align file data to 4 bytes
        while len(file_data_blob) % 4 != 0:
            file_data_blob.append(0)

        sibling = 0xFFFFFFFF  # Will fixup

        entry = struct.pack("<I", 0)                          # parent dir offset
        entry += struct.pack("<I", sibling)                    # sibling
        entry += struct.pack("<Q", data_offset)                # data offset (u64)
        entry += struct.pack("<Q", data_size)                  # data size (u64)
        entry += struct.pack("<I", 0)                          # hash next
        entry += struct.pack("<I", len(name_utf16))            # name length
        entry += name_utf16

        # Align entry to 4 bytes
        while len(entry) % 4 != 0:
            entry += b"\x00"

        prev_sibling_fixups.append(len(bytearray().join(file_meta_entries)))
        file_meta_entries.append(entry)

    # Fix sibling pointers (each points to next entry)
    file_meta_blob = bytearray()
    running_offset = 0
    for idx, entry in enumerate(file_meta_entries):
        entry = bytearray(entry)
        if idx + 1 < len(file_meta_entries):
            # Calculate next entry's offset
            next_offset = running_offset + len(entry)
            struct.pack_into("<I", entry, 4, next_offset)
        file_meta_blob.extend(entry)
        running_offset += len(entry)

    # Hash tables (trivial: one bucket pointing to offset 0)
    dir_hash_table = struct.pack("<I", 0)
    file_hash_table = struct.pack("<I", 0)

    # Level 3 header
    header_size = 0x28
    dir_hash_off = header_size
    dir_hash_sz = len(dir_hash_table)
    dir_meta_off = dir_hash_off + dir_hash_sz
    dir_meta_sz = len(dir_meta_data)
    file_hash_off = dir_meta_off + dir_meta_sz
    file_hash_sz = len(file_hash_table)
    file_meta_off = file_hash_off + file_hash_sz
    file_meta_sz = len(file_meta_blob)
    file_data_off = file_meta_off + file_meta_sz

    # RomFS Level 3 header stores offsets relative to after the header (offset 0x28)
    # The parser reads: read_u32_le(data, l3 + field_offset) + l3
    # So the values stored must be absolute-from-L3-start.
    l3_header = struct.pack("<IIIIIIIIII",
                            header_size,
                            dir_hash_off,     # absolute from L3 start
                            dir_hash_sz,
                            dir_meta_off,
                            dir_meta_sz,
                            file_hash_off,
                            file_hash_sz,
                            file_meta_off,
                            file_meta_sz,
                            file_data_off)

    level3 = (bytes(l3_header) + dir_hash_table + dir_meta_data +
              file_hash_table + bytes(file_meta_blob) + bytes(file_data_blob))
    return level3


def build_romfs(files):
    """Build a minimal IVFC RomFS wrapping Level 3 data."""
    level3 = build_romfs_level3(files)

    # We need Level 1 and Level 2 (can be empty/minimal)
    # Just create a valid IVFC header pointing to Level 3 at offset 0x1000

    l3_size = len(level3)
    l2_size = 0x20  # minimal
    l1_size = 0x20  # minimal

    # IVFC header: 0x5C bytes
    ivfc = bytearray(0x5C)
    ivfc[0:4] = b"IVFC"
    struct.pack_into("<I", ivfc, 0x04, 0x00010000)  # magic number

    # Level offsets/sizes (simplistic)
    struct.pack_into("<I", ivfc, 0x2C, l1_size)  # level 1 data size
    struct.pack_into("<I", ivfc, 0x3C, l2_size)  # level 2 data size
    struct.pack_into("<I", ivfc, 0x4C, l3_size)  # level 3 data size

    # Pad to 0x1000 where Level 3 starts
    padding_to_l3 = 0x1000 - len(ivfc)
    result = bytes(ivfc) + b"\x00" * padding_to_l3 + level3
    return result


def build_ncch(romfs_data):
    """Build a minimal NCCH wrapping RomFS data."""
    # NCCH header is 0x200 bytes
    header = bytearray(0x200)
    header[0x100:0x104] = b"NCCH"

    # Content size in media units
    total_size = 0x200 + len(romfs_data)
    total_mu = (total_size + MEDIA_UNIT - 1) // MEDIA_UNIT
    struct.pack_into("<I", header, 0x104, total_mu)

    # Title ID
    struct.pack_into("<Q", header, 0x108, 0x0004000000035D00)

    # Product code
    header[0x150:0x150 + 6] = b"CTR-RE"

    # Crypto flags: set NoCrypto bit
    header[0x18F] = 0x04

    # RomFS offset (in media units, relative to NCCH start)
    romfs_offset_mu = 0x200 // MEDIA_UNIT  # = 1
    romfs_size_mu = (len(romfs_data) + MEDIA_UNIT - 1) // MEDIA_UNIT
    struct.pack_into("<I", header, 0x1B0, romfs_offset_mu)
    struct.pack_into("<I", header, 0x1B4, romfs_size_mu)

    return bytes(header) + romfs_data


def build_ncsd(ncch_data):
    """Build a minimal NCSD wrapping an NCCH partition."""
    # NCSD header occupies the first 0x200 bytes (overlaps with first media unit)
    # The NCCH starts at the partition offset
    header = bytearray(0x200)
    header[0x100:0x104] = b"NCSD"

    # Image size in media units
    total_size = 0x200 + len(ncch_data)
    # Pad to media unit boundary
    while total_size % MEDIA_UNIT != 0:
        total_size += 1

    total_mu = total_size // MEDIA_UNIT
    struct.pack_into("<I", header, 0x104, total_mu)

    # Title ID
    struct.pack_into("<Q", header, 0x108, 0x0004000000035D00)

    # Partition 0: offset = 1 (media unit 1 = byte 0x200), size = NCCH size
    ncch_mu = (len(ncch_data) + MEDIA_UNIT - 1) // MEDIA_UNIT
    struct.pack_into("<I", header, 0x120, 1)         # offset in MU
    struct.pack_into("<I", header, 0x124, ncch_mu)   # size in MU

    result = bytes(header) + ncch_data
    # Pad to total_size
    result += b"\x00" * (total_size - len(result))
    return result


def make_capcom_tex(width, height, fmt_byte=0x0B):
    """Create a synthetic Capcom .tex file with random pixel data."""
    from textures.decoder import calculate_texture_size
    from textures.tex_capcom import CAPCOM_FORMAT_MAP

    pica_fmt = CAPCOM_FORMAT_MAP.get(fmt_byte, fmt_byte)
    data_size = calculate_texture_size(width, height, pica_fmt)

    header = bytearray(16)
    header[0:4] = b"TEX\x00"
    struct.pack_into("<H", header, 0x04, 1)          # version
    struct.pack_into("<H", header, 0x06, width)
    struct.pack_into("<H", header, 0x08, height)
    header[0x0A] = 1                                   # mip count
    header[0x0B] = fmt_byte
    struct.pack_into("<I", header, 0x0C, 16)           # data offset

    pixel_data = os.urandom(data_size)
    return bytes(header) + pixel_data


def run_e2e():
    print("=" * 56)
    print("End-to-End Synthetic ROM Test")
    print("=" * 56)

    # Create synthetic .tex files
    tex1 = make_capcom_tex(64, 64, 0x0B)    # ETC1
    tex2 = make_capcom_tex(128, 128, 0x0C)  # ETC1A4
    tex3 = make_capcom_tex(32, 32, 0x01)    # RGBA8

    files = {
        "body.tex": tex1,
        "skin.tex": tex2,
        "ui_icon.tex": tex3,
    }

    print(f"Built {len(files)} synthetic .tex files")

    # Build ROM
    romfs = build_romfs(files)
    ncch = build_ncch(romfs)
    ncsd = build_ncsd(ncch)

    print(f"Synthetic ROM size: {len(ncsd):,} bytes")

    # Write to temp file
    tmpdir = tempfile.mkdtemp(prefix="3ds_e2e_")
    rom_path = os.path.join(tmpdir, "synthetic_re_rev.3ds")
    out_dir = os.path.join(tmpdir, "output")

    with open(rom_path, "wb") as f:
        f.write(ncsd)

    try:
        # --- Test scan ---
        print("\n--- Running: scan ---")
        import subprocess
        r = subprocess.run(
            [sys.executable, "main.py", "scan", rom_path, "--verbose"],
            capture_output=True, text=True, cwd=os.path.dirname(__file__)
        )
        print(r.stdout)
        if r.stderr:
            for line in r.stderr.strip().split("\n")[-5:]:
                print(f"  [log] {line}")
        assert r.returncode == 0, f"scan failed: {r.stderr[-200:]}"
        print("  scan: OK")

        # --- Test extract ---
        print("\n--- Running: extract ---")
        r = subprocess.run(
            [sys.executable, "main.py", "extract", rom_path, "-o", out_dir, "--verbose"],
            capture_output=True, text=True, cwd=os.path.dirname(__file__)
        )
        print(r.stdout)
        if r.stderr:
            for line in r.stderr.strip().split("\n")[-5:]:
                print(f"  [log] {line}")
        assert r.returncode == 0, f"extract failed: {r.stderr[-200:]}"

        # Check outputs exist
        assert os.path.isfile(os.path.join(out_dir, "manifest.json")), "manifest.json missing"
        assert os.path.isfile(os.path.join(out_dir, "failures.json")), "failures.json missing"
        assert os.path.isfile(os.path.join(out_dir, "unknown_files.json")), "unknown_files.json missing"
        assert os.path.isfile(os.path.join(out_dir, "summary.json")), "summary.json missing"

        with open(os.path.join(out_dir, "manifest.json"), "r") as f:
            m = json.load(f)
        print(f"  Manifest: {m['texture_count']} textures, schema v{m['schema_version']}")
        assert m["texture_count"] > 0, "No textures extracted!"

        # Verify contact sheet
        cs = os.path.join(out_dir, "contact_sheet.png")
        if os.path.isfile(cs):
            print(f"  Contact sheet: {os.path.getsize(cs):,} bytes")
        else:
            print("  Contact sheet: not generated (acceptable if < 1 texture)")

        # Check TEX report
        tex_report = os.path.join(out_dir, "re_revelations_tex_report.json")
        if os.path.isfile(tex_report):
            with open(tex_report, "r") as f:
                tr = json.load(f)
            print(f"  TEX report: {tr['tex_files_found']} files, "
                  f"{tr['parsed']} parsed, {tr['failed']} failed")
        print("  extract: OK")

        # --- Test report ---
        print("\n--- Running: report ---")
        r = subprocess.run(
            [sys.executable, "main.py", "report", out_dir],
            capture_output=True, text=True, cwd=os.path.dirname(__file__)
        )
        print(r.stdout)
        assert r.returncode == 0, f"report failed: {r.stderr[-200:]}"
        print("  report: OK")

        # --- Test build-pack ---
        print("\n--- Running: build-pack ---")
        r = subprocess.run(
            [sys.executable, "main.py", "build-pack", out_dir],
            capture_output=True, text=True, cwd=os.path.dirname(__file__)
        )
        print(r.stdout)
        assert r.returncode == 0, f"build-pack failed: {r.stderr[-200:]}"

        pack_json_glob = []
        for root, dirs, fnames in os.walk(out_dir):
            for fn in fnames:
                if fn == "pack.json":
                    pack_json_glob.append(os.path.join(root, fn))
        assert len(pack_json_glob) > 0, "No pack.json found"
        with open(pack_json_glob[0], "r") as f:
            pj = json.load(f)
        assert pj["pack_mode"] == "staging"
        print(f"  Pack mode: {pj['pack_mode']}, textures: {pj['texture_count']}")
        print("  build-pack: OK")

        print("\n" + "=" * 56)
        print("ALL E2E TESTS PASSED")
        print("=" * 56)
        return True

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    ok = run_e2e()
    sys.exit(0 if ok else 1)
