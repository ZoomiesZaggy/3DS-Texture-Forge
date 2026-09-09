#!/bin/bash
# 3DS Texture Forge — Mac ARM build script
# Run on an Apple Silicon Mac (M1/M2/M3/M4)
# Requirements: Python 3.10+, pip
#
# Usage:
#   git clone https://github.com/ZoomiesZaggy/3DS-Texture-Forge.git
#   cd 3DS-Texture-Forge
#   bash scripts/build_mac.sh
set -e

echo "=== 3DS Texture Forge — Mac ARM Build ==="
echo ""

# Check Python version
PYTHON="python3"
PY_VER=$($PYTHON --version 2>&1 | grep -oP '\d+\.\d+')
echo "Python version: $PY_VER"

# Create venv
echo "Creating virtual environment..."
$PYTHON -m venv venv_mac
source venv_mac/bin/activate

echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

echo ""
echo "Building CLI binary..."
pyinstaller --onefile \
  --name "3ds-tex-extract-mac" \
  main.py \
  --noconfirm

echo ""
echo "Building GUI binary..."
pyinstaller --onefile --windowed \
  --name "3DS-Texture-Forge-mac" \
  --hidden-import PySide6.QtCore \
  --hidden-import PySide6.QtWidgets \
  --hidden-import PySide6.QtGui \
  gui_entry.py \
  --noconfirm

echo ""
echo "=== Build complete ==="
echo "Binaries are in dist/:"
echo "  dist/3ds-tex-extract-mac     (CLI)"
echo "  dist/3DS-Texture-Forge-mac   (GUI)"
echo ""
echo "To test:"
echo "  ./dist/3ds-tex-extract-mac extract game.3ds -o output/ --quiet"
