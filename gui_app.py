"""
3DS Texture Forge — PySide6 GUI for 3ds-tex-extract.

Single-window dark-themed application for extracting textures
from decrypted Nintendo 3DS ROMs.
"""

import logging
import os
import subprocess
import sys
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import (
    QColor, QDesktopServices, QDragEnterEvent, QDropEvent,
    QFont, QPalette, QPixmap, QAction,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget,
    QSizePolicy,
)

from config import load_config, save_config
from backend import scan_rom, run_extraction, get_output_previews

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Logging handler that routes to a signal
# ──────────────────────────────────────────────

class SignalLogHandler(logging.Handler):
    """Logging handler that emits records via a callback."""

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def emit(self, record):
        try:
            msg = self.format(record)
            self.callback(msg)
        except Exception:
            pass


# ──────────────────────────────────────────────
# Worker threads
# ──────────────────────────────────────────────

class ScanWorker(QThread):
    finished = Signal(dict)
    log_message = Signal(str)

    def __init__(self, filepath: str):
        super().__init__()
        self.filepath = filepath

    def run(self):
        self.log_message.emit(f"Scanning: {os.path.basename(self.filepath)}")
        result = scan_rom(self.filepath)
        if result["success"]:
            self.log_message.emit(
                f"Scan complete: {result['product_code']} | "
                f"{result['title_id']} | {result['file_count']} files"
            )
        else:
            self.log_message.emit(f"Scan failed: {result['error_message']}")
        self.finished.emit(result)


class ExtractWorker(QThread):
    finished = Signal(dict)
    progress = Signal(int, int, str)
    log_message = Signal(str)

    def __init__(self, filepath: str, output_dir: str, options: dict):
        super().__init__()
        self.filepath = filepath
        self.output_dir = output_dir
        self.options = options

    def _on_progress(self, current, total, file_path, fmt_name, w, h):
        self.progress.emit(current, total, file_path)

    def run(self):
        self.log_message.emit(f"Extracting: {os.path.basename(self.filepath)}")
        self.log_message.emit(f"Output: {self.output_dir}")
        result = run_extraction(
            self.filepath, self.output_dir, self.options,
            progress_callback=self._on_progress,
        )
        if result["success"]:
            s = result.get("summary", {})
            self.log_message.emit(
                f"Extraction complete: {s.get('textures_decoded_ok', 0)} textures, "
                f"{s.get('textures_failed', 0)} failed, {result['elapsed']}s"
            )
        else:
            self.log_message.emit(f"Extraction failed: {result['error_message']}")
        self.finished.emit(result)


# ──────────────────────────────────────────────
# Dark palette
# ──────────────────────────────────────────────

def apply_dark_palette(app: QApplication):
    """Apply a dark color palette to the application."""
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
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(128, 128, 128))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(128, 128, 128))
    app.setPalette(palette)
    app.setStyle("Fusion")


