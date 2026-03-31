#!/bin/bash
# 3DS Texture Forge — Linux build script (run inside WSL or native Linux)
set -e
export WSLENV=""
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

echo "=== Installing system dependencies ==="
sudo apt-get update -qq
sudo apt-get install -y -qq python3-pip python3-venv python3-dev

echo "=== Setting up venv ==="
cd /mnt/c/claude/3ds-tex-extract
rm -rf venv_linux
python3 -m venv venv_linux
source venv_linux/bin/activate

echo "=== Installing Python dependencies ==="
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

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
