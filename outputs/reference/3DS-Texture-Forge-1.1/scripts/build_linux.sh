#!/bin/bash
# 3DS Texture Forge — Linux build script (run inside WSL or native Linux)
set -e
export WSLENV=""
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

echo "=== Installing pip (user-level, no sudo) ==="
python3 -m pip --version 2>/dev/null || {
    echo "Bootstrapping pip..."
    python3 -c "import urllib.request; urllib.request.urlretrieve('https://bootstrap.pypa.io/get-pip.py', '/tmp/get-pip.py')"
    python3 /tmp/get-pip.py --user --break-system-packages 2>&1 | tail -3
}
export PATH="$HOME/.local/bin:$PATH"

echo "=== Installing Python dependencies ==="
pip3 install --user --break-system-packages -r requirements.txt 2>&1 | tail -5
pip3 install --user --break-system-packages pyinstaller 2>&1 | tail -3

echo "=== Building CLI binary ==="
pyinstaller --onefile \
  --name "3ds-tex-extract-linux" \
  main.py \
  --noconfirm

echo "=== Building GUI binary ==="
pyinstaller --onefile \
  --name "3DS-Texture-Forge-linux" \
  --hidden-import PySide6.QtCore \
  --hidden-import PySide6.QtWidgets \
  --hidden-import PySide6.QtGui \
  gui_entry.py \
  --noconfirm

echo "=== Build complete ==="
ls -lh dist/3ds-tex-extract-linux dist/3DS-Texture-Forge-linux 2>/dev/null || echo "Check dist/ for binaries"
