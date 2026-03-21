"""
3DS Texture Forge — PySide6 GUI.

Grandma-proof: step-by-step flow, giant drop zone, one big button.
"""

import logging
import os
import re
import sys
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal, QUrl, QMimeData, QTimer
from PySide6.QtGui import (
    QColor, QDesktopServices, QDragEnterEvent, QDropEvent,
    QFont, QIcon, QPalette, QPixmap, QPainter, QPen, QAction, QCursor,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSpacerItem,
    QVBoxLayout, QWidget, QDialog, QTextBrowser,
)

from config import load_config, save_config
from backend import scan_rom, run_extraction, get_output_previews, get_game_name

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────

COL_BG = "#2d2d30"
COL_BG_DARKER = "#1e1e1e"
COL_TEXT = "#d4d4d4"
COL_TEXT_DIM = "#808080"
COL_ACCENT = "#2a82da"
COL_ACCENT_HOVER = "#3a92ea"
COL_GREEN = "#4ec96b"
COL_GREEN_DIM = "#2a6b3a"
COL_RED = "#ff6b6b"
COL_ORANGE = "#ffaa44"
COL_BORDER = "#555555"
COL_DROP_BORDER = "#888888"
COL_DROP_HOVER = "#2a82da"


# ──────────────────────────────────────────────
# Logging handler
# ──────────────────────────────────────────────

class SignalLogHandler(logging.Handler):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def emit(self, record):
        try:
            self.callback(self.format(record))
        except Exception:
            pass


# ──────────────────────────────────────────────
# Worker: combined scan + extract in one step
# ──────────────────────────────────────────────

class ExtractWorker(QThread):
    finished = Signal(dict)
    progress = Signal(int, int, str)
    log_message = Signal(str)
    phase_changed = Signal(str)

    def __init__(self, filepath: str, output_dir: str, options: dict):
        super().__init__()
        self.filepath = filepath
        self.output_dir = output_dir
        self.options = options

    def _on_progress(self, current, total, file_path, fmt_name, w, h):
        self.progress.emit(current, total, file_path)

    def run(self):
        self.phase_changed.emit("Loading ROM...")
        self.log_message.emit(f"Loading: {os.path.basename(self.filepath)}")

        # Phase 1: scan
        scan_result = scan_rom(self.filepath)
        if not scan_result["success"]:
            result = {
                "success": False,
                "error_message": scan_result["error_message"],
                "is_encrypted": scan_result.get("is_encrypted", False),
                "scan_result": scan_result,
            }
            self.finished.emit(result)
            return

        game_name = get_game_name(
            scan_result.get("title_id", ""),
            scan_result.get("product_code", ""),
        )
        self.phase_changed.emit(f"Extracting textures from {game_name}...")
        self.log_message.emit(
            f"ROM: {game_name} | {scan_result['product_code']} | "
            f"{scan_result['file_count']} files"
        )

        # Phase 2: extract
        result = run_extraction(
            self.filepath, self.output_dir, self.options,
            progress_callback=self._on_progress,
        )
        result["scan_result"] = scan_result
        result["game_name"] = game_name
        self.finished.emit(result)


# ──────────────────────────────────────────────
# Dark palette
# ──────────────────────────────────────────────

def apply_dark_palette(app: QApplication):
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(45, 45, 48))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(212, 212, 212))
    palette.setColor(QPalette.ColorRole.Base, QColor(30, 30, 30))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(45, 45, 48))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(45, 45, 48))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(212, 212, 212))
    palette.setColor(QPalette.ColorRole.Text, QColor(212, 212, 212))
    palette.setColor(QPalette.ColorRole.Button, QColor(55, 55, 58))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(212, 212, 212))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text,
                     QColor(128, 128, 128))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText,
                     QColor(128, 128, 128))
    app.setPalette(palette)
    app.setStyle("Fusion")


# ──────────────────────────────────────────────
# Drop Zone widget
# ──────────────────────────────────────────────

