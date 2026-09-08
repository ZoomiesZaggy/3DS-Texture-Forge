"""Loader encrypted-path handling and GUI backend multi-content wiring.

Two clusters:

1. Loader: that `iter_rom_contents` preserves the EncryptedROMError signal
   (so the GodMode9 hint survives) instead of masking it as a generic parse
   failure -- for both an encrypted single container and a fully-encrypted
   CIA. Uses a minimal hand-built NCCH (just enough header for NCCHParser to
   reach its crypto check) wrapped in the synthetic CIA from the CIA tests.

2. GUI backend: that scan_rom sums file counts across contents and reports
   content_count, and that run_extraction forwards extra contents into the
   pipeline. The pipeline is stubbed so these stay fast unit tests of the
   wiring, not a second copy of the extraction e2e.
"""

import struct
import tempfile

import pytest

import tex_forge.gui.backend as backend
from tex_forge.core.exceptions import EncryptedROMError, ROMParseError
from tex_forge.rom.loader import content_label_from_chain, iter_rom_contents


# ── helpers: minimal NCCH + CIA ──────────────────────────────────────────────

def _ncch(encrypted: bool, has_romfs: bool) -> bytes:
    """A 0x400-byte NCCH header sufficient for NCCHParser + get_romfs()."""
    buf = bytearray(b"\x00" * 0x400)
    buf[0x100:0x104] = b"NCCH"
    buf[0x108:0x110] = struct.pack("<Q", 0x0004000000055D00)
    pc = b"CTR-P-TEST"
    buf[0x150:0x150 + len(pc)] = pc
    # flags[7] bit2 (0x04) = NoCrypto. Set it for a decrypted content.
    buf[0x18F] = 0x00 if encrypted else 0x04
    if has_romfs:
        buf[0x1B0:0x1B4] = struct.pack("<I", 0x10)   # romfs offset (media units)
        buf[0x1B4:0x1B8] = struct.pack("<I", 0x01)   # romfs size
    return bytes(buf)


def _cia(contents) -> bytes:
    """contents: list of (type_flags, ncch_bytes). Reuses the CIA layout the
    parser tests exercise: header/cert/ticket/TMD, 64-byte aligned, with one
    TMD chunk record per content."""
    def be16(v): return struct.pack(">H", v)
    def be32(v): return struct.pack(">I", v)
    def be64(v): return struct.pack(">Q", v)
    def le32(v): return struct.pack("<I", v)

    def pad64(b):
        while len(b) % 64:
            b.append(0)

    tmd = bytearray()
    tmd += be32(0x00010004)
    tmd += b"\x00" * (0x100 + 0x3C)
    header = bytearray(b"\x00" * 0xC4)
    header[0x9E:0xA0] = be16(len(contents))
    tmd += header
    tmd += b"\x00" * 0x900
    for i, (tflags, data) in enumerate(contents):
        rec = bytearray(b"\x00" * 0x30)
        rec[0x00:0x04] = be32(i)
        rec[0x04:0x06] = be16(i)
        rec[0x06:0x08] = be16(tflags)
        rec[0x08:0x10] = be64(len(data))
        tmd += rec

    cert = b"CERT" * 4
    ticket = b"TIK!" * 4
    head = bytearray(b"\x00" * 0x20)
    head[0x00:0x04] = le32(0x20)
    head[0x08:0x0C] = le32(len(cert))
    head[0x0C:0x10] = le32(len(ticket))
    head[0x10:0x14] = le32(len(tmd))

    out = bytearray(head); pad64(out)
    out += cert; pad64(out)
    out += ticket; pad64(out)
    out += tmd; pad64(out)
    for _tf, data in contents:
        out += data; pad64(out)
    return bytes(out)


def _write_tmp(data: bytes, suffix: str) -> str:
    f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    f.write(data)
    f.close()
    return f.name


# ── loader tests ─────────────────────────────────────────────────────────────

def test_label_helper():
    assert content_label_from_chain("CIA/content0(main)/NCCH/RomFS") == "content0(main)"
    assert content_label_from_chain("CIA/content3(DLC)/NCCH/RomFS") == "content3(DLC)"
    assert content_label_from_chain("NCSD/partition0/NCCH/RomFS") == ""


def test_encrypted_single_container_preserves_signal(monkeypatch):
    def fake_parse_rom(path):
        raise EncryptedROMError("encrypted")
    monkeypatch.setattr("tex_forge.rom.loader.parse_rom", fake_parse_rom)
    with pytest.raises(EncryptedROMError):
        list(iter_rom_contents("game.3ds"))


def test_fully_encrypted_cia_raises_encrypted_not_parse_error():
    cia = _cia([(0x0001, _ncch(encrypted=True, has_romfs=True))])
    path = _write_tmp(cia, ".cia")
    with pytest.raises(EncryptedROMError):
        list(iter_rom_contents(path))


def test_cia_with_no_romfs_content_raises_parse_error():
    cia = _cia([(0x0000, _ncch(encrypted=False, has_romfs=False))])
    path = _write_tmp(cia, ".cia")
    with pytest.raises(ROMParseError):
        list(iter_rom_contents(path))


# ── GUI backend tests ────────────────────────────────────────────────────────

class _FakeRomFS:
    def __init__(self, data):
        self._n = data  # data is an int = how many files to fake

    def list_files(self):
        return [(f"a/0/0/{i}", 0x100, 16) for i in range(self._n)]


def test_scan_rom_sums_contents(monkeypatch):
    contents = [
        (3, "TID0", "CTR-P-A", "CIA/content0(main)/NCCH/RomFS"),
        (5, "TID0", "CTR-P-A", "CIA/content1(DLC)/NCCH/RomFS"),
    ]
    monkeypatch.setattr(backend, "iter_rom_contents", lambda p: iter(contents))
    monkeypatch.setattr(backend, "RomFSParser", _FakeRomFS)

    res = backend.scan_rom("x.cia")
    assert res["success"] is True
    assert res["content_count"] == 2
    assert res["file_count"] == 8            # 3 + 5
    assert res["chain"].endswith("content0(main)/NCCH/RomFS")
    assert len(res["romfs_files_preview"]) == 3


def test_scan_rom_encrypted_flag(monkeypatch):
    def boom(p):
        raise EncryptedROMError("nope")
    monkeypatch.setattr(backend, "iter_rom_contents", boom)
    res = backend.scan_rom("x.3ds")
    assert res["is_encrypted"] is True
    assert res["success"] is False


def test_run_extraction_forwards_extra_contents(monkeypatch):
    contents = [
        (b"main", "TID0", "CTR-P-A", "CIA/content0(main)/NCCH/RomFS"),
        (b"dlc",  "TID0", "CTR-P-A", "CIA/content1(DLC)/NCCH/RomFS"),
    ]
    monkeypatch.setattr(backend, "iter_rom_contents", lambda p: iter(contents))

    captured = {}

    class _FakePipe:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.records = [1, 2]
            self.failures = []

        def run(self):
            return {"textures_decoded_ok": 2, "content_count": 2}

    monkeypatch.setattr(backend, "ExtractionPipeline", _FakePipe)

    with tempfile.TemporaryDirectory() as td:
        res = backend.run_extraction("x.cia", td, {"output_mode": "azahar"})

    assert res["success"] is True
    assert res["content_count"] == 2
    assert captured["content_source"] == "content0(main)"
    assert len(captured["extra_contents"]) == 1
    assert captured["extra_contents"][0].source_content == "content1(DLC)"
    assert captured["chain"] == "CIA/content0(main)/NCCH/RomFS"
