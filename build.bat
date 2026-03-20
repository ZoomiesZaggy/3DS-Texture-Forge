@echo off
echo === Building 3DS Texture Forge ===

REM Install dependencies
pip install PySide6 Pillow numpy pyinstaller

REM Build GUI exe (no console window)
echo.
echo Building GUI...
pyinstaller --onefile --windowed --name "3DS Texture Forge" gui_entry.py

REM Also build CLI exe (with console)
echo.
echo Building CLI...
pyinstaller --onefile --name "3ds-tex-extract" main.py

echo.
echo Build complete.
echo GUI: dist\3DS Texture Forge.exe
echo CLI: dist\3ds-tex-extract.exe
pause