class DropZone(QFrame):
    """Large drag-and-drop target that also responds to clicks."""

    file_dropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setMinimumHeight(130)
        self._hovering = False
        self._loaded_file = ""
        self._game_info = ""
        self._update_style(False)

    def _update_style(self, hover: bool):
        if self._loaded_file:
            self.setStyleSheet(f"""
                DropZone {{
                    background: {COL_BG_DARKER};
                    border: 2px solid {COL_GREEN_DIM};
                    border-radius: 8px;
                }}
            """)
        elif hover:
            self.setStyleSheet(f"""
                DropZone {{
                    background: #1a3a5a;
                    border: 2px dashed {COL_DROP_HOVER};
                    border-radius: 8px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                DropZone {{
                    background: {COL_BG_DARKER};
                    border: 2px dashed {COL_DROP_BORDER};
                    border-radius: 8px;
                }}
            """)

    def set_loaded(self, filepath: str, game_info: str = ""):
        self._loaded_file = filepath
        self._game_info = game_info
        self._update_style(False)
        self.update()

    def clear(self):
        self._loaded_file = ""
        self._game_info = ""
        self._update_style(False)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()

        if self._loaded_file:
            # Show loaded file info
            fname = os.path.basename(self._loaded_file)

            # Checkmark
            painter.setPen(QPen(QColor(COL_GREEN), 2))
            font_big = QFont("Segoe UI", 13, QFont.Weight.Bold)
            painter.setFont(font_big)
            painter.drawText(rect.adjusted(0, 20, 0, -40),
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                             f"  {fname}")

            if self._game_info:
                painter.setPen(QColor(COL_TEXT_DIM))
                font_sm = QFont("Segoe UI", 10)
                painter.setFont(font_sm)
                painter.drawText(rect.adjusted(0, 50, 0, -10),
                                 Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                                 self._game_info)

            # Small "click to change" hint
            painter.setPen(QColor(COL_TEXT_DIM))
            font_xs = QFont("Segoe UI", 9)
            painter.setFont(font_xs)
            painter.drawText(rect.adjusted(0, 0, 0, -10),
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                             "Click or drop to change file")
        else:
            # Empty state
            painter.setPen(QColor(COL_TEXT_DIM))
            font_main = QFont("Segoe UI", 14)
            painter.setFont(font_main)
            painter.drawText(rect.adjusted(0, 25, 0, -30),
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                             "Drop your .3ds or .cia ROM file here")

            font_sub = QFont("Segoe UI", 10)
            painter.setFont(font_sub)
            painter.drawText(rect.adjusted(0, 55, 0, -10),
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                             "or click to browse")

        painter.end()

    def mousePressEvent(self, event):
        self.file_dropped.emit("")  # Signal parent to open browse dialog

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                path = url.toLocalFile().lower()
                if path.endswith((".3ds", ".cia", ".cxi", ".app")):
                    event.acceptProposedAction()
                    self._hovering = True
                    self._update_style(True)
                    return

    def dragLeaveEvent(self, event):
        self._hovering = False
        self._update_style(False)

    def dropEvent(self, event: QDropEvent):
        self._hovering = False
        self._update_style(False)
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith((".3ds", ".cia", ".cxi", ".app")):
                self.file_dropped.emit(path)
                return
        # Non-ROM file dropped
        self.file_dropped.emit(event.mimeData().urls()[0].toLocalFile()
                               if event.mimeData().urls() else "")


# ──────────────────────────────────────────────
# Collapsible section
# ──────────────────────────────────────────────