# ──────────────────────────────────────────────
# Main Window
# ──────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.scan_result = None
        self.extract_result = None
        self.worker = None

        self.setWindowTitle("3DS Texture Forge")
        self.setMinimumSize(960, 680)
        self.resize(self.cfg.get("window_width", 1000),
                    self.cfg.get("window_height", 720))
        self.setAcceptDrops(True)

        self._build_menu()
        self._build_ui()
        self._setup_logging()

        # Restore last paths
        if self.cfg.get("last_input_path"):
            self.input_path.setText(self.cfg["last_input_path"])
        if self.cfg.get("last_output_path"):
            self.output_path.setText(self.cfg["last_output_path"])

        self.chk_scan_all.setChecked(self.cfg.get("scan_all_files", False))
        self.chk_dump_raw.setChecked(self.cfg.get("dump_raw", False))
        self.chk_verbose.setChecked(self.cfg.get("verbose_logging", False))

    # ── Menu ──

    def _build_menu(self):
        menu_bar = self.menuBar()
        help_menu = menu_bar.addMenu("Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _show_about(self):
        QMessageBox.about(self, "About 3DS Texture Forge",
            "3DS Texture Forge v1.0\n\n"
            "Extracts textures from decrypted 3DS game ROMs for use with "
            "the Azahar emulator.\n\n"
            "Known limitations:\n"
            "  - Requires decrypted ROM input\n"
            "  - Best tested with Resident Evil: Revelations\n"
            "  - Some Capcom TEX header variants may not parse correctly\n"
            "  - BCH texture extraction uses heuristic scanning\n"
            "  - Not all games' texture formats are supported yet\n\n"
            "Textures are extracted to PNG. To use them as Azahar custom "
            "textures, you will need to match them to the hash-based "
            "filenames Azahar expects (use Azahar's built-in texture "
            "dumping feature for this step)."
        )

    # ── Logging ──

    def _setup_logging(self):
        handler = SignalLogHandler(self._append_log_safe)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logging.root.addHandler(handler)
        logging.root.setLevel(logging.INFO)

    def _append_log_safe(self, msg: str):
        # May be called from worker thread — use thread-safe approach
        if QThread.currentThread() == QApplication.instance().thread():
            self._append_log(msg)
        else:
            # Queue via signal; we'll use the worker's log_message signal instead
            pass

    def _append_log(self, msg: str):
        self.log_box.appendPlainText(msg)
        sb = self.log_box.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ── UI Construction ──

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(8)

        # Section 1: Input
        grp_input = QGroupBox("Input ROM")
        vl = QVBoxLayout(grp_input)
        hl = QHBoxLayout()
        self.input_path = QLineEdit()
        self.input_path.setPlaceholderText(
            "Drop a .3ds or .cia file here, or click Browse...")
        self.input_path.setReadOnly(True)
        hl.addWidget(self.input_path)
        btn_browse_input = QPushButton("Browse...")
        btn_browse_input.clicked.connect(self._browse_input)
        hl.addWidget(btn_browse_input)
        vl.addLayout(hl)
        self.lbl_rom_info = QLabel("No file loaded")
        self.lbl_rom_info.setStyleSheet("color: gray; font-style: italic;")
        vl.addWidget(self.lbl_rom_info)
        layout.addWidget(grp_input)

        # Section 2: Output
        grp_output = QGroupBox("Output Folder")
        vl2 = QVBoxLayout(grp_output)
        hl2 = QHBoxLayout()
        self.output_path = QLineEdit()
        self.output_path.setPlaceholderText("Output directory for extracted textures")
        hl2.addWidget(self.output_path)
        btn_browse_output = QPushButton("Browse...")
        btn_browse_output.clicked.connect(self._browse_output)
        hl2.addWidget(btn_browse_output)
        self.btn_open_folder = QPushButton("Open Output Folder")
        self.btn_open_folder.setEnabled(False)
        self.btn_open_folder.clicked.connect(self._open_output_folder)
        hl2.addWidget(self.btn_open_folder)
        vl2.addLayout(hl2)
        layout.addWidget(grp_output)

        # Section 3: Actions
        grp_actions = QGroupBox("Actions")
        vl3 = QVBoxLayout(grp_actions)
        hl3 = QHBoxLayout()

        self.btn_scan = QPushButton("Scan")
        self.btn_scan.setToolTip("Load ROM and report file count (fast)")
        self.btn_scan.clicked.connect(self._do_scan)
        hl3.addWidget(self.btn_scan)

        self.btn_extract = QPushButton("  Extract Textures  ")
        self.btn_extract.setToolTip("Full extraction pipeline")
        self.btn_extract.setStyleSheet(
            "QPushButton { background-color: #2a82da; color: white; "
            "font-weight: bold; padding: 6px 16px; }"
            "QPushButton:hover { background-color: #3a92ea; }"
            "QPushButton:disabled { background-color: #555; color: #888; }"
        )
        self.btn_extract.clicked.connect(self._do_extract)
        hl3.addWidget(self.btn_extract)

        self.btn_manifest = QPushButton("Open Manifest")
        self.btn_manifest.setEnabled(False)
        self.btn_manifest.clicked.connect(self._open_manifest)
        hl3.addWidget(self.btn_manifest)

        hl3.addStretch()
        vl3.addLayout(hl3)

        hl_opts = QHBoxLayout()
        self.chk_scan_all = QCheckBox("Deep scan (brute-force all files)")
        hl_opts.addWidget(self.chk_scan_all)
        self.chk_dump_raw = QCheckBox("Save raw texture data (.bin)")
        hl_opts.addWidget(self.chk_dump_raw)
        self.chk_verbose = QCheckBox("Verbose logging")
        hl_opts.addWidget(self.chk_verbose)
        hl_opts.addStretch()
        vl3.addLayout(hl_opts)
        layout.addWidget(grp_actions)

        # Section 4: Progress
        grp_progress = QGroupBox("Progress")
        vl4 = QVBoxLayout(grp_progress)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        vl4.addWidget(self.progress_bar)
        self.lbl_status = QLabel("Ready.")
        vl4.addWidget(self.lbl_status)
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFont(QFont("Consolas", 9))
        self.log_box.setMaximumHeight(160)
        vl4.addWidget(self.log_box)
        layout.addWidget(grp_progress)

        # Section 5: Results (hidden initially)
        self.grp_results = QGroupBox("Results")
        self.grp_results.setVisible(False)
        vl5 = QVBoxLayout(self.grp_results)

        self.lbl_results_stats = QLabel("")
        vl5.addWidget(self.lbl_results_stats)

        # Thumbnail scroll area
        self.thumb_scroll = QScrollArea()
        self.thumb_scroll.setWidgetResizable(True)
        self.thumb_scroll.setMinimumHeight(120)
        self.thumb_scroll.setMaximumHeight(240)
        self.thumb_widget = QWidget()
        self.thumb_layout = QHBoxLayout(self.thumb_widget)
        self.thumb_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.thumb_scroll.setWidget(self.thumb_widget)
        vl5.addWidget(self.thumb_scroll)

        layout.addWidget(self.grp_results)
        layout.addStretch()

    # ── Drag and Drop ──

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                path = url.toLocalFile().lower()
                if path.endswith((".3ds", ".cia", ".cxi", ".app")):
                    event.acceptProposedAction()
                    return

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith((".3ds", ".cia", ".cxi", ".app")):
                self.input_path.setText(path)
                self._do_scan()
                return

    # ── Browse buttons ──

    def _browse_input(self):
        start_dir = os.path.dirname(self.cfg.get("last_input_path", "")) or ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select 3DS ROM",
            start_dir,
            "3DS ROMs (*.3ds *.cia *.cxi *.app);;All Files (*)",
        )
        if path:
            self.input_path.setText(path)
            self._do_scan()

    def _browse_output(self):
        start_dir = self.output_path.text() or ""
        path = QFileDialog.getExistingDirectory(self, "Select Output Folder", start_dir)
        if path:
            self.output_path.setText(path)

    # ── Actions ──

    def _set_busy(self, busy: bool):
        self.btn_scan.setEnabled(not busy)
        self.btn_extract.setEnabled(not busy)

    def _do_scan(self):
        path = self.input_path.text().strip()
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "No File",
                "Please select a valid ROM file first.")
            return

        self._set_busy(True)
        self.lbl_status.setText("Loading ROM...")
        self.progress_bar.setRange(0, 0)  # indeterminate
        self.lbl_rom_info.setText("Scanning...")
        self.lbl_rom_info.setStyleSheet("color: #d4d4d4;")

        self.worker = ScanWorker(path)
        self.worker.log_message.connect(self._append_log)
        self.worker.finished.connect(self._on_scan_finished)
        self.worker.start()

    def _on_scan_finished(self, result: dict):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100 if result["success"] else 0)
        self._set_busy(False)
        self.worker = None

        if result["success"]:
            self.scan_result = result
            info = (f"{result['product_code']} | {result['title_id']} | "
                    f"{result['file_count']} files in RomFS")
            self.lbl_rom_info.setText(info)
            self.lbl_rom_info.setStyleSheet("color: #90ee90;")
            self.lbl_status.setText("Scan complete. Ready to extract.")

            # Save and auto-fill output path
            self.cfg["last_input_path"] = self.input_path.text()
            if not self.output_path.text().strip():
                default_out = os.path.join("output", result["title_id"])
                self.output_path.setText(os.path.abspath(default_out))
            save_config(self.cfg)
        elif result["is_encrypted"]:
            self.lbl_rom_info.setText("Encrypted ROM")
            self.lbl_rom_info.setStyleSheet("color: #ff6b6b;")
            self.lbl_status.setText("Cannot process encrypted ROM.")
            QMessageBox.warning(self, "Encrypted ROM",
                "This ROM is encrypted. Please decrypt it first using "
                "GodMode9 or a similar tool.\n\n"
                "3DS Texture Forge cannot extract textures from encrypted ROMs.")
        else:
            self.lbl_rom_info.setText("Failed to parse")
            self.lbl_rom_info.setStyleSheet("color: #ff6b6b;")
            self.lbl_status.setText("Scan failed.")
            QMessageBox.warning(self, "Parse Error",
                f"Could not parse this file.\n\n"
                f"Supported formats: .3ds, .cia, .cxi, .app (decrypted only).\n\n"
                f"Error: {result['error_message']}")

    def _do_extract(self):
        path = self.input_path.text().strip()
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "No File",
                "Please select a valid ROM file first.")
            return

        out_dir = self.output_path.text().strip()
        if not out_dir:
            QMessageBox.warning(self, "No Output",
                "Please specify an output directory.")
            return

        self._set_busy(True)
        self.grp_results.setVisible(False)
        self.lbl_status.setText("Loading ROM...")
        self.progress_bar.setRange(0, 0)  # indeterminate initially

        options = {
            "scan_all": self.chk_scan_all.isChecked(),
            "dump_raw": self.chk_dump_raw.isChecked(),
            "verbose": self.chk_verbose.isChecked(),
        }

        if self.chk_verbose.isChecked():
            logging.root.setLevel(logging.DEBUG)
        else:
            logging.root.setLevel(logging.INFO)

        self.worker = ExtractWorker(path, out_dir, options)
        self.worker.log_message.connect(self._append_log)
        self.worker.progress.connect(self._on_extract_progress)
        self.worker.finished.connect(self._on_extract_finished)
        self.worker.start()

    def _on_extract_progress(self, current: int, total: int, file_path: str):
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
            fname = os.path.basename(file_path) if file_path else ""
            self.lbl_status.setText(
                f"Extracting textures ({current}/{total})... {fname}")

    def _on_extract_finished(self, result: dict):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100 if result["success"] else 0)
        self._set_busy(False)
        self.worker = None

        if result["success"]:
            self.extract_result = result
            s = result.get("summary", {})
            decoded = s.get("textures_decoded_ok", 0)
            failed = s.get("textures_failed", 0)
            title_id = s.get("title_id", "")
            elapsed = result.get("elapsed", 0)

            self.lbl_status.setText("Done.")

            # Stats
            fail_color = "red" if failed > 0 else "gray"
            self.lbl_results_stats.setText(
                f'<span style="color: #90ee90;">Textures extracted: {decoded}</span>'
                f'&nbsp;&nbsp;|&nbsp;&nbsp;'
                f'<span style="color: {fail_color};">Failed: {failed}</span>'
                f'&nbsp;&nbsp;|&nbsp;&nbsp;'
                f'Title ID: {title_id}'
                f'&nbsp;&nbsp;|&nbsp;&nbsp;'
                f'Time: {elapsed}s'
            )

            # Enable post-extract buttons
            self.btn_open_folder.setEnabled(True)
            manifest_path = os.path.join(result["output_dir"], "manifest.json")
            self.btn_manifest.setEnabled(os.path.isfile(manifest_path))

            # Save paths
            self.cfg["last_input_path"] = self.input_path.text()
            self.cfg["last_output_path"] = self.output_path.text()
            save_config(self.cfg)

            # Load thumbnails
            self._load_thumbnails(result["output_dir"])

            self.grp_results.setVisible(True)

            if decoded == 0:
                QMessageBox.information(self, "No Textures Found",
                    "No textures were found.\n\n"
                    "Try enabling 'Deep scan' to brute-force search all files.")

        elif result["is_encrypted"]:
            self.lbl_status.setText("Cannot process encrypted ROM.")
            QMessageBox.warning(self, "Encrypted ROM",
                "This ROM is encrypted. Please decrypt it first using "
                "GodMode9 or a similar tool.")
        else:
            self.lbl_status.setText("Extraction failed.")
            QMessageBox.warning(self, "Extraction Error",
                f"Extraction failed:\n\n{result['error_message']}")

    def _load_thumbnails(self, output_dir: str):
        # Clear existing thumbnails
        while self.thumb_layout.count():
            item = self.thumb_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        previews = get_output_previews(output_dir, max_count=12)
        total_pngs = 0
        textures_dir = os.path.join(output_dir, "textures")
        if os.path.isdir(textures_dir):
            for root, dirs, files in os.walk(textures_dir):
                total_pngs += sum(1 for f in files if f.lower().endswith(".png"))

        for png_path in previews:
            pixmap = QPixmap(png_path)
            if pixmap.isNull():
                continue
            scaled = pixmap.scaled(96, 96,
                                   Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            lbl = QLabel()
            lbl.setPixmap(scaled)
            lbl.setToolTip(os.path.basename(png_path))
            lbl.setCursor(Qt.CursorShape.PointingHandCursor)
            # Store path for click handler
            lbl.setProperty("png_path", png_path)
            lbl.mousePressEvent = lambda event, p=png_path: self._open_image(p)
            self.thumb_layout.addWidget(lbl)

        remaining = total_pngs - len(previews)
        if remaining > 0:
            more_lbl = QLabel(f"and {remaining} more...")
            more_lbl.setStyleSheet("color: gray; font-style: italic; padding: 8px;")
            self.thumb_layout.addWidget(more_lbl)

    def _open_image(self, path: str):
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_output_folder(self):
        out_dir = self.output_path.text().strip()
        if out_dir and os.path.isdir(out_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(out_dir))

    def _open_manifest(self):
        out_dir = self.output_path.text().strip()
        if not out_dir:
            return
        manifest_path = os.path.join(out_dir, "manifest.json")
        if os.path.isfile(manifest_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(manifest_path))

    # ── Window lifecycle ──

    def closeEvent(self, event):
        self.cfg["window_width"] = self.width()
        self.cfg["window_height"] = self.height()
        self.cfg["last_input_path"] = self.input_path.text()
        self.cfg["last_output_path"] = self.output_path.text()
        self.cfg["scan_all_files"] = self.chk_scan_all.isChecked()
        self.cfg["dump_raw"] = self.chk_dump_raw.isChecked()
        self.cfg["verbose_logging"] = self.chk_verbose.isChecked()
        save_config(self.cfg)
        super().closeEvent(event)
