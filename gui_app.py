"""
3DS Texture Forge — PySide6 GUI.

Modern dark theme with three-panel layout:
  Sidebar (Library, Queue, History, Settings)
  Main content area (Drop zone, Progress, Results)
  Details panel (Game info, Stats, Quick actions)
"""

import datetime
import glob
import json
import logging
import os
import re
import sys
import time
from typing import Optional, List, Dict, Any

from PySide6.QtCore import (
    Qt, QThread, Signal, QUrl, QTimer, QSize, QPropertyAnimation,
    QEasingCurve, Property,
)
from PySide6.QtGui import (
    QColor, QDesktopServices, QDragEnterEvent, QDropEvent,
    QFont, QIcon, QPalette, QPixmap, QPainter, QPen, QAction, QCursor,
    QFontDatabase,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QSizePolicy, QSlider, QSpacerItem, QSplitter, QStackedWidget,
    QStatusBar, QVBoxLayout, QWidget, QDialog, QTextBrowser, QRadioButton,
    QButtonGroup, QToolButton,
)

from config import load_config, save_config
from backend import scan_rom, run_extraction, get_output_previews, get_game_name

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# Color palette
# ══════════════════════════════════════════════════════════════

C_BG         = "#1a1a2e"
C_SURFACE    = "#16213e"
C_CARD       = "#0f3460"
C_ACCENT     = "#e94560"
C_ACCENT_H   = "#ff5a75"
C_ACCENT2    = "#533483"
C_TEXT        = "#eaeaea"
C_TEXT2       = "#a0a0b0"
C_SUCCESS     = "#4ecca3"
C_SUCCESS_DIM = "#2a7a5a"
C_WARNING     = "#f5a623"
C_ERROR       = "#e94560"
C_BORDER      = "#2a2a4a"
C_SIDEBAR_BG  = "#111128"
C_SIDEBAR_SEL = "#1e1e4a"
C_SIDEBAR_HOV = "#1a1a3e"
C_INPUT_BG    = "#0d1b2a"

# Font stack (resolved at runtime)
FONT_FAMILY = "Segoe UI, Ubuntu, Noto Sans, Helvetica, Arial, sans-serif"


# ══════════════════════════════════════════════════════════════
# Stylesheet fragments
# ══════════════════════════════════════════════════════════════

def _btn_primary(bg=C_ACCENT, hover=C_ACCENT_H, fg="white", radius=6, h=38):
    return f"""
        QPushButton {{
            background: {bg}; color: {fg};
            font-weight: bold; font-size: 13px;
            padding: 6px 24px; border-radius: {radius}px; border: none;
            min-height: {h}px;
        }}
        QPushButton:hover {{ background: {hover}; }}
        QPushButton:disabled {{ background: #2a2a3a; color: #555; }}
    """

def _btn_secondary(bg="#2a2a4a", hover="#3a3a5a", fg=C_TEXT, radius=6, h=32):
    return f"""
        QPushButton {{
            background: {bg}; color: {fg};
            font-size: 12px; padding: 4px 16px;
            border-radius: {radius}px; border: 1px solid {C_BORDER};
            min-height: {h}px;
        }}
        QPushButton:hover {{ background: {hover}; border-color: #4a4a6a; }}
    """

def _btn_ghost(fg=C_TEXT2, hover_fg=C_TEXT):
    return f"""
        QPushButton {{
            background: transparent; border: none;
            color: {fg}; font-size: 12px; padding: 4px 8px;
        }}
        QPushButton:hover {{ color: {hover_fg}; }}
    """

SCROLLBAR_STYLE = f"""
    QScrollBar:vertical {{
        background: transparent; width: 8px; margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: #3a3a5a; border-radius: 4px; min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: #5a5a7a; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0; background: none;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: none;
    }}
    QScrollBar:horizontal {{
        background: transparent; height: 8px; margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background: #3a3a5a; border-radius: 4px; min-width: 30px;
    }}
    QScrollBar::handle:horizontal:hover {{ background: #5a5a7a; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0; background: none;
    }}
"""


# ══════════════════════════════════════════════════════════════
# Logging handler — thread-safe signal bridge
# ══════════════════════════════════════════════════════════════

class SignalLogHandler(logging.Handler):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def emit(self, record):
        try:
            self.callback(self.format(record))
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════
# Worker thread — scan + extract
# ══════════════════════════════════════════════════════════════

class ExtractWorker(QThread):
    finished = Signal(dict)
    progress = Signal(int, int, str, int)
    log_message = Signal(str)
    phase_changed = Signal(str)

    def __init__(self, filepath: str, output_dir: str, options: dict):
        super().__init__()
        self.filepath = filepath
        self.output_dir = output_dir
        self.options = options

    def _on_progress(self, current, total, file_path, fmt_name, tex_count, h):
        self.progress.emit(current, total, file_path, tex_count)

    def run(self):
        self.phase_changed.emit("Loading ROM...")
        self.log_message.emit(f"Loading: {os.path.basename(self.filepath)}")

        scan_result = scan_rom(self.filepath)
        if not scan_result["success"]:
            self.finished.emit({
                "success": False,
                "error_message": scan_result["error_message"],
                "is_encrypted": scan_result.get("is_encrypted", False),
                "scan_result": scan_result,
            })
            return

        game_name = get_game_name(
            scan_result.get("title_id", ""),
            scan_result.get("product_code", ""),
        )
        self.phase_changed.emit(f"Extracting {game_name}...")
        self.log_message.emit(
            f"ROM: {game_name} | {scan_result['product_code']} | "
            f"{scan_result['file_count']} files"
        )

        result = run_extraction(
            self.filepath, self.output_dir, self.options,
            progress_callback=self._on_progress,
        )
        result["scan_result"] = scan_result
        result["game_name"] = game_name
        self.finished.emit(result)


# ══════════════════════════════════════════════════════════════
# Dark palette
# ══════════════════════════════════════════════════════════════

def apply_dark_palette(app: QApplication):
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(C_BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(C_TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(C_INPUT_BG))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(C_SURFACE))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(C_SURFACE))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(C_TEXT))
    palette.setColor(QPalette.ColorRole.Text, QColor(C_TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(C_SURFACE))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(C_TEXT))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, QColor(C_ACCENT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(C_ACCENT2))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text,
                     QColor("#555566"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText,
                     QColor("#555566"))
    app.setPalette(palette)
    app.setStyle("Fusion")

    # Global stylesheet additions
    app.setStyleSheet(f"""
        QToolTip {{
            background: {C_SURFACE}; color: {C_TEXT};
            border: 1px solid {C_BORDER}; padding: 4px;
            font-size: 11px;
        }}
        {SCROLLBAR_STYLE}
    """)


# ══════════════════════════════════════════════════════════════
# Drop Zone
# ══════════════════════════════════════════════════════════════