class CollapsibleSection(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._expanded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._toggle_btn = QPushButton(f"  {title}")
        self._toggle_btn.setStyleSheet(f"""
            QPushButton {{
                text-align: left;
                background: transparent;
                border: none;
                color: {COL_TEXT_DIM};
                font-size: 12px;
                padding: 6px 4px;
            }}
            QPushButton:hover {{
                color: {COL_TEXT};
            }}
        """)
        self._toggle_btn.clicked.connect(self.toggle)
        layout.addWidget(self._toggle_btn)

        self._content = QWidget()
        self._content.setVisible(False)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(16, 4, 0, 8)
        layout.addWidget(self._content)

        self._title = title

    def content_layout(self):
        return self._content_layout

    def toggle(self):
        self._expanded = not self._expanded
        self._content.setVisible(self._expanded)
        arrow = "" if self._expanded else ""
        self._toggle_btn.setText(f"{arrow}  {self._title}")

    def set_expanded(self, expanded: bool):
        self._expanded = expanded
        self._content.setVisible(expanded)
        arrow = "" if self._expanded else ""
        self._toggle_btn.setText(f"{arrow}  {self._title}")


# ──────────────────────────────────────────────
# Step indicator
# ──────────────────────────────────────────────

class StepLabel(QLabel):
    """A numbered step label that can be active, done, or dimmed."""

    def __init__(self, number: int, text: str, parent=None):
        super().__init__(parent)
        self._number = number
        self._text = text
        self._state = "upcoming"  # "upcoming", "active", "done"
        self._render()

    def set_state(self, state: str):
        self._state = state
        self._render()

    def _render(self):
        num = self._number
        if self._state == "done":
            circle = f'<span style="color:{COL_GREEN}; font-size:15px;">&#10004;</span>'
            color = COL_TEXT_DIM
        elif self._state == "active":
            circle = f'<span style="color:{COL_ACCENT}; font-size:15px; font-weight:bold;">{num}</span>'
            color = COL_TEXT
        else:
            circle = f'<span style="color:{COL_TEXT_DIM}; font-size:15px;">{num}</span>'
            color = COL_TEXT_DIM

        self.setText(
            f'<span style="font-size:13px;">{circle}</span>'
            f'&nbsp;&nbsp;'
            f'<span style="color:{color}; font-size:13px;">{self._text}</span>'
        )


# ──────────────────────────────────────────────
# About dialog
# ──────────────────────────────────────────────

class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About 3DS Texture Forge")
        self.setFixedSize(480, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)

        text = QTextBrowser()
        text.setOpenExternalLinks(True)
        text.setStyleSheet(f"background: {COL_BG_DARKER}; border: none; color: {COL_TEXT};")
        text.setHtml(f"""
            <h2 style="color:{COL_TEXT};">3DS Texture Forge v1.0</h2>
            <p>Extracts textures from decrypted Nintendo 3DS game ROMs.
            Textures are saved as PNG files organized by source.</p>

            <p><b>Tested games:</b></p>
            <table cellspacing="4">
            <tr><td style="color:{COL_GREEN};">&#10004;</td>
                <td>Resident Evil: Revelations</td><td style="color:{COL_TEXT_DIM};">1,137 textures</td></tr>
            <tr><td style="color:{COL_GREEN};">&#10004;</td>
                <td>Corpse Party</td><td style="color:{COL_TEXT_DIM};">2,781 textures</td></tr>
            <tr><td style="color:{COL_GREEN};">&#10004;</td>
                <td>Pokemon Y</td><td style="color:{COL_TEXT_DIM};">8,015 textures</td></tr>
            <tr><td style="color:{COL_GREEN};">&#10004;</td>
                <td>Mario Kart 7</td><td style="color:{COL_TEXT_DIM};">2,770 textures</td></tr>
            <tr><td style="color:{COL_GREEN};">&#10004;</td>
                <td>Zelda: Ocarina of Time 3D</td><td style="color:{COL_TEXT_DIM};">3,584 textures</td></tr>
            </table>

            <p style="margin-top:12px;"><b>For Azahar/Citra custom textures:</b><br>
            Use the emulator's texture dump feature to get hash-based filenames,
            then replace them with these extracted textures.</p>

            <p style="margin-top:12px;">
            <a href="https://github.com/ZoomiesZaggy/3DS-Texture-Forge">
            github.com/ZoomiesZaggy/3DS-Texture-Forge</a></p>
        """)
        layout.addWidget(text)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        layout.addWidget(btn_close, alignment=Qt.AlignmentFlag.AlignRight)


# ──────────────────────────────────────────────
# Main Window
# ──────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.worker = None
        self._loaded_path = ""
        self._scan_result = None
        self._game_name = ""

        self.setWindowTitle("3DS Texture Forge")
        self._set_window_icon()
        self.setMinimumSize(800, 600)
        self.resize(self.cfg.get("window_width", 1000),
                    self.cfg.get("window_height", 720))
        self.setAcceptDrops(True)

        self._build_ui()
        self._setup_logging()
        self._update_steps("idle")

    def _set_window_icon(self):
        """Set the window icon, checking PyInstaller bundle path first."""
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(base_path, 'icon.ico')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

    # ── Logging ──

    def _setup_logging(self):
        handler = SignalLogHandler(self._log_from_handler)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logging.root.addHandler(handler)
        logging.root.setLevel(logging.INFO)

    def _log_from_handler(self, msg: str):
        if QThread.currentThread() == QApplication.instance().thread():
            self._append_log(msg)

    def _append_log(self, msg: str):
        self.log_box.appendPlainText(msg)
        sb = self.log_box.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ── UI Construction ──

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(24, 16, 24, 12)
        main_layout.setSpacing(6)

        # ── Title bar area ──
        title_bar = QHBoxLayout()
        title_lbl = QLabel(
            f'<span style="color:{COL_TEXT}; font-size:18px; font-weight:bold;">'
            f'3DS Texture Forge</span>'
        )
        title_bar.addWidget(title_lbl)
        title_bar.addStretch()
        self.btn_about = QPushButton("About")
        self.btn_about.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none;
                color: {COL_TEXT_DIM}; font-size: 12px;
                padding: 4px 8px;
            }}
            QPushButton:hover {{ color: {COL_ACCENT}; }}
        """)
        self.btn_about.clicked.connect(self._show_about)
        title_bar.addWidget(self.btn_about)
        main_layout.addLayout(title_bar)

        # ── Separator ──
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {COL_BORDER};")
        main_layout.addWidget(sep)
        main_layout.addSpacing(4)

        # ── How to Use header ──
        how_lbl = QLabel(
            f'<span style="color:{COL_TEXT_DIM}; font-size:11px; '
            f'letter-spacing:2px;">HOW TO USE</span>'
        )
        main_layout.addWidget(how_lbl)
        main_layout.addSpacing(2)

        # ── Step 1 ──
        self.step1 = StepLabel(1, "Get a decrypted .3ds or .cia ROM file")
        main_layout.addWidget(self.step1)
        hint1 = QLabel(
            f'<span style="color:{COL_TEXT_DIM}; font-size:11px;">'
            f'&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;'
            f'You need a legally dumped ROM decrypted with GodMode9</span>'
        )
        main_layout.addWidget(hint1)
        main_layout.addSpacing(2)

        # ── Step 2 + Drop Zone ──
        self.step2 = StepLabel(2, "Drop your ROM file here")
        main_layout.addWidget(self.step2)
        main_layout.addSpacing(4)

        self.drop_zone = DropZone()
        self.drop_zone.file_dropped.connect(self._on_file_dropped)
        main_layout.addWidget(self.drop_zone)
        main_layout.addSpacing(4)

        # ── Step 3 + Extract button ──
        self.step3 = StepLabel(3, "Click Extract and wait")
        main_layout.addWidget(self.step3)
        main_layout.addSpacing(4)

        # Extract button + output path row
        action_row = QHBoxLayout()
        self.btn_extract = QPushButton("   EXTRACT TEXTURES   ")
        self.btn_extract.setMinimumHeight(44)
        self.btn_extract.setEnabled(False)
        self.btn_extract.setStyleSheet(f"""
            QPushButton {{
                background-color: {COL_ACCENT};
                color: white;
                font-weight: bold;
                font-size: 14px;
                padding: 8px 32px;
                border-radius: 6px;
                border: none;
            }}
            QPushButton:hover {{
                background-color: {COL_ACCENT_HOVER};
            }}
            QPushButton:disabled {{
                background-color: #3a3a3d;
                color: {COL_TEXT_DIM};
            }}
        """)
        self.btn_extract.clicked.connect(self._do_extract)
        action_row.addWidget(self.btn_extract)
        action_row.addStretch()
        main_layout.addLayout(action_row)

        # Output path (shown after file loaded)
        self.output_row = QWidget()
        output_hl = QHBoxLayout(self.output_row)
        output_hl.setContentsMargins(0, 0, 0, 0)
        self.lbl_output = QLabel(
            f'<span style="color:{COL_TEXT_DIM}; font-size:11px;">Output:</span>'
        )
        output_hl.addWidget(self.lbl_output)
        self.lbl_output_path = QLabel("")
        self.lbl_output_path.setStyleSheet(f"color: {COL_TEXT}; font-size: 11px;")
        output_hl.addWidget(self.lbl_output_path)
        self.btn_change_output = QPushButton("Change")
        self.btn_change_output.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none;
                color: {COL_ACCENT}; font-size: 11px;
                padding: 2px 6px;
            }}
            QPushButton:hover {{ text-decoration: underline; }}
        """)
        self.btn_change_output.clicked.connect(self._browse_output)
        output_hl.addWidget(self.btn_change_output)
        output_hl.addStretch()
        self.output_row.setVisible(False)
        main_layout.addWidget(self.output_row)

        # Progress bar (hidden until extracting)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumHeight(18)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: {COL_BG_DARKER};
                border: 1px solid {COL_BORDER};
                border-radius: 4px;
                text-align: center;
                color: {COL_TEXT};
                font-size: 11px;
            }}
            QProgressBar::chunk {{
                background: {COL_ACCENT};
                border-radius: 3px;
            }}
        """)
        main_layout.addWidget(self.progress_bar)

        self.lbl_progress_text = QLabel("")
        self.lbl_progress_text.setStyleSheet(f"color: {COL_TEXT_DIM}; font-size: 11px;")
        self.lbl_progress_text.setVisible(False)
        main_layout.addWidget(self.lbl_progress_text)

        main_layout.addSpacing(4)

        # ── Step 4 + Results ──
        self.step4 = StepLabel(4, "Get your textures")
        main_layout.addWidget(self.step4)
        main_layout.addSpacing(4)

        # Results panel (hidden until extraction complete)
        self.results_panel = QFrame()
        self.results_panel.setStyleSheet(f"""
            QFrame {{
                background: {COL_BG_DARKER};
                border: 1px solid {COL_BORDER};
                border-radius: 8px;
            }}
        """)
        self.results_panel.setVisible(False)
        results_layout = QVBoxLayout(self.results_panel)
        results_layout.setContentsMargins(16, 12, 16, 12)
        results_layout.setSpacing(8)

        self.lbl_results_headline = QLabel("")
        self.lbl_results_headline.setStyleSheet(f"font-size: 14px; font-weight: bold; border: none;")
        results_layout.addWidget(self.lbl_results_headline)

        self.lbl_results_detail = QLabel("")
        self.lbl_results_detail.setStyleSheet(f"color: {COL_TEXT_DIM}; font-size: 11px; border: none;")
        self.lbl_results_detail.setVisible(False)
        results_layout.addWidget(self.lbl_results_detail)

        # Action buttons row
        btn_row = QHBoxLayout()
        self.btn_open_folder = QPushButton("   Open Output Folder   ")
        self.btn_open_folder.setMinimumHeight(36)
        self.btn_open_folder.setStyleSheet(f"""
            QPushButton {{
                background-color: {COL_GREEN_DIM};
                color: white;
                font-weight: bold;
                font-size: 12px;
                padding: 6px 20px;
                border-radius: 5px;
                border: none;
            }}
            QPushButton:hover {{
                background-color: {COL_GREEN};
                color: black;
            }}
        """)
        self.btn_open_folder.clicked.connect(self._open_output_folder)
        btn_row.addWidget(self.btn_open_folder)

        self.btn_manifest = QPushButton("   View Manifest   ")
        self.btn_manifest.setMinimumHeight(36)
        self.btn_manifest.setStyleSheet(f"""
            QPushButton {{
                background-color: #3a3a3d;
                color: {COL_TEXT};
                font-size: 12px;
                padding: 6px 16px;
                border-radius: 5px;
                border: 1px solid {COL_BORDER};
            }}
            QPushButton:hover {{
                background-color: #4a4a4d;
            }}
        """)
        self.btn_manifest.clicked.connect(self._open_manifest)
        btn_row.addWidget(self.btn_manifest)
        btn_row.addStretch()
        results_layout.addLayout(btn_row)

        # Thumbnail area
        self.thumb_scroll = QScrollArea()
        self.thumb_scroll.setWidgetResizable(True)
        self.thumb_scroll.setMinimumHeight(80)
        self.thumb_scroll.setMaximumHeight(120)
        self.thumb_scroll.setStyleSheet(f"background: transparent; border: none;")
        self.thumb_widget = QWidget()
        self.thumb_widget.setStyleSheet("border: none;")
        self.thumb_layout = QHBoxLayout(self.thumb_widget)
        self.thumb_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.thumb_layout.setSpacing(6)
        self.thumb_scroll.setWidget(self.thumb_widget)
        results_layout.addWidget(self.thumb_scroll)

        main_layout.addWidget(self.results_panel)

        # ── Error panel (hidden) ──
        self.error_panel = QFrame()
        self.error_panel.setStyleSheet(f"""
            QFrame {{
                background: #3a1a1a;
                border: 1px solid {COL_RED};
                border-radius: 8px;
            }}
        """)
        self.error_panel.setVisible(False)
        error_layout = QVBoxLayout(self.error_panel)
        error_layout.setContentsMargins(16, 12, 16, 12)
        self.lbl_error = QLabel("")
        self.lbl_error.setWordWrap(True)
        self.lbl_error.setStyleSheet(f"color: {COL_TEXT}; font-size: 12px; border: none;")
        error_layout.addWidget(self.lbl_error)
        main_layout.addWidget(self.error_panel)

        main_layout.addStretch()

        # ── Advanced Options (collapsed) ──
        self.advanced_section = CollapsibleSection("Advanced Options")
        adv_layout = self.advanced_section.content_layout()
        self.chk_scan_all = QCheckBox("Deep scan — Try harder to find textures (slower)")
        self.chk_scan_all.setStyleSheet(f"color: {COL_TEXT}; font-size: 11px;")
        adv_layout.addWidget(self.chk_scan_all)
        self.chk_dump_raw = QCheckBox("Save raw data — Also save undecoded texture files")
        self.chk_dump_raw.setStyleSheet(f"color: {COL_TEXT}; font-size: 11px;")
        adv_layout.addWidget(self.chk_dump_raw)
        self.chk_verbose = QCheckBox("Verbose log — Show detailed extraction log")
        self.chk_verbose.setStyleSheet(f"color: {COL_TEXT}; font-size: 11px;")
        adv_layout.addWidget(self.chk_verbose)
        main_layout.addWidget(self.advanced_section)

        # ── Extraction Log (collapsed) ──
        self.log_section = CollapsibleSection("Extraction Log")
        log_layout = self.log_section.content_layout()
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFont(QFont("Consolas", 9))
        self.log_box.setMaximumHeight(140)
        self.log_box.setStyleSheet(f"""
            QPlainTextEdit {{
                background: {COL_BG_DARKER};
                border: 1px solid {COL_BORDER};
                border-radius: 4px;
                color: {COL_TEXT_DIM};
            }}
        """)
        log_layout.addWidget(self.log_box)
        main_layout.addWidget(self.log_section)

        # Restore saved options
        self.chk_scan_all.setChecked(self.cfg.get("scan_all_files", False))
        self.chk_dump_raw.setChecked(self.cfg.get("dump_raw", False))
        self.chk_verbose.setChecked(self.cfg.get("verbose_logging", False))

    # ── Step state management ──

    def _update_steps(self, phase: str):
        """Update step indicators based on current phase."""
        if phase == "idle":
            self.step1.set_state("active")
            self.step2.set_state("active")
            self.step3.set_state("upcoming")
            self.step4.set_state("upcoming")
        elif phase == "file_loaded":
            self.step1.set_state("done")
            self.step2.set_state("done")
            self.step3.set_state("active")
            self.step4.set_state("upcoming")
        elif phase == "extracting":
            self.step1.set_state("done")
            self.step2.set_state("done")
            self.step3.set_state("active")
            self.step4.set_state("upcoming")
        elif phase == "done":
            self.step1.set_state("done")
            self.step2.set_state("done")
            self.step3.set_state("done")
            self.step4.set_state("active")

    # ── File handling ──

    def _on_file_dropped(self, path: str):
        if path == "":
            # Click on drop zone → open browser
            self._browse_input()
            return

        if not path.lower().endswith((".3ds", ".cia", ".cxi", ".app")):
            self._show_error(
                "This doesn't look like a 3DS ROM file",
                "3DS Texture Forge works with:\n"
                "  .3ds files (cartridge dumps)\n"
                "  .cia files (installable titles)\n\n"
                "Make sure your file is a decrypted 3DS game ROM."
            )
            return

        if not os.path.isfile(path):
            self._show_error(
                "File not found",
                f"Could not find:\n{path}"
            )
            return

        self._load_file(path)

    def _browse_input(self):
        start_dir = os.path.dirname(self.cfg.get("last_input_path", "")) or ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select 3DS ROM",
            start_dir,
            "3DS ROMs (*.3ds *.cia *.cxi *.app);;All Files (*)",
        )
        if path:
            self._load_file(path)

    def _load_file(self, path: str):
        self._loaded_path = path
        self.cfg["last_input_path"] = path

        # Quick scan to get game info
        self._hide_error()
        self.results_panel.setVisible(False)
        self.drop_zone.set_loaded(path, "Scanning...")

        # Synchronous scan — typically takes <2s, acceptable for UX
        result = scan_rom(path)
        self._on_quick_scan_done(result)

    def _on_quick_scan_done(self, result: dict):
        if result["success"]:
            self._scan_result = result
            self._game_name = get_game_name(
                result.get("title_id", ""),
                result.get("product_code", ""),
            )

            info = (f"{self._game_name}  |  "
                    f"{result['product_code']}  |  "
                    f"{result['file_count']} files")
            self.drop_zone.set_loaded(self._loaded_path, info)

            # Set output path
            safe_name = re.sub(r'[<>:"/\\|?*]', '', self._game_name).strip() or "output"
            output_dir = os.path.abspath(os.path.join("output", safe_name))
            self._output_dir = output_dir
            self.lbl_output_path.setText(output_dir)
            self.output_row.setVisible(True)

            self.btn_extract.setEnabled(True)
            self._update_steps("file_loaded")
            self._hide_error()

        elif result.get("is_encrypted"):
            self.drop_zone.clear()
            self._show_error(
                "This ROM is encrypted",
                "3DS Texture Forge can only read decrypted ROM files.\n\n"
                "To decrypt your ROM:\n"
                "  1. Put the ROM on your 3DS SD card\n"
                "  2. Open GodMode9 on your 3DS\n"
                "  3. Navigate to the ROM file\n"
                '  4. Select "NCSD image options"  "Decrypt file"\n'
                "  5. Copy the decrypted file back to your PC\n\n"
                'Need help? Search "GodMode9 decrypt 3DS ROM" on YouTube.'
            )
            self._update_steps("idle")
        else:
            self.drop_zone.clear()
            self._show_error(
                "Could not read this file",
                f"3DS Texture Forge works with:\n"
                f"  .3ds files (cartridge dumps)\n"
                f"  .cia files (installable titles)\n\n"
                f"Make sure your file is a decrypted 3DS game ROM.\n\n"
                f"Details: {result.get('error_message', 'Unknown error')}"
            )
            self._update_steps("idle")

    # ── Output ──

    def _browse_output(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select Output Folder",
            getattr(self, '_output_dir', ''),
        )
        if path:
            self._output_dir = path
            self.lbl_output_path.setText(path)

    # ── Extract ──

    def _do_extract(self):
        if not self._loaded_path or not os.path.isfile(self._loaded_path):
            return

        output_dir = getattr(self, '_output_dir', '')
        if not output_dir:
            return

        # Disable button, show progress
        self.btn_extract.setEnabled(False)
        self.btn_extract.setText("   EXTRACTING...   ")
        self.results_panel.setVisible(False)
        self._hide_error()
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # indeterminate
        self.lbl_progress_text.setVisible(True)
        self.lbl_progress_text.setText("Loading ROM...")
        self._update_steps("extracting")
        self.log_box.clear()

        if self.chk_verbose.isChecked():
            logging.root.setLevel(logging.DEBUG)
            self.log_section.set_expanded(True)
        else:
            logging.root.setLevel(logging.INFO)

        options = {
            "scan_all": self.chk_scan_all.isChecked(),
            "dump_raw": self.chk_dump_raw.isChecked(),
            "verbose": self.chk_verbose.isChecked(),
        }

        self.worker = ExtractWorker(self._loaded_path, output_dir, options)
        self.worker.log_message.connect(self._append_log)
        self.worker.progress.connect(self._on_extract_progress)
        self.worker.phase_changed.connect(self._on_phase_changed)
        self.worker.finished.connect(self._on_extract_finished)
        self.worker.start()

    def _on_phase_changed(self, phase_text: str):
        self.lbl_progress_text.setText(phase_text)

    def _on_extract_progress(self, current: int, total: int, file_path: str):
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
            self.lbl_progress_text.setText(
                f"Extracting textures ({current}/{total})..."
            )

    def _on_extract_finished(self, result: dict):
        self.worker = None
        self.progress_bar.setVisible(False)
        self.lbl_progress_text.setVisible(False)

        if result.get("success"):
            s = result.get("summary", {})
            decoded = s.get("textures_decoded_ok", 0)
            failed = s.get("textures_failed", 0)
            suspicious = s.get("suspicious_outputs", 0)
            elapsed = result.get("elapsed", 0)
            game_name = result.get("game_name", self._game_name)

            # Update button
            self.btn_extract.setText("   EXTRACT TEXTURES   ")
            self.btn_extract.setEnabled(True)

            # Show results
            if decoded > 0:
                self.lbl_results_headline.setText(
                    f'<span style="color:{COL_GREEN};">'
                    f'Done! Extracted {decoded:,} textures from {game_name}</span>'
                )
            else:
                self.lbl_results_headline.setText(
                    f'<span style="color:{COL_ORANGE};">'
                    f'No textures were found in {game_name}</span>'
                )

            # Detail line
            details = []
            if failed > 0:
                details.append(f'<span style="color:{COL_RED};">{failed} failed</span>')
            if suspicious > 0:
                details.append(f"{suspicious} may be blank or corrupted")
            details.append(f"{elapsed}s")
            if details:
                self.lbl_results_detail.setText("  |  ".join(details))
                self.lbl_results_detail.setVisible(True)

            # Store output dir for buttons
            self._result_output_dir = result.get("output_dir", getattr(self, '_output_dir', ''))

            # Check manifest
            manifest_path = os.path.join(self._result_output_dir, "manifest.json")
            self.btn_manifest.setVisible(os.path.isfile(manifest_path))

            # Load thumbnails
            self._load_thumbnails(self._result_output_dir, decoded)

            self.results_panel.setVisible(True)
            self._update_steps("done")

            # If zero textures, show helpful message
            if decoded == 0:
                self._show_error(
                    "No textures were found in this ROM",
                    "This could mean:\n"
                    "  The game uses a format we don't support yet\n"
                    "  The ROM file might be corrupted or incomplete\n\n"
                    'Try: Check the "Deep scan" option in Advanced Options\n'
                    "below and extract again. If that doesn't help,\n"
                    "this game may not be supported yet.",
                    is_warning=True,
                )

        elif result.get("is_encrypted"):
            self.btn_extract.setText("   EXTRACT TEXTURES   ")
            self.btn_extract.setEnabled(True)
            self._update_steps("file_loaded")
            self._show_error(
                "This ROM is encrypted",
                "3DS Texture Forge can only read decrypted ROM files.\n\n"
                "To decrypt your ROM:\n"
                "  1. Put the ROM on your 3DS SD card\n"
                "  2. Open GodMode9 on your 3DS\n"
                "  3. Navigate to the ROM file\n"
                '  4. Select "NCSD image options"  "Decrypt file"\n'
                "  5. Copy the decrypted file back to your PC\n\n"
                'Need help? Search "GodMode9 decrypt 3DS ROM" on YouTube.'
            )
        else:
            self.btn_extract.setText("   EXTRACT TEXTURES   ")
            self.btn_extract.setEnabled(True)
            self._update_steps("file_loaded")
            self._show_error(
                "Extraction failed",
                result.get("error_message", "An unknown error occurred."),
            )

        save_config(self.cfg)

    # ── Results helpers ──

    def _load_thumbnails(self, output_dir: str, total_decoded: int):
        # Clear existing
        while self.thumb_layout.count():
            item = self.thumb_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        previews = get_output_previews(output_dir, max_count=18)

        for png_path in previews:
            pixmap = QPixmap(png_path)
            if pixmap.isNull():
                continue
            scaled = pixmap.scaled(
                80, 80,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            lbl = QLabel()
            lbl.setPixmap(scaled)
            lbl.setToolTip(os.path.basename(png_path))
            lbl.setCursor(Qt.CursorShape.PointingHandCursor)
            lbl.setStyleSheet("border: none; padding: 2px;")
            lbl.mousePressEvent = lambda event, p=png_path: self._open_image(p)
            self.thumb_layout.addWidget(lbl)

        remaining = total_decoded - len(previews)
        if remaining > 0:
            more_lbl = QLabel(f"... and {remaining:,} more")
            more_lbl.setStyleSheet(
                f"color: {COL_TEXT_DIM}; font-style: italic; "
                f"padding: 8px; border: none;"
            )
            self.thumb_layout.addWidget(more_lbl)

    def _open_image(self, path: str):
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_output_folder(self):
        out_dir = getattr(self, '_result_output_dir', '')
        if out_dir and os.path.isdir(out_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(out_dir))

    def _open_manifest(self):
        out_dir = getattr(self, '_result_output_dir', '')
        if not out_dir:
            return
        manifest_path = os.path.join(out_dir, "manifest.json")
        if os.path.isfile(manifest_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(manifest_path))

    # ── Error display ──

    def _show_error(self, title: str, body: str, is_warning: bool = False):
        border_color = COL_ORANGE if is_warning else COL_RED
        bg_color = "#3a2a1a" if is_warning else "#3a1a1a"
        icon = "" if is_warning else ""
        self.error_panel.setStyleSheet(f"""
            QFrame {{
                background: {bg_color};
                border: 1px solid {border_color};
                border-radius: 8px;
            }}
        """)
        self.lbl_error.setText(
            f'<span style="color:{border_color}; font-size:13px; font-weight:bold;">'
            f'{icon} {title}</span><br><br>'
            f'<span style="color:{COL_TEXT}; font-size:11px; white-space:pre-wrap;">'
            f'{body}</span>'
        )
        self.error_panel.setVisible(True)

    def _hide_error(self):
        self.error_panel.setVisible(False)

    # ── About ──

    def _show_about(self):
        dlg = AboutDialog(self)
        dlg.exec()

    # ── Drag and Drop on main window (fallback) ──

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            self._on_file_dropped(path)
            return

    # ── Window lifecycle ──

    def closeEvent(self, event):
        # Stop worker if running
        if self.worker and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait(2000)

        self.cfg["window_width"] = self.width()
        self.cfg["window_height"] = self.height()
        if self._loaded_path:
            self.cfg["last_input_path"] = self._loaded_path
        self.cfg["scan_all_files"] = self.chk_scan_all.isChecked()
        self.cfg["dump_raw"] = self.chk_dump_raw.isChecked()
        self.cfg["verbose_logging"] = self.chk_verbose.isChecked()
        save_config(self.cfg)
        super().closeEvent(event)
