"""Entry point for 3DS Texture Forge GUI."""

import sys
from PySide6.QtWidgets import QApplication
from gui_app import MainWindow, apply_dark_palette


def main():
    app = QApplication(sys.argv)
    apply_dark_palette(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
