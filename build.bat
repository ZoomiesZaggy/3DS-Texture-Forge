@echo off
echo Installing dependencies...
pip install pillow numpy pyinstaller

echo.
echo Building 3ds-tex-extract.exe...
pyinstaller --onefile --name 3ds-tex-extract main.py

echo.
echo Build complete!
echo Executable: dist\3ds-tex-extract.exe
pause
