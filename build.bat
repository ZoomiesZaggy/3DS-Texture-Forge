@echo off
echo ============================================
echo   Building 3DS Texture Forge
echo ============================================
echo.

REM Check Python
python --version 2>nul || (echo ERROR: Python not found. Install Python 3.11+ first. && pause && exit /b 1)

REM Install dependencies
echo Installing dependencies...
pip install PySide6 Pillow numpy pyinstaller --quiet

echo.
echo Building GUI (.exe with no console)...
pyinstaller --onefile --windowed --name "3DS Texture Forge" gui_entry.py --noconfirm

echo.
echo Building CLI (.exe with console)...
pyinstaller --onefile --name "3ds-tex-extract" main.py --noconfirm

echo.
echo ============================================
echo   Build complete!
echo ============================================
echo.
echo   GUI:  dist\3DS Texture Forge.exe
echo   CLI:  dist\3ds-tex-extract.exe
echo.
echo   To use the GUI: double-click "3DS Texture Forge.exe"
echo   To use the CLI: open a terminal and run "3ds-tex-extract.exe"
echo.
pause
