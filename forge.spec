# PyInstaller spec for 3DS Texture Forge (HOME Menu GUI).
#
# Build:  pyinstaller forge.spec
# Output: dist/3DS-Texture-Forge.exe (onefile, windowed)
#
# Notes:
#  - Bundles the rounded font under tex_forge/gui/assets so _asset() finds it at
#    runtime (it checks both the module dir and sys._MEIPASS).
#  - collect_submodules('tex_forge') pulls in every texture/archive/compression
#    plugin, even any imported lazily, so format coverage matches a source run.
#  - Excludes large Qt modules the UI never uses (WebEngine / QML / Multimedia)
#    to keep the exe smaller. The app uses only QtWidgets / QtGui / QtCore.

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

datas = [("tex_forge/gui/assets", "tex_forge/gui/assets")]
# Pillow / numpy / xxhash data files come from their own PyInstaller hooks.

hiddenimports = collect_submodules("tex_forge")
# cityhash is an optional native speedup; azahar_hash has a pure-Python fallback,
# so a missing cityhash must not fail the build.
hiddenimports += ["xxhash"]

excludes = [
    "tkinter",
    "PyQt5",
    "PyQt6",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtQuick",
    "PySide6.QtQml",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.Qt3DCore",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
]

a = Analysis(
    ["forge_gui.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="3DS-Texture-Forge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX can corrupt Qt plugins; leave it off
    runtime_tmpdir=None,
    console=False,  # windowed GUI app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