class DropZone(QFrame):
    """Large drag-and-drop target."""
    file_dropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setMinimumHeight(200)
        self._hovering = False
        self._loaded_file = ""
        self._game_info = ""
        self._update_style(False)

    def _update_style(self, hover: bool):
        if self._loaded_file:
            self.setStyleSheet(f"""
                DropZone {{
                    background: {C_SURFACE};
                    border: 2px solid {C_SUCCESS_DIM};
                    border-radius: 8px;
                }}
            """)
        elif hover:
            self.setStyleSheet(f"""
                DropZone {{
                    background: #1a2a4a;
                    border: 2px dashed {C_ACCENT};
                    border-radius: 8px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                DropZone {{
                    background: {C_SURFACE};
                    border: 2px dashed #3a3a5a;
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
            fname = os.path.basename(self._loaded_file)
            painter.setPen(QPen(QColor(C_SUCCESS), 2))
            font_big = QFont(FONT_FAMILY, 13, QFont.Weight.Bold)
            painter.setFont(font_big)
            painter.drawText(rect.adjusted(0, 40, 0, -60),
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                             fname)
            if self._game_info:
                painter.setPen(QColor(C_TEXT2))
                painter.setFont(QFont(FONT_FAMILY, 10))
                painter.drawText(rect.adjusted(0, 70, 0, -30),
                                 Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                                 self._game_info)
            painter.setPen(QColor("#666680"))
            painter.setFont(QFont(FONT_FAMILY, 9))
            painter.drawText(rect.adjusted(0, 0, 0, -12),
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                             "Click or drop to change file")
        else:
            # Cartridge icon (simple unicode)
            painter.setPen(QColor("#4a4a6a"))
            painter.setFont(QFont(FONT_FAMILY, 36))
            painter.drawText(rect.adjusted(0, 20, 0, -80),
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                             "\U0001F3AE")  # game controller emoji
            painter.setPen(QColor(C_TEXT))
            painter.setFont(QFont(FONT_FAMILY, 14))
            painter.drawText(rect.adjusted(0, 85, 0, -40),
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                             "Drop a ROM here or click to browse")
            painter.setPen(QColor(C_TEXT2))
            painter.setFont(QFont(FONT_FAMILY, 10))
            painter.drawText(rect.adjusted(0, 115, 0, -20),
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                             "Supports .3ds and .cia (decrypted)")
        painter.end()

    def mousePressEvent(self, event):
        self.file_dropped.emit("")

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith((".3ds", ".cia", ".cxi", ".app")):
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
        if event.mimeData().urls():
            self.file_dropped.emit(event.mimeData().urls()[0].toLocalFile())


# ══════════════════════════════════════════════════════════════
# Metric Pill — small rounded stat display
# ══════════════════════════════════════════════════════════════

class MetricPill(QFrame):
    def __init__(self, label: str, value: str = "--", color: str = C_ACCENT, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            MetricPill {{
                background: {C_SURFACE}; border: 1px solid {C_BORDER};
                border-radius: 8px; padding: 8px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)
        self._value_lbl = QLabel(value)
        self._value_lbl.setStyleSheet(f"color: {color}; font-size: 20px; font-weight: bold;")
        self._value_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._value_lbl)
        self._label_lbl = QLabel(label)
        self._label_lbl.setStyleSheet(f"color: {C_TEXT2}; font-size: 11px;")
        self._label_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label_lbl)

    def set_value(self, value: str, color: str = None):
        self._value_lbl.setText(value)
        if color:
            self._value_lbl.setStyleSheet(f"color: {color}; font-size: 20px; font-weight: bold;")


# ══════════════════════════════════════════════════════════════
# Sidebar Tab Button
# ══════════════════════════════════════════════════════════════

class SidebarButton(QPushButton):
    def __init__(self, icon_text: str, label: str, parent=None):
        super().__init__(parent)
        self.setText(f"  {icon_text}  {label}")
        self.setCheckable(True)
        self.setFixedHeight(40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_style()

    def _update_style(self):
        self.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C_TEXT2};
                text-align: left; font-size: 12px;
                border: none; padding: 0 12px;
                border-left: 3px solid transparent;
            }}
            QPushButton:hover {{
                background: {C_SIDEBAR_HOV}; color: {C_TEXT};
            }}
            QPushButton:checked {{
                background: {C_SIDEBAR_SEL}; color: {C_TEXT};
                border-left: 3px solid {C_ACCENT};
            }}
        """)


# ══════════════════════════════════════════════════════════════
# History Manager
# ══════════════════════════════════════════════════════════════

HISTORY_FILE = os.path.join(os.path.expanduser("~"), ".3ds-texture-forge", "history.json")

def _load_history() -> List[Dict]:
    try:
        if os.path.isfile(HISTORY_FILE):
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []

