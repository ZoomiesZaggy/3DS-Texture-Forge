"""Frozen-app launcher for the 3DS Texture Forge HOME Menu GUI.

PyInstaller needs a real script as its entry point (not a module). This simply
delegates to tex_forge.gui.entry.main so the packaged exe and `python -m
tex_forge.gui.entry` share one code path.
"""

from tex_forge.gui.entry import main

if __name__ == "__main__":
    raise SystemExit(main())
