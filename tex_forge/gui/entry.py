"""GUI entry point: `python -m tex_forge.gui.entry`.

Launches the 3DS HOME Menu UI (home_menu.HomeMenuWindow). The vendored v1 UI
(_gui_app_v1.py) is kept in the tree for reference but is no longer the default.
"""

from __future__ import annotations


def main() -> int:
    # Import inside the function so callers without PySide6 can still import
    # tex_forge.gui (e.g. for backend.py) without immediately failing.
    import sys
    try:
        from PySide6.QtWidgets import QApplication  # noqa: F401
    except ImportError:
        print("PySide6 not installed. Run `pip install tex-forge[gui]`.",
              file=sys.stderr)
        return 1

    from tex_forge.gui.home_menu import main as run_home_menu
    return run_home_menu()


if __name__ == "__main__":
    raise SystemExit(main())