def _save_history(entries: List[Dict]):
    try:
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(entries[:50], f, indent=2)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
# Main Window
# ══════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.worker = None
        self._loaded_path = ""
        self._scan_result = None
        self._game_name = ""
        self._output_dir = ""
        self._result_output_dir = ""
        self._extract_start_time = 0
        self._queue: List[str] = []
        self._queue_running = False

        self.setWindowTitle("3DS Texture Forge")
        self._set_window_icon()
        self.setMinimumSize(900, 600)
        self.resize(self.cfg.get("window_width", 1200),
                    self.cfg.get("window_height", 800))
        self.setAcceptDrops(True)

        self.setStyleSheet(f"QMainWindow {{ background: {C_BG}; }}")

        self._build_ui()
        self._setup_logging()
        self._switch_main_page("drop")

    def _set_window_icon(self):
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

    # ══════════════════════════════════════════════
    # UI Construction
    # ══════════════════════════════════════════════

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Sidebar ──
        self._build_sidebar(root)

        # ── Main + Details splitter ──
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(1)
        self.splitter.setStyleSheet(f"QSplitter::handle {{ background: {C_BORDER}; }}")

        # Main content
        self.main_stack = QStackedWidget()
        self._build_main_pages()
        self.splitter.addWidget(self.main_stack)

        # Details panel
        self.details_panel = QWidget()
        self._build_details_panel()
        self.splitter.addWidget(self.details_panel)

        self.splitter.setSizes([700, 280])
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        root.addWidget(self.splitter, 1)

        # ── Status bar ──
        self._build_status_bar()

    # ── Sidebar ──

    def _build_sidebar(self, parent_layout):
        sidebar = QWidget()
        sidebar.setFixedWidth(200)
        sidebar.setStyleSheet(f"background: {C_SIDEBAR_BG};")
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(0, 0, 0, 0)
        sb_layout.setSpacing(0)

        # Logo
        logo = QLabel("  3DS Texture\n  Forge")
        logo.setFixedHeight(56)
        logo.setStyleSheet(f"""
            color: {C_TEXT}; font-size: 14px; font-weight: bold;
            padding: 8px 12px; background: {C_SIDEBAR_BG};
        """)
        sb_layout.addWidget(logo)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {C_BORDER};")
        sb_layout.addWidget(sep)
        sb_layout.addSpacing(8)

        # Nav buttons
        self.btn_extract_tab = SidebarButton("\U0001F3AE", "Extract")
        self.btn_library_tab = SidebarButton("\U0001F4C2", "Library")
        self.btn_queue_tab   = SidebarButton("\U0001F4CB", "Queue")
        self.btn_history_tab = SidebarButton("\U0001F4CA", "History")
        self.btn_settings_tab = SidebarButton("\u2699", "Settings")

        self._sidebar_btns = [
            self.btn_extract_tab, self.btn_library_tab, self.btn_queue_tab,
            self.btn_history_tab, self.btn_settings_tab,
        ]
        self._sidebar_pages = ["drop", "library", "queue", "history", "settings"]

        for i, btn in enumerate(self._sidebar_btns):
            btn.clicked.connect(lambda checked, idx=i: self._on_sidebar_click(idx))
            sb_layout.addWidget(btn)

        self.btn_extract_tab.setChecked(True)

        sb_layout.addStretch()

        # Version
        ver = QLabel(f"  v1.1")
        ver.setStyleSheet(f"color: #444460; font-size: 10px; padding: 8px;")
        sb_layout.addWidget(ver)

        parent_layout.addWidget(sidebar)

    def _on_sidebar_click(self, idx: int):
        for i, btn in enumerate(self._sidebar_btns):
            btn.setChecked(i == idx)
        page = self._sidebar_pages[idx]
        self._switch_main_page(page)

    # ── Main content pages ──

    def _build_main_pages(self):
        # Page 0: Drop zone / extraction
        self.page_extract = QWidget()
        self._build_extract_page()
        self.main_stack.addWidget(self.page_extract)

        # Page 1: Library
        self.page_library = QWidget()
        self._build_library_page()
        self.main_stack.addWidget(self.page_library)

        # Page 2: Queue
        self.page_queue = QWidget()
        self._build_queue_page()
        self.main_stack.addWidget(self.page_queue)

        # Page 3: History
        self.page_history = QWidget()
        self._build_history_page()
        self.main_stack.addWidget(self.page_history)

        # Page 4: Settings
        self.page_settings = QWidget()
        self._build_settings_page()
        self.main_stack.addWidget(self.page_settings)

    def _switch_main_page(self, name: str):
        idx_map = {"drop": 0, "extract": 0, "library": 1, "queue": 2,
                   "history": 3, "settings": 4}
        idx = idx_map.get(name, 0)
        self.main_stack.setCurrentIndex(idx)
        if name == "history":
            self._refresh_history()

    # ── Extract page ──

    def _build_extract_page(self):
        layout = QVBoxLayout(self.page_extract)
        layout.setContentsMargins(24, 20, 24, 12)
        layout.setSpacing(12)

        # Drop zone
        self.drop_zone = DropZone()
        self.drop_zone.file_dropped.connect(self._on_file_dropped)
        layout.addWidget(self.drop_zone)

        # Action row
        action_row = QHBoxLayout()
        self.btn_extract = QPushButton("   EXTRACT TEXTURES   ")
        self.btn_extract.setStyleSheet(_btn_primary())
        self.btn_extract.setEnabled(False)
        self.btn_extract.clicked.connect(self._do_extract)
        action_row.addWidget(self.btn_extract)

        self.btn_add_queue = QPushButton("Add to Queue")
        self.btn_add_queue.setStyleSheet(_btn_secondary())
        self.btn_add_queue.setEnabled(False)
        self.btn_add_queue.clicked.connect(self._add_to_queue)
        action_row.addWidget(self.btn_add_queue)
        action_row.addStretch()
        layout.addLayout(action_row)

        # Progress section (hidden)
        self.progress_frame = QFrame()
        self.progress_frame.setStyleSheet(f"""
            QFrame {{ background: {C_SURFACE}; border: 1px solid {C_BORDER};
                      border-radius: 8px; }}
        """)
        self.progress_frame.setVisible(False)
        pf_layout = QVBoxLayout(self.progress_frame)
        pf_layout.setContentsMargins(16, 12, 16, 12)
        pf_layout.setSpacing(8)

        self.lbl_progress_phase = QLabel("Loading ROM...")
        self.lbl_progress_phase.setStyleSheet(f"color: {C_TEXT}; font-size: 13px; font-weight: bold; border: none;")
        pf_layout.addWidget(self.lbl_progress_phase)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumHeight(14)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: {C_INPUT_BG}; border: none; border-radius: 7px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {C_ACCENT}, stop:1 {C_ACCENT2});
                border-radius: 7px;
            }}
        """)
        pf_layout.addWidget(self.progress_bar)

        self.lbl_progress_stats = QLabel("")
        self.lbl_progress_stats.setStyleSheet(f"color: {C_TEXT2}; font-size: 11px; border: none;")
        pf_layout.addWidget(self.lbl_progress_stats)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setStyleSheet(_btn_ghost(C_ERROR, C_ACCENT_H))
        self.btn_cancel.clicked.connect(self._cancel_extract)
        self.btn_cancel.setVisible(False)
        pf_layout.addWidget(self.btn_cancel, alignment=Qt.AlignmentFlag.AlignRight)

        layout.addWidget(self.progress_frame)

        # Results section (hidden)
        self.results_frame = QFrame()
        self.results_frame.setStyleSheet(f"""
            QFrame {{ background: {C_SURFACE}; border: 1px solid {C_BORDER};
                      border-radius: 8px; }}
        """)
        self.results_frame.setVisible(False)
        rf_layout = QVBoxLayout(self.results_frame)
        rf_layout.setContentsMargins(16, 12, 16, 12)
        rf_layout.setSpacing(10)

        self.lbl_results_headline = QLabel("")
        self.lbl_results_headline.setStyleSheet(f"font-size: 15px; font-weight: bold; border: none;")
        rf_layout.addWidget(self.lbl_results_headline)

        # Metric pills row
        metrics_row = QHBoxLayout()
        self.pill_textures = MetricPill("Textures", "--", C_SUCCESS)
        self.pill_quality  = MetricPill("Quality", "--", C_ACCENT)
        self.pill_unique   = MetricPill("Unique", "--", C_ACCENT2)
        self.pill_time     = MetricPill("Time", "--", C_TEXT2)
        for pill in [self.pill_textures, self.pill_quality, self.pill_unique, self.pill_time]:
            metrics_row.addWidget(pill)
        rf_layout.addLayout(metrics_row)

        # Action buttons
        res_btn_row = QHBoxLayout()
        self.btn_open_folder = QPushButton("  Open Output Folder  ")
        self.btn_open_folder.setStyleSheet(_btn_primary(C_SUCCESS_DIM, C_SUCCESS, "white"))
        self.btn_open_folder.clicked.connect(self._open_output_folder)
        res_btn_row.addWidget(self.btn_open_folder)

        self.btn_view_manifest = QPushButton("View Manifest")
        self.btn_view_manifest.setStyleSheet(_btn_secondary())
        self.btn_view_manifest.clicked.connect(self._open_manifest)
        res_btn_row.addWidget(self.btn_view_manifest)
        res_btn_row.addStretch()
        rf_layout.addLayout(res_btn_row)

        # Thumbnail preview
        self.thumb_scroll = QScrollArea()
        self.thumb_scroll.setWidgetResizable(True)
        self.thumb_scroll.setMaximumHeight(110)
        self.thumb_scroll.setStyleSheet(f"background: transparent; border: none;")
        self.thumb_widget = QWidget()
        self.thumb_widget.setStyleSheet("border: none;")
        self.thumb_layout = QHBoxLayout(self.thumb_widget)
        self.thumb_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.thumb_layout.setSpacing(6)
        self.thumb_scroll.setWidget(self.thumb_widget)
        rf_layout.addWidget(self.thumb_scroll)

        layout.addWidget(self.results_frame)

        # Error panel (hidden)
        self.error_panel = QFrame()
        self.error_panel.setVisible(False)
        ep_layout = QVBoxLayout(self.error_panel)
        ep_layout.setContentsMargins(16, 12, 16, 12)
        self.lbl_error = QLabel("")
        self.lbl_error.setWordWrap(True)
        self.lbl_error.setStyleSheet(f"color: {C_TEXT}; font-size: 12px; border: none;")
        ep_layout.addWidget(self.lbl_error)
        layout.addWidget(self.error_panel)

        layout.addStretch()

        # Log panel (collapsed)
        self.log_toggle = QPushButton("  Show Extraction Log")
        self.log_toggle.setStyleSheet(_btn_ghost())
        self.log_toggle.clicked.connect(self._toggle_log)
        layout.addWidget(self.log_toggle)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFont(QFont("Consolas, Courier New, monospace", 9))
        self.log_box.setMaximumHeight(140)
        self.log_box.setVisible(False)
        self.log_box.setStyleSheet(f"""
            QPlainTextEdit {{
                background: {C_INPUT_BG}; border: 1px solid {C_BORDER};
                border-radius: 6px; color: {C_TEXT2}; padding: 4px;
            }}
        """)
        layout.addWidget(self.log_box)

    def _toggle_log(self):
        vis = not self.log_box.isVisible()
        self.log_box.setVisible(vis)
        self.log_toggle.setText("  Hide Extraction Log" if vis else "  Show Extraction Log")

    # ── Library page ──

    def _build_library_page(self):
        layout = QVBoxLayout(self.page_library)
        layout.setContentsMargins(24, 20, 24, 12)
        layout.setSpacing(12)

        header = QLabel(f'<span style="color:{C_TEXT}; font-size:16px; font-weight:bold;">ROM Library</span>')
        layout.addWidget(header)

        # Folder picker row
        folder_row = QHBoxLayout()
        self.lib_folder_input = QLineEdit()
        self.lib_folder_input.setPlaceholderText("Select a folder containing ROMs...")
        self.lib_folder_input.setStyleSheet(f"""
            QLineEdit {{
                background: {C_INPUT_BG}; color: {C_TEXT}; border: 1px solid {C_BORDER};
                border-radius: 6px; padding: 6px 10px; font-size: 12px;
            }}
            QLineEdit:focus {{ border-color: {C_ACCENT}; }}
        """)
        self.lib_folder_input.setText(self.cfg.get("library_folder", ""))
        folder_row.addWidget(self.lib_folder_input)

        btn_browse_lib = QPushButton("Browse")
        btn_browse_lib.setStyleSheet(_btn_secondary())
        btn_browse_lib.clicked.connect(self._browse_library_folder)
        folder_row.addWidget(btn_browse_lib)

        btn_scan_lib = QPushButton("Scan")
        btn_scan_lib.setStyleSheet(_btn_primary(h=32))
        btn_scan_lib.clicked.connect(self._scan_library)
        folder_row.addWidget(btn_scan_lib)
        layout.addLayout(folder_row)

        # ROM list
        self.lib_list = QListWidget()
        self.lib_list.setStyleSheet(f"""
            QListWidget {{
                background: {C_SURFACE}; border: 1px solid {C_BORDER};
                border-radius: 6px; color: {C_TEXT}; font-size: 12px;
            }}
            QListWidget::item {{
                padding: 8px 12px; border-bottom: 1px solid {C_BORDER};
            }}
            QListWidget::item:selected {{
                background: {C_SIDEBAR_SEL};
            }}
            QListWidget::item:hover {{
                background: {C_SIDEBAR_HOV};
            }}
        """)
        self.lib_list.itemDoubleClicked.connect(self._lib_item_double_clicked)
        layout.addWidget(self.lib_list)

        # Library actions
        lib_actions = QHBoxLayout()
        btn_extract_sel = QPushButton("Extract Selected")
        btn_extract_sel.setStyleSheet(_btn_primary(h=32))
        btn_extract_sel.clicked.connect(self._lib_extract_selected)
        lib_actions.addWidget(btn_extract_sel)

        btn_queue_all = QPushButton("Queue All")
        btn_queue_all.setStyleSheet(_btn_secondary())
        btn_queue_all.clicked.connect(self._lib_queue_all)
        lib_actions.addWidget(btn_queue_all)
        lib_actions.addStretch()
        layout.addLayout(lib_actions)

    def _browse_library_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select ROM Folder",
                                                 self.lib_folder_input.text())
        if path:
            self.lib_folder_input.setText(path)
            self.cfg["library_folder"] = path
            save_config(self.cfg)
            self._scan_library()

    def _scan_library(self):
        folder = self.lib_folder_input.text()
        if not folder or not os.path.isdir(folder):
            return
        self.lib_list.clear()
        for f in sorted(os.listdir(folder)):
            if f.lower().endswith((".3ds", ".cia")):
                item = QListWidgetItem(f)
                item.setData(Qt.ItemDataRole.UserRole, os.path.join(folder, f))
                size_mb = os.path.getsize(os.path.join(folder, f)) / (1024 * 1024)
                item.setToolTip(f"{size_mb:.0f} MB")
                self.lib_list.addItem(item)
        self.statusBar().showMessage(f"Found {self.lib_list.count()} ROMs", 5000)

    def _lib_item_double_clicked(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self._on_sidebar_click(0)  # Switch to Extract tab
            self._load_file(path)

    def _lib_extract_selected(self):
        item = self.lib_list.currentItem()
        if item:
            self._lib_item_double_clicked(item)

    def _lib_queue_all(self):
        for i in range(self.lib_list.count()):
            path = self.lib_list.item(i).data(Qt.ItemDataRole.UserRole)
            if path and path not in self._queue:
                self._queue.append(path)
        self._refresh_queue_list()
        self._on_sidebar_click(2)  # Switch to Queue tab
        self.statusBar().showMessage(f"Added {self.lib_list.count()} ROMs to queue", 3000)

    # ── Queue page ──

    def _build_queue_page(self):
        layout = QVBoxLayout(self.page_queue)
        layout.setContentsMargins(24, 20, 24, 12)
        layout.setSpacing(12)

        header = QLabel(f'<span style="color:{C_TEXT}; font-size:16px; font-weight:bold;">Extraction Queue</span>')
        layout.addWidget(header)

        self.queue_list = QListWidget()
        self.queue_list.setStyleSheet(f"""
            QListWidget {{
                background: {C_SURFACE}; border: 1px solid {C_BORDER};
                border-radius: 6px; color: {C_TEXT}; font-size: 12px;
            }}
            QListWidget::item {{ padding: 8px 12px; border-bottom: 1px solid {C_BORDER}; }}
            QListWidget::item:selected {{ background: {C_SIDEBAR_SEL}; }}
        """)
        layout.addWidget(self.queue_list)

        self.lbl_queue_status = QLabel("")
        self.lbl_queue_status.setStyleSheet(f"color: {C_TEXT2}; font-size: 11px;")
        layout.addWidget(self.lbl_queue_status)

        q_actions = QHBoxLayout()
        self.btn_start_queue = QPushButton("Start All")
        self.btn_start_queue.setStyleSheet(_btn_primary(h=32))
        self.btn_start_queue.clicked.connect(self._start_queue)
        q_actions.addWidget(self.btn_start_queue)

        btn_clear_queue = QPushButton("Clear Queue")
        btn_clear_queue.setStyleSheet(_btn_secondary())
        btn_clear_queue.clicked.connect(self._clear_queue)
        q_actions.addWidget(btn_clear_queue)
        q_actions.addStretch()
        layout.addLayout(q_actions)

    def _refresh_queue_list(self):
        self.queue_list.clear()
        for path in self._queue:
            self.queue_list.addItem(os.path.basename(path))
        self.lbl_queue_status.setText(f"{len(self._queue)} items in queue")

    def _add_to_queue(self):
        if self._loaded_path and self._loaded_path not in self._queue:
            self._queue.append(self._loaded_path)
            self._refresh_queue_list()
            self.statusBar().showMessage(f"Added to queue: {os.path.basename(self._loaded_path)}", 3000)

    def _start_queue(self):
        if not self._queue or self._queue_running:
            return
        self._queue_running = True
        self._queue_idx = 0
        self._on_sidebar_click(0)  # Switch to Extract tab
        self._run_next_in_queue()

    def _run_next_in_queue(self):
        if self._queue_idx >= len(self._queue):
            self._queue_running = False
            self.statusBar().showMessage("Queue complete!", 5000)
            return
        path = self._queue[self._queue_idx]
        self._queue_idx += 1
        self._load_file(path)
        QTimer.singleShot(500, self._do_extract)

    def _clear_queue(self):
        self._queue.clear()
        self._queue_running = False
        self._refresh_queue_list()

    # ── History page ──

    def _build_history_page(self):
        layout = QVBoxLayout(self.page_history)
        layout.setContentsMargins(24, 20, 24, 12)
        layout.setSpacing(12)

        header_row = QHBoxLayout()
        header = QLabel(f'<span style="color:{C_TEXT}; font-size:16px; font-weight:bold;">Extraction History</span>')
        header_row.addWidget(header)
        header_row.addStretch()
        btn_clear_hist = QPushButton("Clear")
        btn_clear_hist.setStyleSheet(_btn_ghost())
        btn_clear_hist.clicked.connect(self._clear_history)
        header_row.addWidget(btn_clear_hist)
        layout.addLayout(header_row)

        self.history_list = QListWidget()
        self.history_list.setStyleSheet(f"""
            QListWidget {{
                background: {C_SURFACE}; border: 1px solid {C_BORDER};
                border-radius: 6px; color: {C_TEXT}; font-size: 12px;
            }}
            QListWidget::item {{ padding: 8px 12px; border-bottom: 1px solid {C_BORDER}; }}
            QListWidget::item:selected {{ background: {C_SIDEBAR_SEL}; }}
        """)
        self.history_list.itemDoubleClicked.connect(self._history_item_clicked)
        layout.addWidget(self.history_list)

    def _refresh_history(self):
        self.history_list.clear()
        entries = _load_history()
        for entry in entries:
            game = entry.get("game", "Unknown")
            tex = entry.get("textures", 0)
            quality = entry.get("quality", "")
            date = entry.get("date", "")
            text = f"{game}  |  {tex:,} textures  |  {quality}  |  {date}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, entry.get("output_dir", ""))
            self.history_list.addItem(item)

    def _history_item_clicked(self, item):
        out_dir = item.data(Qt.ItemDataRole.UserRole)
        if out_dir and os.path.isdir(out_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(out_dir))

    def _clear_history(self):
        _save_history([])
        self._refresh_history()

    def _add_history_entry(self, game: str, textures: int, quality: str, output_dir: str):
        entries = _load_history()
        entries.insert(0, {
            "game": game,
            "textures": textures,
            "quality": quality,
            "output_dir": output_dir,
            "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        })
        _save_history(entries)

    # ── Settings page ──

    def _build_settings_page(self):
        layout = QVBoxLayout(self.page_settings)
        layout.setContentsMargins(24, 20, 24, 12)
        layout.setSpacing(16)

        header = QLabel(f'<span style="color:{C_TEXT}; font-size:16px; font-weight:bold;">Settings</span>')
        layout.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        scroll_content = QWidget()
        s_layout = QVBoxLayout(scroll_content)
        s_layout.setSpacing(16)

        # ── Output section ──
        s_layout.addWidget(self._settings_section("Output"))
        out_grid = QGridLayout()
        out_grid.setSpacing(8)

        out_grid.addWidget(QLabel("Output folder:"), 0, 0)
        self.set_output_input = QLineEdit(self.cfg.get("last_output_path", ""))
        self.set_output_input.setPlaceholderText("Default: ./output/<game_name>")
        self.set_output_input.setStyleSheet(f"""
            QLineEdit {{
                background: {C_INPUT_BG}; color: {C_TEXT}; border: 1px solid {C_BORDER};
                border-radius: 4px; padding: 4px 8px; font-size: 12px;
            }}
        """)
        out_grid.addWidget(self.set_output_input, 0, 1)
        btn_browse_out = QPushButton("Browse")
        btn_browse_out.setStyleSheet(_btn_secondary(h=28))
        btn_browse_out.clicked.connect(lambda: self._settings_browse_folder(self.set_output_input))
        out_grid.addWidget(btn_browse_out, 0, 2)

        out_grid.addWidget(QLabel("Output mode:"), 1, 0)
        mode_row = QHBoxLayout()
        self.rb_standard = QRadioButton("Standard")
        self.rb_azahar = QRadioButton("Azahar")
        self.rb_standard.setChecked(self.cfg.get("output_mode", "standard") != "azahar")
        self.rb_azahar.setChecked(self.cfg.get("output_mode", "standard") == "azahar")
        mode_row.addWidget(self.rb_standard)
        mode_row.addWidget(self.rb_azahar)
        mode_row.addStretch()
        mode_container = QWidget()
        mode_container.setLayout(mode_row)
        out_grid.addWidget(mode_container, 1, 1)
        s_layout.addLayout(out_grid)

        # ── Extraction section ──
        s_layout.addWidget(self._settings_section("Extraction"))
        self.chk_scan_all = QCheckBox("Deep scan (try harder, slower)")
        self.chk_scan_all.setChecked(self.cfg.get("scan_all_files", False))
        s_layout.addWidget(self.chk_scan_all)
        self.chk_dedup = QCheckBox("Skip duplicates (saves disk space)")
        self.chk_dedup.setChecked(self.cfg.get("dedup", False))
        s_layout.addWidget(self.chk_dedup)
        self.chk_dump_raw = QCheckBox("Save raw texture data")
        self.chk_dump_raw.setChecked(self.cfg.get("dump_raw", False))
        s_layout.addWidget(self.chk_dump_raw)
        self.chk_verbose = QCheckBox("Verbose logging")
        self.chk_verbose.setChecked(self.cfg.get("verbose_logging", False))
        s_layout.addWidget(self.chk_verbose)

        # ── Quality section ──
        s_layout.addWidget(self._settings_section("Quality"))
        self.chk_contact_sheet = QCheckBox("Generate contact sheet")
        self.chk_contact_sheet.setChecked(self.cfg.get("contact_sheet", True))
        s_layout.addWidget(self.chk_contact_sheet)
        self.chk_quality_report = QCheckBox("Generate quality report")
        self.chk_quality_report.setChecked(self.cfg.get("quality_report", True))
        s_layout.addWidget(self.chk_quality_report)

        # ── Azahar section ──
        s_layout.addWidget(self._settings_section("Azahar Integration"))
        az_grid = QGridLayout()
        az_grid.addWidget(QLabel("Azahar load folder:"), 0, 0)
        self.set_azahar_path = QLineEdit(self.cfg.get("azahar_load_path", ""))
        self.set_azahar_path.setPlaceholderText("e.g. C:/Users/You/azahar/load/textures")
        self.set_azahar_path.setStyleSheet(f"""
            QLineEdit {{
                background: {C_INPUT_BG}; color: {C_TEXT}; border: 1px solid {C_BORDER};
                border-radius: 4px; padding: 4px 8px; font-size: 12px;
            }}
        """)
        az_grid.addWidget(self.set_azahar_path, 0, 1)
        btn_az_browse = QPushButton("Browse")
        btn_az_browse.setStyleSheet(_btn_secondary(h=28))
        btn_az_browse.clicked.connect(lambda: self._settings_browse_folder(self.set_azahar_path))
        az_grid.addWidget(btn_az_browse, 0, 2)
        s_layout.addLayout(az_grid)

        s_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        # Apply button
        btn_save = QPushButton("Save Settings")
        btn_save.setStyleSheet(_btn_primary(h=32))
        btn_save.clicked.connect(self._save_settings)
        layout.addWidget(btn_save, alignment=Qt.AlignmentFlag.AlignLeft)

    def _settings_section(self, title: str) -> QLabel:
        lbl = QLabel(f'<span style="color:{C_TEXT2}; font-size:11px; letter-spacing:1px;">'
                     f'{title.upper()}</span>')
        lbl.setStyleSheet(f"padding-top: 4px; border-bottom: 1px solid {C_BORDER}; padding-bottom: 4px;")
        return lbl

    def _settings_browse_folder(self, line_edit: QLineEdit):
        path = QFileDialog.getExistingDirectory(self, "Select Folder", line_edit.text())
        if path:
            line_edit.setText(path)

    def _save_settings(self):
        self.cfg["last_output_path"] = self.set_output_input.text()
        self.cfg["output_mode"] = "azahar" if self.rb_azahar.isChecked() else "standard"
        self.cfg["scan_all_files"] = self.chk_scan_all.isChecked()
        self.cfg["dedup"] = self.chk_dedup.isChecked()
        self.cfg["dump_raw"] = self.chk_dump_raw.isChecked()
        self.cfg["verbose_logging"] = self.chk_verbose.isChecked()
        self.cfg["contact_sheet"] = self.chk_contact_sheet.isChecked()
        self.cfg["quality_report"] = self.chk_quality_report.isChecked()
        self.cfg["azahar_load_path"] = self.set_azahar_path.text()
        save_config(self.cfg)
        self.statusBar().showMessage("Settings saved", 3000)

    # ── Details panel ──

    def _build_details_panel(self):
        self.details_panel.setFixedWidth(280)
        self.details_panel.setStyleSheet(f"background: {C_SURFACE};")
        layout = QVBoxLayout(self.details_panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.lbl_detail_title = QLabel("Game Info")
        self.lbl_detail_title.setStyleSheet(f"color: {C_TEXT}; font-size: 14px; font-weight: bold;")
        layout.addWidget(self.lbl_detail_title)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {C_BORDER};")
        layout.addWidget(sep)

        self.lbl_detail_game = QLabel("No ROM loaded")
        self.lbl_detail_game.setWordWrap(True)
        self.lbl_detail_game.setStyleSheet(f"color: {C_TEXT2}; font-size: 12px;")
        layout.addWidget(self.lbl_detail_game)

        self.detail_info_frame = QFrame()
        self.detail_info_frame.setStyleSheet(f"""
            QFrame {{ background: {C_CARD}; border-radius: 6px; }}
        """)
        self.detail_info_frame.setVisible(False)
        di_layout = QVBoxLayout(self.detail_info_frame)
        di_layout.setContentsMargins(12, 8, 12, 8)
        di_layout.setSpacing(4)
        self.lbl_detail_tid = QLabel("")
        self.lbl_detail_tid.setStyleSheet(f"color: {C_TEXT2}; font-size: 11px;")
        di_layout.addWidget(self.lbl_detail_tid)
        self.lbl_detail_product = QLabel("")
        self.lbl_detail_product.setStyleSheet(f"color: {C_TEXT2}; font-size: 11px;")
        di_layout.addWidget(self.lbl_detail_product)
        self.lbl_detail_files = QLabel("")
        self.lbl_detail_files.setStyleSheet(f"color: {C_TEXT2}; font-size: 11px;")
        di_layout.addWidget(self.lbl_detail_files)
        self.lbl_detail_size = QLabel("")
        self.lbl_detail_size.setStyleSheet(f"color: {C_TEXT2}; font-size: 11px;")
        di_layout.addWidget(self.lbl_detail_size)
        layout.addWidget(self.detail_info_frame)

        # Quick actions
        layout.addSpacing(8)
        self.lbl_detail_actions = QLabel("Quick Actions")
        self.lbl_detail_actions.setStyleSheet(f"color: {C_TEXT}; font-size: 13px; font-weight: bold;")
        self.lbl_detail_actions.setVisible(False)
        layout.addWidget(self.lbl_detail_actions)

        self.btn_detail_azahar = QPushButton("  Copy to Azahar")
        self.btn_detail_azahar.setStyleSheet(_btn_secondary())
        self.btn_detail_azahar.setVisible(False)
        self.btn_detail_azahar.clicked.connect(self._copy_to_azahar)
        layout.addWidget(self.btn_detail_azahar)

        self.btn_detail_open = QPushButton("  Open in Explorer")
        self.btn_detail_open.setStyleSheet(_btn_secondary())
        self.btn_detail_open.setVisible(False)
        self.btn_detail_open.clicked.connect(self._open_output_folder)
        layout.addWidget(self.btn_detail_open)

        layout.addStretch()

        # About
        btn_about = QPushButton("About 3DS Texture Forge")
        btn_about.setStyleSheet(_btn_ghost())
        btn_about.clicked.connect(self._show_about)
        layout.addWidget(btn_about)

    def _update_details(self, scan_result=None, game_name="", output_dir=""):
        if scan_result:
            self.lbl_detail_game.setText(f'<span style="color:{C_TEXT}; font-size:14px;">{game_name}</span>')
            self.lbl_detail_tid.setText(f"Title ID: {scan_result.get('title_id', 'N/A')}")
            self.lbl_detail_product.setText(f"Product: {scan_result.get('product_code', 'N/A')}")
            self.lbl_detail_files.setText(f"Files: {scan_result.get('file_count', 0):,}")
            if self._loaded_path:
                size_mb = os.path.getsize(self._loaded_path) / (1024 * 1024)
                self.lbl_detail_size.setText(f"ROM size: {size_mb:.0f} MB")
            self.detail_info_frame.setVisible(True)
        else:
            self.lbl_detail_game.setText("No ROM loaded")
            self.detail_info_frame.setVisible(False)

        has_output = output_dir and os.path.isdir(output_dir)
        self.lbl_detail_actions.setVisible(has_output)
        self.btn_detail_open.setVisible(has_output)
        self.btn_detail_azahar.setVisible(has_output and bool(self.cfg.get("azahar_load_path")))

    # ── Status bar ──

    def _build_status_bar(self):
        sb = QStatusBar()
        sb.setFixedHeight(24)
        sb.setStyleSheet(f"""
            QStatusBar {{
                background: {C_SIDEBAR_BG}; color: {C_TEXT2};
                font-size: 11px; border-top: 1px solid {C_BORDER};
            }}
        """)
        self.setStatusBar(sb)
        sb.showMessage("Ready")

    # ══════════════════════════════════════════════
    # File handling
    # ══════════════════════════════════════════════

    def _on_file_dropped(self, path: str):
        if path == "":
            self._browse_input()
            return
        if not path.lower().endswith((".3ds", ".cia", ".cxi", ".app")):
            self._show_error("Not a 3DS ROM",
                             "Supported formats: .3ds, .cia\nMake sure the file is decrypted.")
            return
        if not os.path.isfile(path):
            self._show_error("File not found", f"Could not find: {path}")
            return
        self._load_file(path)

    def _browse_input(self):
        start_dir = os.path.dirname(self.cfg.get("last_input_path", "")) or ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select 3DS ROM", start_dir,
            "3DS ROMs (*.3ds *.cia *.cxi *.app);;All Files (*)",
        )
        if path:
            self._load_file(path)

    def _load_file(self, path: str):
        self._loaded_path = path
        self.cfg["last_input_path"] = path
        self._hide_error()
        self.results_frame.setVisible(False)
        self.drop_zone.set_loaded(path, "Scanning...")
        self.statusBar().showMessage(f"Scanning {os.path.basename(path)}...")

        result = scan_rom(path)
        if result["success"]:
            self._scan_result = result
            self._game_name = get_game_name(result.get("title_id", ""), result.get("product_code", ""))
            info = f"{self._game_name}  |  {result['product_code']}  |  {result['file_count']} files"
            self.drop_zone.set_loaded(path, info)

            safe_name = re.sub(r'[<>:"/\\|?*]', '', self._game_name).strip() or "output"
            custom_out = self.cfg.get("last_output_path", "")
            if custom_out:
                self._output_dir = os.path.join(custom_out, safe_name)
            else:
                self._output_dir = os.path.abspath(os.path.join("output", safe_name))

            self.btn_extract.setEnabled(True)
            self.btn_add_queue.setEnabled(True)
            self._hide_error()
            self._update_details(result, self._game_name)
            self.statusBar().showMessage(f"Loaded: {self._game_name}", 5000)
        elif result.get("is_encrypted"):
            self.drop_zone.clear()
            self._show_error("ROM is encrypted",
                             "Decrypt with GodMode9 first.\nSearch 'GodMode9 decrypt 3DS ROM' for help.")
            self._update_details()
        else:
            self.drop_zone.clear()
            self._show_error("Cannot read file", result.get("error_message", "Unknown error"))
            self._update_details()

    # ══════════════════════════════════════════════
    # Extraction
    # ══════════════════════════════════════════════

    def _do_extract(self):
        if not self._loaded_path or not os.path.isfile(self._loaded_path):
            return
        if not self._output_dir:
            return

        self.btn_extract.setEnabled(False)
        self.btn_extract.setText("   EXTRACTING...   ")
        self.results_frame.setVisible(False)
        self._hide_error()
        self.progress_frame.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.lbl_progress_phase.setText("Loading ROM...")
        self.lbl_progress_stats.setText("")
        self.btn_cancel.setVisible(True)
        self._extract_start_time = time.time()
        self.log_box.clear()

        if self.chk_verbose.isChecked():
            logging.root.setLevel(logging.DEBUG)
        else:
            logging.root.setLevel(logging.INFO)

        options = {
            "scan_all": self.chk_scan_all.isChecked(),
            "dedup": self.chk_dedup.isChecked(),
            "dump_raw": self.chk_dump_raw.isChecked(),
            "verbose": self.chk_verbose.isChecked(),
        }

        self.worker = ExtractWorker(self._loaded_path, self._output_dir, options)
        self.worker.log_message.connect(self._append_log)
        self.worker.progress.connect(self._on_extract_progress)
        self.worker.phase_changed.connect(self._on_phase_changed)
        self.worker.finished.connect(self._on_extract_finished)
        self.worker.start()

    def _on_phase_changed(self, text: str):
        self.lbl_progress_phase.setText(text)
        self.statusBar().showMessage(text)

    def _on_extract_progress(self, current: int, total: int, file_path: str, tex_count: int):
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
            elapsed = time.time() - self._extract_start_time
            pct = current / total if total > 0 else 0
            eta_str = ""
            if pct > 0.05 and elapsed > 2:
                remaining = elapsed / pct * (1 - pct)
                m, s = divmod(int(remaining), 60)
                eta_str = f"  |  ETA: {m}:{s:02d}"
            self.lbl_progress_stats.setText(
                f"{current}/{total} files  |  {tex_count:,} textures  |  "
                f"{elapsed:.0f}s elapsed{eta_str}"
            )

    def _cancel_extract(self):
        if self.worker and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait(2000)
            self.worker = None
            self.progress_frame.setVisible(False)
            self.btn_extract.setEnabled(True)
            self.btn_extract.setText("   EXTRACT TEXTURES   ")
            self.statusBar().showMessage("Extraction cancelled", 3000)

    def _on_extract_finished(self, result: dict):
        self.worker = None
        self.progress_frame.setVisible(False)
        self.btn_cancel.setVisible(False)
        self.btn_extract.setText("   EXTRACT TEXTURES   ")
        self.btn_extract.setEnabled(True)

        if result.get("success"):
            s = result.get("summary", {})
            decoded = s.get("textures_decoded_ok", 0)
            unique = s.get("textures_unique", decoded)
            suspicious = s.get("suspicious_outputs", 0)
            elapsed = result.get("elapsed", 0)
            game_name = result.get("game_name", self._game_name)
            quality_str = f"{s.get('quality_score', 0)}%" if 'quality_score' in s else "--"

            self._result_output_dir = result.get("output_dir", self._output_dir)

            # Headline
            if decoded > 0:
                self.lbl_results_headline.setText(
                    f'<span style="color:{C_SUCCESS};">Extracted {decoded:,} textures from {game_name}</span>')
            else:
                self.lbl_results_headline.setText(
                    f'<span style="color:{C_WARNING};">No textures found in {game_name}</span>')

            # Metric pills
            self.pill_textures.set_value(f"{decoded:,}", C_SUCCESS)
            quality_pct = round((1 - suspicious / max(decoded, 1)) * 100, 1) if decoded > 0 else 0
            self.pill_quality.set_value(f"{quality_pct}%",
                                        C_SUCCESS if quality_pct >= 90 else C_WARNING)
            self.pill_unique.set_value(f"{unique:,}", C_ACCENT2)
            self.pill_time.set_value(f"{elapsed}s", C_TEXT2)

            # Manifest button
            manifest_path = os.path.join(self._result_output_dir, "manifest.json")
            self.btn_view_manifest.setVisible(os.path.isfile(manifest_path))

            # Thumbnails
            self._load_thumbnails(self._result_output_dir, decoded)

            self.results_frame.setVisible(True)
            self._update_details(self._scan_result, game_name, self._result_output_dir)

            # Add to history
            self._add_history_entry(game_name, decoded, f"{quality_pct}%", self._result_output_dir)

            self.statusBar().showMessage(
                f"Done: {decoded:,} textures at {quality_pct}% quality in {elapsed}s", 10000)

            # Continue queue if running
            if self._queue_running:
                QTimer.singleShot(1000, self._run_next_in_queue)

        elif result.get("is_encrypted"):
            self._show_error("ROM is encrypted",
                             "Decrypt with GodMode9 first.")
        else:
            self._show_error("Extraction failed",
                             result.get("error_message", "Unknown error"))

        save_config(self.cfg)

    # ── Results helpers ──

    def _load_thumbnails(self, output_dir: str, total_decoded: int):
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
            scaled = pixmap.scaled(80, 80,
                                    Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)
            lbl = QLabel()
            lbl.setPixmap(scaled)
            lbl.setToolTip(os.path.basename(png_path))
            lbl.setCursor(Qt.CursorShape.PointingHandCursor)
            lbl.setStyleSheet("border: none; padding: 2px;")
            lbl.mousePressEvent = lambda event, p=png_path: self._open_image(p)
            self.thumb_layout.addWidget(lbl)

        remaining = total_decoded - len(previews)
        if remaining > 0:
            more = QLabel(f"... +{remaining:,} more")
            more.setStyleSheet(f"color: {C_TEXT2}; font-style: italic; padding: 8px; border: none;")
            self.thumb_layout.addWidget(more)

    def _open_image(self, path: str):
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_output_folder(self):
        out_dir = self._result_output_dir or self._output_dir
        if out_dir and os.path.isdir(out_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(out_dir))

    def _open_manifest(self):
        out_dir = self._result_output_dir or self._output_dir
        if out_dir:
            p = os.path.join(out_dir, "manifest.json")
            if os.path.isfile(p):
                QDesktopServices.openUrl(QUrl.fromLocalFile(p))

    def _copy_to_azahar(self):
        az_path = self.cfg.get("azahar_load_path", "")
        if not az_path or not self._result_output_dir:
            self.statusBar().showMessage("Set Azahar load path in Settings first", 5000)
            return
        import shutil
        src = self._result_output_dir
        if not os.path.isdir(src):
            return
        # Copy all PNGs to Azahar load path
        tex_dir = os.path.join(src, "textures")
        if not os.path.isdir(tex_dir):
            tex_dir = src
        count = 0
        for f in os.listdir(tex_dir):
            if f.lower().endswith(".png"):
                shutil.copy2(os.path.join(tex_dir, f), os.path.join(az_path, f))
                count += 1
        self.statusBar().showMessage(f"Copied {count} textures to Azahar", 5000)

    # ── Error display ──

    def _show_error(self, title: str, body: str, is_warning: bool = False):
        border_color = C_WARNING if is_warning else C_ERROR
        bg_color = "#2a2a1a" if is_warning else "#2a1a1a"
        self.error_panel.setStyleSheet(f"""
            QFrame {{
                background: {bg_color}; border: 1px solid {border_color};
                border-radius: 8px;
            }}
        """)
        self.lbl_error.setText(
            f'<span style="color:{border_color}; font-size:13px; font-weight:bold;">'
            f'{title}</span><br><br>'
            f'<span style="color:{C_TEXT}; font-size:11px; white-space:pre-wrap;">{body}</span>'
        )
        self.error_panel.setVisible(True)

    def _hide_error(self):
        self.error_panel.setVisible(False)

    # ── About ──

    def _show_about(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("About 3DS Texture Forge")
        dlg.setFixedSize(460, 360)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(24, 24, 24, 24)
        text = QTextBrowser()
        text.setOpenExternalLinks(True)
        text.setStyleSheet(f"background: {C_SURFACE}; border: none; color: {C_TEXT};")
        text.setHtml(f"""
            <h2 style="color:{C_TEXT};">3DS Texture Forge v1.1</h2>
            <p>Extract textures from decrypted Nintendo 3DS game ROMs.</p>
            <p>Supports 40+ games with over 1.5 million textures.</p>
            <p>Features: quality reports, contact sheets, deduplication,
            Azahar/Citra custom texture pack output, batch extraction.</p>
            <p style="margin-top:16px;">
            <a href="https://github.com/ZoomiesZaggy/3DS-Texture-Forge"
               style="color:{C_ACCENT};">
            github.com/ZoomiesZaggy/3DS-Texture-Forge</a></p>
        """)
        layout.addWidget(text)
        btn = QPushButton("Close")
        btn.setStyleSheet(_btn_secondary())
        btn.clicked.connect(dlg.close)
        layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignRight)
        dlg.exec()

    # ── Drag and Drop on main window ──

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            self._on_file_dropped(url.toLocalFile())
            return

    # ── Window lifecycle ──

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait(2000)

        self.cfg["window_width"] = self.width()
        self.cfg["window_height"] = self.height()
        if self._loaded_path:
            self.cfg["last_input_path"] = self._loaded_path
        self._save_settings()
        super().closeEvent(event)
