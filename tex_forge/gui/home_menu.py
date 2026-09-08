"""3DS Texture Forge: HOME Menu UI.

A reskin of the GUI styled after the Nintendo 3DS HOME Menu. It reuses
tex_forge.gui.backend unchanged and is built as a replacement for the vendored
_gui_app_v1.py. entry.py keeps launching v1 until this reaches parity.

Design split (see PROGRESS.md): a non-interactive top "stage" that previews
work, and an interactive bottom "workbench" (the game grid, controls, queue).

Pass 1 scope: window shell with the stage/workbench split, the top status bar,
and the game grid populating from the configured ROM paths. Selecting a tile
loads its metadata into the stage via scan_rom and queues it. Extraction wiring,
the heartbeat LED behavior, full 3DS visual polish, the Activity Log, and theme
switching come in later passes.

House rule: no em dashes anywhere (use commas, colons, semicolons, parentheses).

Run standalone for testing:  python -m tex_forge.gui.home_menu
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Dict, List, Optional

from PySide6.QtCore import (
    Qt, QThread, Signal, QTimer, QSize, QDateTime, QRectF,
    QPropertyAnimation, QEasingCurve,
)
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPixmap, QBrush, QPen, QImage,
    QPainterPath, QLinearGradient, QFontDatabase,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMenu, QPushButton, QScrollArea, QSplitter, QVBoxLayout, QWidget,
    QFileDialog, QSizePolicy, QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
)

import json
import re

from tex_forge.gui.backend import (
    scan_rom, run_extraction, get_output_previews, get_rom_icon_rgba,
    get_rom_banner_rgba,
)
from tex_forge.gui.config import load_config, save_config
from tex_forge.metadata.games import get_game_name


def rgba_to_pixmap(arr) -> Optional[QPixmap]:
    """Convert an (H, W, 4) uint8 RGBA ndarray to a QPixmap, or None."""
    if arr is None:
        return None
    try:
        import numpy as np
        a = np.ascontiguousarray(arr, dtype=np.uint8)
        h, w = a.shape[:2]
        img = QImage(a.data, w, h, 4 * w, QImage.Format.Format_RGBA8888)
        # .copy() detaches from the numpy buffer so the data can be freed
        return QPixmap.fromImage(img.copy())
    except Exception:
        return None


# ==============================================================
# Theme (Pass 1 ships the default Sky palette; switching is a later pass)
# ==============================================================

SKY_THEME = {
    "name": "Sky",
    "bg_top": "#B3E5FC",
    "bg_bottom": "#E1F5FE",
    "stage_bg": "#0E2A38",      # the top screen reads like a lit panel
    "stage_text": "#EAF6FB",
    "stage_dim": "#9FC4D4",
    "tile_bg": "#FFFFFF",
    "tile_border": "#BFE3F4",
    "tile_sel": "#00B7EB",
    "text": "#2B3A42",
    "text_dim": "#5C7682",
    "accent": "#00B7EB",
    "brand_red": "#E60012",
    "seam": "#6FA8C4",
    "panel": "#EAF6FC",
}

DARK_THEME = {
    "name": "Dark",
    "bg_top": "#1B2733",
    "bg_bottom": "#10171F",
    "stage_bg": "#0A1118",
    "stage_text": "#E8F0F5",
    "stage_dim": "#8AA0AE",
    "tile_bg": "#1E2C39",
    "tile_border": "#33485A",
    "tile_sel": "#00B7EB",
    "text": "#E8F0F5",
    "text_dim": "#8DA2B0",
    "accent": "#00B7EB",
    "brand_red": "#E60012",
    "seam": "#33485A",
    "panel": "#26384A",
}

CORAL_THEME = {
    "name": "Coral",
    "bg_top": "#FFE0D6",
    "bg_bottom": "#FFF2EC",
    "stage_bg": "#3A1E1A",
    "stage_text": "#FFEDE6",
    "stage_dim": "#D8A99B",
    "tile_bg": "#FFFFFF",
    "tile_border": "#F5C9BC",
    "tile_sel": "#FF6B4A",
    "text": "#3A2A24",
    "text_dim": "#8A6A5E",
    "accent": "#FF6B4A",
    "brand_red": "#E60012",
    "seam": "#E8A593",
    "panel": "#FFE3DA",
}

THEMES = {"sky": SKY_THEME, "dark": DARK_THEME, "coral": CORAL_THEME}

# Active theme. A mutable copy so set_theme() can swap values in place and every
# THEME[...] lookup (including those baked into stylesheets we re-run on a theme
# change, and those read at paint time) picks up the new palette.
THEME = dict(SKY_THEME)


def set_theme(name: str) -> None:
    """Swap the active palette in place (keeps the THEME identity stable)."""
    palette = THEMES.get(name, SKY_THEME)
    THEME.clear()
    THEME.update(palette)


def _lighten(hexstr: str, factor: int = 118) -> str:
    """Return a lighter shade of a hex color (factor > 100 lightens)."""
    return QColor(hexstr).lighter(factor).name()

# Rounded humanist sans, bundled (OFL). Resolved through _asset so it works both
# from source and from a PyInstaller bundle. Falls back to a rounded stack.
FONT_FAMILY = "Nunito"
_FONT_FILE = "Nunito-VariableFont_wght.ttf"


def _asset(*parts) -> str:
    """Resolve a bundled asset path for both source runs and frozen builds."""
    here = os.path.dirname(os.path.abspath(__file__))
    meipass = getattr(sys, "_MEIPASS", None)
    candidates = [os.path.join(here, *parts)]
    if meipass:
        candidates.append(os.path.join(meipass, "tex_forge", "gui", *parts))
        candidates.append(os.path.join(meipass, *parts))
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0]


def load_app_font() -> str:
    """Register the bundled rounded font; return the resolved family name."""
    global FONT_FAMILY
    try:
        path = _asset("assets", "fonts", _FONT_FILE)
        fid = QFontDatabase.addApplicationFont(path)
        fams = QFontDatabase.applicationFontFamilies(fid)
        if fams:
            FONT_FAMILY = fams[0]
    except Exception:
        pass  # fall back to the platform default; the UI still works
    return FONT_FAMILY


# Single source of truth for ROM extensions lives in the loader; the CLI
# batch command uses the same constant, so discovery can never drift.
from tex_forge.rom.loader import ROM_EXTENSIONS as ROM_EXTS

# Cap discovery so a huge No-Intro set does not stall the grid. Surfaced in the
# UI when hit (no silent truncation, per house rule).
DISCOVERY_CAP = 600


# ==============================================================
# ROM discovery
# ==============================================================

def discover_roms(paths: List[str], cap: int = DISCOVERY_CAP):
    """Walk the configured library paths and return ROM file paths.

    Returns (rom_paths, truncated_bool). De-dups by normalized path so the same
    file under two overlapping library roots only appears once.
    """
    found: List[str] = []
    seen = set()
    truncated = False
    for base in paths:
        if not base or not os.path.isdir(base):
            continue
        for root, _dirs, files in os.walk(base):
            for f in sorted(files):
                if f.lower().endswith(ROM_EXTS):
                    full = os.path.join(root, f)
                    key = os.path.normcase(os.path.abspath(full))
                    if key in seen:
                        continue
                    seen.add(key)
                    found.append(full)
                    if len(found) >= cap:
                        truncated = True
                        return found, truncated
    return found, truncated


# ==============================================================
# Worker threads (keep filesystem walks and RomFS parsing off the UI thread)
# ==============================================================

class DiscoverWorker(QThread):
    done = Signal(list, bool)  # rom_paths, truncated

    def __init__(self, paths: List[str]):
        super().__init__()
        self.paths = list(paths)

    def run(self):
        try:
            roms, truncated = discover_roms(self.paths)
        except Exception:
            roms, truncated = [], False
        self.done.emit(roms, truncated)


class ScanWorker(QThread):
    done = Signal(str, dict)  # filepath, scan_result

    def __init__(self, filepath: str):
        super().__init__()
        self.filepath = filepath

    def run(self):
        result = scan_rom(self.filepath)  # never raises
        self.done.emit(self.filepath, result)


class BannerWorker(QThread):
    """Decode a title's HOME Menu banner image off the UI thread.

    Reads the whole ROM (same trade-off as IconLoader, but only for the one
    selected title, on demand). Emits even on failure (rgba None) so the
    window can stop tracking the request; the stage simply keeps whatever it
    is already showing.
    """

    banner_ready = Signal(str, object)  # filepath, rgba ndarray or None

    def __init__(self, filepath: str):
        super().__init__()
        self.filepath = filepath

    def run(self):
        try:
            rgba = get_rom_banner_rgba(self.filepath)
        except Exception:
            rgba = None
        self.banner_ready.emit(self.filepath, rgba)


class ExtractWorker(QThread):
    """Runs run_extraction off the UI thread, forwarding the 4-arg progress
    callback (current, total, path, decoded_ok) into a Qt signal.

    Cancellation is cooperative: request_cancel() sets an Event the pipeline
    checks between files. The pipeline then drains its PNG writers, writes
    partial outputs with summary["canceled"] = True, and run() returns
    normally, so `done` still fires. QThread.terminate() is never used here:
    it cannot stop the pipeline's internal PNG-writer pool (those threads
    kept writing after a terminate) and can corrupt interpreter state.
    """

    progress = Signal(int, int, str, int)
    done = Signal(dict)

    def __init__(self, filepath: str, output_dir: str, options: dict):
        super().__init__()
        self.filepath = filepath
        self.output_dir = output_dir
        self.options = options
        self._cancel = threading.Event()

    def request_cancel(self):
        self._cancel.set()

    def _cb(self, current: int, total: int, path: str, decoded_ok: int):
        self.progress.emit(current, total, path, decoded_ok)

    def run(self):
        result = run_extraction(
            self.filepath, self.output_dir, self.options,
            progress_callback=self._cb,
            cancel_event=self._cancel,
        )
        result["output_dir"] = self.output_dir
        result["filepath"] = self.filepath
        self.done.emit(result)


class IconLoader(QThread):
    """Decode HOME Menu icons off the UI thread, one ROM at a time.

    Sequential on purpose: extract_title_icon reads the whole ROM file, so
    decoding many at once would thrash IO. Emits only successful icons (the tile
    keeps its placeholder otherwise). Skips paths already in the shared cache.
    """

    icon_ready = Signal(str, object)  # filepath, rgba ndarray

    def __init__(self, paths: List[str], have: set):
        super().__init__()
        self._paths = list(paths)
        self._have = set(have)
        self._abort = False

    def stop(self):
        self._abort = True

    def run(self):
        for p in self._paths:
            if self._abort:
                return
            if p in self._have:
                continue
            try:
                rgba = get_rom_icon_rgba(p)
            except Exception:
                rgba = None
            if rgba is not None and not self._abort:
                self.icon_ready.emit(p, rgba)


# ==============================================================
# Queue job model
# ==============================================================

class Job:
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    CANCELED = "CANCELED"

    TERMINAL = (COMPLETE, FAILED, CANCELED)

    def __init__(self, path: str):
        self.path = path
        self.state = self.QUEUED
        self.summary: dict = {}
        self.output_dir = ""
        self.error = ""
        self.decoded_ok = 0
        self.progress_text = ""


# ==============================================================
# Hinge LED (idle state in Pass 1; job-driven states come in Pass 2)
# ==============================================================

class HingeLED(QFrame):
    """Small status light styled after the 3DS hinge notification LED.

    States (see handoff):
      idle      -> steady cyan/blue (ready)
      busy      -> pulsing green (actively extracting)
      milestone -> brief orange flash (e.g. crossing a texture-count threshold)
      error     -> steady red (a job entered FAILED)
    """

    IDLE = QColor("#00B7EB")
    BUSY = QColor("#34D058")
    MILESTONE = QColor("#F5A623")
    ERROR = QColor("#E60012")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self._color = QColor(self.IDLE)
        self._pulsing = False
        self._phase = 0.0
        # Generation counter: set_idle / set_error bump it, which invalidates
        # any pending milestone-flash revert. Without this, a flash landing in
        # the final 700 ms of a run could call set_busy after the queue had
        # already finished, leaving the LED pulsing green while idle.
        self._gen = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)

    def set_idle(self):
        self._gen += 1
        self._stop_pulse()
        self._color = QColor(self.IDLE)
        self.update()

    def set_error(self):
        self._gen += 1
        self._stop_pulse()
        self._color = QColor(self.ERROR)
        self.update()

    def set_busy(self):
        self._color = QColor(self.BUSY)
        if not self._pulsing:
            self._pulsing = True
            self._phase = 0.0
            self._timer.start(45)
        self.update()

    def flash_milestone(self, revert_busy: bool = True):
        """Brief orange flash, then return to the busy pulse (or idle)."""
        was_pulsing = self._pulsing
        self._stop_pulse()
        self._color = QColor(self.MILESTONE)
        self.update()
        gen = self._gen
        to_busy = revert_busy and was_pulsing
        QTimer.singleShot(700, lambda: self._revert_flash(gen, to_busy))

    def _revert_flash(self, gen: int, to_busy: bool):
        if gen != self._gen:
            return  # idle/error happened during the flash; do not override it
        if to_busy:
            self.set_busy()
        else:
            self.set_idle()

    def _stop_pulse(self):
        self._pulsing = False
        self._timer.stop()

    def _step(self):
        # phase walks 0..1..0 for a smooth breathing pulse
        self._phase = (self._phase + 0.08) % 2.0
        self.update()

    def _pulse_alpha(self) -> int:
        if not self._pulsing:
            return 255
        tri = self._phase if self._phase <= 1.0 else (2.0 - self._phase)
        return int(150 + 105 * tri)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        core = QColor(self._color)
        core.setAlpha(self._pulse_alpha())
        glow = QColor(self._color)
        glow.setAlpha(int(core.alpha() * 0.28))
        p.setBrush(QBrush(glow))
        p.drawEllipse(0, 0, 14, 14)
        p.setBrush(QBrush(core))
        p.drawEllipse(3, 3, 8, 8)
        p.end()


# ==============================================================
# Top status bar (HOME Menu style: clock/date left, indicators right)
# ==============================================================

class StatusStrip(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(30)
        self.setStyleSheet(
            f"background: {THEME['bg_top']};"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 12, 0)
        lay.setSpacing(8)

        self.clock = QLabel("")
        self.clock.setStyleSheet(
            f"color: {THEME['text']}; font-size: 12px; font-weight: bold;"
        )
        lay.addWidget(self.clock)
        lay.addStretch()

        # Decorative signal bars + notification dot + a battery style plate.
        self.signal = QLabel("▮ ▮ ▮")  # three small bars
        self.signal.setStyleSheet(f"color: {THEME['text_dim']}; font-size: 11px;")
        lay.addWidget(self.signal)

        self.led = HingeLED()
        lay.addWidget(self.led)

        self.battery = QLabel("\U0001F50B")  # battery glyph (decorative slot)
        self.battery.setStyleSheet(f"color: {THEME['text']}; font-size: 12px;")
        lay.addWidget(self.battery)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._tick()

    def _tick(self):
        now = QDateTime.currentDateTime()
        self.clock.setText(now.toString("ddd  MMM d   h:mm AP"))

    def apply_theme(self):
        self.setStyleSheet(f"background: {THEME['bg_top']};")
        self.clock.setStyleSheet(
            f"color: {THEME['text']}; font-size: 12px; font-weight: bold;"
        )
        self.signal.setStyleSheet(f"color: {THEME['text_dim']}; font-size: 11px;")
        self.battery.setStyleSheet(f"color: {THEME['text']}; font-size: 12px;")
        self.led.update()


# ==============================================================
# Checkerboard texture preview (the stage's looking-glass)
# ==============================================================

class CheckerPreview(QLabel):
    """Paints an alpha checkerboard, then a centered pixmap when one is set."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pix: Optional[QPixmap] = None
        self.setMinimumSize(220, 160)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder = "Select a game to load it onto the stage"
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity)
        self._fade = None

    def set_pixmap(self, pix: Optional[QPixmap]):
        self._pix = pix
        self.update()
        self._fade_in()

    def _fade_in(self):
        # quick, non-blocking fade so the stage "swaps" rather than hard-cuts
        anim = QPropertyAnimation(self._opacity, b"opacity", self)
        anim.setDuration(200)
        anim.setStartValue(0.3)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        self._fade = anim  # keep a reference

    def set_placeholder(self, text: str):
        self._placeholder = text
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        rect = self.rect()
        # checkerboard
        cell = 12
        light = QColor("#1b3b4b")
        dark = QColor("#15323f")
        for y in range(rect.top(), rect.bottom() + cell, cell):
            for x in range(rect.left(), rect.right() + cell, cell):
                c = light if ((x // cell + y // cell) % 2 == 0) else dark
                p.fillRect(x, y, cell, cell, c)
        if self._pix is not None and not self._pix.isNull():
            scaled = self._pix.scaled(
                rect.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = rect.left() + (rect.width() - scaled.width()) // 2
            y = rect.top() + (rect.height() - scaled.height()) // 2
            p.drawPixmap(x, y, scaled)
        else:
            p.setPen(QColor(THEME["stage_dim"]))
            p.setFont(QFont(FONT_FAMILY, 10))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._placeholder)
        p.end()


# ==============================================================
# Stage (top screen): preview + metadata readout
# ==============================================================

class Stage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {THEME['stage_bg']};")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(18)

        self.preview = CheckerPreview()
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding,
                                   QSizePolicy.Policy.Expanding)
        lay.addWidget(self.preview, 3)

        # metadata column
        meta = QVBoxLayout()
        meta.setSpacing(6)
        self.title = QLabel("No game loaded")
        self.title.setWordWrap(True)
        self.title.setStyleSheet(
            f"color: {THEME['stage_text']}; font-size: 17px; font-weight: bold;"
        )
        meta.addWidget(self.title)

        self.fields = QLabel("")
        self.fields.setWordWrap(True)
        self.fields.setTextFormat(Qt.TextFormat.RichText)
        self.fields.setStyleSheet(
            f"color: {THEME['stage_dim']}; font-size: 12px;"
        )
        self.fields.setAlignment(Qt.AlignmentFlag.AlignTop)
        meta.addWidget(self.fields)
        meta.addStretch()

        meta_box = QWidget()
        meta_box.setLayout(meta)
        lay.addWidget(meta_box, 2)

    def show_loading(self, filepath: str):
        self.title.setText("Loading...")
        self.fields.setText(
            f"<span style='color:{THEME['stage_dim']}'>"
            f"Reading {os.path.basename(filepath)}</span>"
        )
        self.preview.set_pixmap(None)
        self.preview.set_placeholder("Reading ROM...")

    def show_metadata(self, filepath: str, result: Dict):
        if not result.get("success"):
            if result.get("is_encrypted"):
                self.title.setText("ROM is encrypted")
                self.fields.setText(
                    f"<span style='color:{THEME['brand_red']}'>"
                    "Decrypt with GodMode9 first.</span>"
                )
            else:
                self.title.setText("Cannot read ROM")
                self.fields.setText(
                    f"<span style='color:{THEME['brand_red']}'>"
                    f"{result.get('error_message', 'Unknown error')}</span>"
                )
            self.preview.set_placeholder("No preview")
            return

        name = get_game_name(result.get("title_id", ""),
                             result.get("product_code", ""))
        self.title.setText(name)
        try:
            size_mb = os.path.getsize(filepath) / (1024 * 1024)
        except OSError:
            size_mb = 0
        rows = [
            ("Title ID", result.get("title_id", "N/A")),
            ("Product", result.get("product_code", "N/A")),
            ("Files", f"{result.get('file_count', 0):,}"),
            ("Contents", str(result.get("content_count", 1))),
            ("ROM size", f"{size_mb:.0f} MB"),
            ("Chain", result.get("chain", "")),
        ]
        html = "<br>".join(
            f"<b style='color:{THEME['stage_text']}'>{k}:</b> {v}"
            for k, v in rows
        )
        self.fields.setText(html)
        self.preview.set_pixmap(None)
        self.preview.set_placeholder("Queue this game and press Start to extract")

    def show_extracting(self, game_name: str, current: int, total: int,
                        decoded_ok: int):
        self.title.setText(f"Extracting: {game_name}")
        pct = (current / total * 100) if total else 0
        self.fields.setText(
            f"<b style='color:{THEME['stage_text']}'>Progress:</b> "
            f"{current}/{total} files ({pct:.0f}%)<br>"
            f"<b style='color:{THEME['stage_text']}'>Textures decoded:</b> "
            f"{decoded_ok:,}"
        )
        self.preview.set_placeholder("Decoding textures...")

    def show_texture(self, game_name: str, png_path: str, rec: dict,
                    summary: dict):
        """Show one decoded texture as the stage sample, with real metadata."""
        self.title.setText(game_name)
        pix = QPixmap(png_path) if png_path else None
        self.preview.set_pixmap(pix)
        if pix is None or pix.isNull():
            self.preview.set_placeholder("No previewable texture")

        w = rec.get("width", 0)
        h = rec.get("height", 0)
        fmt = rec.get("detected_format", "?")
        azhash = rec.get("azahar_hash_cityhash64", "")
        decoded = summary.get("textures_decoded_ok", 0)
        unique = summary.get("textures_unique", decoded)
        # PICA200 textures are always Morton (Z-order) tiled in the ROM; the
        # decoder de-tiles them. There is no per-texture swizzle flag because
        # it is universal (see core/types.Texture).
        rows = [
            ("Sample", os.path.basename(png_path) if png_path else "(none)"),
            ("Dimensions", f"{w} x {h}" if w and h else "?"),
            ("Pica200 format", str(fmt)),
            ("Swizzle", "Morton (Z-order), de-tiled"),
            ("Azahar hash", azhash if azhash
             else "(normal mode; use Azahar mode for hashes)"),
            ("Decoded", f"{decoded:,} ok / {unique:,} unique"),
        ]
        self.fields.setText("<br>".join(
            f"<b style='color:{THEME['stage_text']}'>{k}:</b> {v}"
            for k, v in rows
        ))

    def apply_theme(self):
        self.setStyleSheet(f"background: {THEME['stage_bg']};")
        self.title.setStyleSheet(
            f"color: {THEME['stage_text']}; font-size: 17px; font-weight: bold;"
        )
        self.fields.setStyleSheet(
            f"color: {THEME['stage_dim']}; font-size: 12px;"
        )
        self.preview.update()


# ==============================================================
# Game tile (workbench grid)
# ==============================================================

class IconPlate(QWidget):
    """Glossy rounded icon plate: gradient base, the icon (or initials), and a
    soft top sheen, all painted so the gloss reads like a real 3DS tile."""

    RADIUS = 12

    def __init__(self, initials: str, parent=None):
        super().__init__(parent)
        self._initials = initials
        self._pix: Optional[QPixmap] = None
        self.setFixedHeight(82)

    def set_icon(self, pix: Optional[QPixmap]):
        self._pix = pix
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, self.RADIUS, self.RADIUS)
        p.setClipPath(path)

        # base gradient (white to pale)
        grad = QLinearGradient(0, r.top(), 0, r.bottom())
        grad.setColorAt(0.0, QColor("#ffffff"))
        grad.setColorAt(1.0, QColor(THEME["panel"]))
        p.fillPath(path, QBrush(grad))

        # icon or initials
        if self._pix is not None and not self._pix.isNull():
            side = int(min(r.width(), r.height())) - 14
            scaled = self._pix.scaled(
                side, side, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = r.left() + (r.width() - scaled.width()) / 2
            y = r.top() + (r.height() - scaled.height()) / 2
            p.drawPixmap(int(x), int(y), scaled)
        else:
            p.setPen(QColor(THEME["accent"]))
            p.setFont(QFont(FONT_FAMILY, 20, QFont.Weight.Bold))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, self._initials)

        # gloss: a soft highlight across the top half
        gloss_rect = QRectF(r.left(), r.top(), r.width(), r.height() * 0.52)
        gpath = QPainterPath()
        gpath.addRoundedRect(gloss_rect, self.RADIUS, self.RADIUS)
        gloss = QLinearGradient(0, gloss_rect.top(), 0, gloss_rect.bottom())
        gloss.setColorAt(0.0, QColor(255, 255, 255, 120))
        gloss.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillPath(gpath, QBrush(gloss))

        # crisp inner border
        p.setClipping(False)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(THEME["tile_border"]), 1))
        p.drawRoundedRect(r, self.RADIUS, self.RADIUS)
        p.end()


class GameTile(QFrame):
    clicked = Signal(str)

    TILE_W = 124
    TILE_H = 136

    def __init__(self, filepath: str, parent=None):
        super().__init__(parent)
        self.filepath = filepath
        self._selected = False
        self.setFixedSize(self.TILE_W, self.TILE_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 6)
        lay.setSpacing(4)

        self.plate = IconPlate(self._initials(filepath))
        lay.addWidget(self.plate)

        self.name_label = QLabel(os.path.basename(filepath))
        self.name_label.setWordWrap(True)
        self.name_label.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )
        self.name_label.setFixedHeight(34)
        lay.addWidget(self.name_label)

        # soft drop shadow under the tile (lifts on selection)
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(14)
        self._shadow.setColor(QColor(20, 50, 70, 70))
        self._shadow.setOffset(0, 3)
        self.setGraphicsEffect(self._shadow)
        self._pop = None

        self.setToolTip(filepath)
        self._apply_style()

    def set_icon(self, pixmap: QPixmap):
        """Swap the placeholder plate for the real HOME Menu icon."""
        if pixmap is None or pixmap.isNull():
            return
        self.plate.set_icon(pixmap)

    @staticmethod
    def _initials(filepath: str) -> str:
        base = os.path.splitext(os.path.basename(filepath))[0]
        words = [w for w in base.replace("_", " ").split() if w[:1].isalnum()]
        if not words:
            return "3DS"
        return "".join(w[0] for w in words[:2]).upper()

    def set_selected(self, on: bool):
        was = self._selected
        self._selected = on
        self._apply_style()
        if on and not was:
            self._animate_pop()

    def _animate_pop(self):
        # a quick "lift": the shadow blurs and floats up, then settles. Reads as
        # a pop without fighting the grid layout.
        anim = QPropertyAnimation(self._shadow, b"blurRadius", self)
        anim.setDuration(240)
        anim.setStartValue(14)
        anim.setKeyValueAt(0.5, 30)
        anim.setEndValue(22)
        anim.setEasingCurve(QEasingCurve.Type.OutBack)
        anim.start()
        self._pop = anim  # keep a reference so it is not GC'd

    def _apply_style(self):
        if self._selected:
            border = THEME["tile_sel"]
            width = 3
            self._shadow.setColor(QColor(0, 183, 235, 150))  # accent glow
            self._shadow.setOffset(0, 5)
        else:
            border = THEME["tile_border"]
            width = 1
            self._shadow.setColor(QColor(20, 50, 70, 70))
            self._shadow.setOffset(0, 3)
            self._shadow.setBlurRadius(14)
        self.setStyleSheet(
            f"GameTile {{ background: {THEME['tile_bg']};"
            f" border: {width}px solid {border}; border-radius: 16px; }}"
        )
        self.name_label.setStyleSheet(
            f"color: {THEME['text']}; font-size: 9px; border: none;"
        )

    def mousePressEvent(self, event):
        self.clicked.emit(self.filepath)
        super().mousePressEvent(event)


# ==============================================================
# Settings dialog (extract options, previously config.json-only)
# ==============================================================

class SettingsDialog(QDialog):
    """Edit the extract options that run_extraction reads from config.

    Until this existed, switching to Azahar output mode (the entire point of
    the tool for texture-pack work) required hand-editing config.json. The
    dialog edits a copy and only writes back on Save.
    """

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Extraction Settings")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setStyleSheet(
            f"QDialog {{ background: {THEME['bg_bottom']}; }}"
            f" QLabel {{ color: {THEME['text']}; font-size: 12px; }}"
            f" QCheckBox {{ color: {THEME['text']}; font-size: 12px;"
            f" spacing: 8px; }}"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        # Output base folder
        lay.addWidget(QLabel("Output base folder (a per-game subfolder is "
                             "created inside it):"))
        out_row = QHBoxLayout()
        self.out_edit = QLineEdit(cfg.get("last_output_path", "")
                                  or os.path.abspath("output"))
        self.out_edit.setStyleSheet(
            f"QLineEdit {{ background: {THEME['tile_bg']}; color: {THEME['text']};"
            f" border: 1px solid {THEME['tile_border']}; border-radius: 8px;"
            f" padding: 6px 10px; font-size: 11px; }}"
        )
        out_row.addWidget(self.out_edit, 1)
        btn_browse = QPushButton("Browse")
        btn_browse.setStyleSheet(self._btn_style())
        btn_browse.clicked.connect(self._browse)
        out_row.addWidget(btn_browse)
        lay.addLayout(out_row)

        # Output mode
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Output mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Normal (browsable folders)", "normal")
        self.mode_combo.addItem("Azahar (drop-in texture pack names)", "azahar")
        self.mode_combo.setCurrentIndex(
            1 if cfg.get("output_mode") == "azahar" else 0)
        self.mode_combo.setStyleSheet(
            f"QComboBox {{ background: {THEME['tile_bg']}; color: {THEME['text']};"
            f" border: 1px solid {THEME['tile_border']}; border-radius: 8px;"
            f" padding: 5px 10px; font-size: 11px; }}"
            f" QComboBox QAbstractItemView {{ background: {THEME['tile_bg']};"
            f" color: {THEME['text']};"
            f" selection-background-color: {THEME['accent']};"
            f" selection-color: #ffffff; }}"
        )
        mode_row.addWidget(self.mode_combo, 1)
        lay.addLayout(mode_row)

        hint = QLabel("Azahar mode names files tex1_<W>x<H>_<CityHash64>_"
                      "<code>_mip0.png so the folder drops straight into "
                      "load/textures/<title_id>/.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {THEME['text_dim']}; font-size: 10px;")
        lay.addWidget(hint)

        # Toggles
        self.chk_dedup = QCheckBox("Dedup (skip writing duplicate textures)")
        self.chk_dedup.setChecked(bool(cfg.get("dedup", False)))
        self.chk_scan_all = QCheckBox("Scan all files (ignore extension filter; slower)")
        self.chk_scan_all.setChecked(bool(cfg.get("scan_all_files", False)))
        self.chk_dump_raw = QCheckBox("Dump raw texture bytes (raw/*.bin beside PNGs)")
        self.chk_dump_raw.setChecked(bool(cfg.get("dump_raw", False)))
        self.chk_new_folder = QCheckBox("New folder per run (normal mode only; "
                                        "Azahar packs keep one stable folder)")
        self.chk_new_folder.setChecked(bool(cfg.get("new_folder_per_run", True)))
        self.chk_verbose = QCheckBox("Verbose logging")
        self.chk_verbose.setChecked(bool(cfg.get("verbose_logging", False)))
        for chk in (self.chk_dedup, self.chk_scan_all, self.chk_dump_raw,
                    self.chk_new_folder, self.chk_verbose):
            lay.addWidget(chk)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setStyleSheet(self._btn_style())
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        btn_save = QPushButton("Save")
        btn_save.setStyleSheet(self._btn_style(primary=True))
        btn_save.clicked.connect(self._save)
        btn_row.addWidget(btn_save)
        lay.addLayout(btn_row)

    def _btn_style(self, primary: bool = False) -> str:
        if primary:
            bg, fg, hover = THEME["accent"], "#ffffff", _lighten(THEME["accent"])
        else:
            bg, fg, hover = THEME["tile_bg"], THEME["text"], THEME["panel"]
        return (
            f"QPushButton {{ background: {bg}; color: {fg}; font-size: 12px;"
            f" font-weight: bold; padding: 6px 16px; border-radius: 14px;"
            f" border: 1px solid {THEME['tile_border']}; }}"
            f" QPushButton:hover {{ background: {hover}; }}"
        )

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, "Output base folder",
                                                self.out_edit.text() or "")
        if path:
            self.out_edit.setText(path)

    def _save(self):
        self.cfg["last_output_path"] = self.out_edit.text().strip()
        self.cfg["output_mode"] = self.mode_combo.currentData()
        self.cfg["dedup"] = self.chk_dedup.isChecked()
        self.cfg["scan_all_files"] = self.chk_scan_all.isChecked()
        self.cfg["dump_raw"] = self.chk_dump_raw.isChecked()
        self.cfg["new_folder_per_run"] = self.chk_new_folder.isChecked()
        self.cfg["verbose_logging"] = self.chk_verbose.isChecked()
        save_config(self.cfg)
        self.accept()


# ==============================================================
# Activity shelf (the heartbeat): lifetime + session stats + theme picker
# ==============================================================

class ActivityShelf(QWidget):
    """Makes the system feel inhabited: lifetime textures and games processed
    (persisted across launches), plus 'this session' counts framed lightly like
    Play Coins. Also hosts the live theme picker."""

    theme_changed = Signal(str)
    settings_requested = Signal()

    def __init__(self, current_theme: str = "sky", parent=None):
        super().__init__(parent)
        self._cards: Dict[str, QFrame] = {}
        self._values: Dict[str, QLabel] = {}
        self._labels: Dict[str, QLabel] = {}

        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(10)

        self._brand = QLabel("Texture Forge")
        lay.addWidget(self._brand)
        lay.addStretch()

        lay.addWidget(self._make_card("lifetime", "Lifetime textures", "0"))
        lay.addWidget(self._make_card("games", "Games processed", "0"))
        lay.addWidget(self._make_card("session", "This session", "0"))

        self.theme_combo = QComboBox()
        for key in ("sky", "dark", "coral"):
            self.theme_combo.addItem(THEMES[key]["name"], key)
        idx = max(0, self.theme_combo.findData(current_theme))
        self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.currentIndexChanged.connect(
            lambda _i: self.theme_changed.emit(self.theme_combo.currentData())
        )
        lay.addWidget(self.theme_combo)

        self.btn_settings = QPushButton("Settings")
        self.btn_settings.clicked.connect(self.settings_requested.emit)
        lay.addWidget(self.btn_settings)

        self.apply_theme()

    def _make_card(self, key: str, label: str, value: str) -> QFrame:
        card = QFrame()
        v = QVBoxLayout(card)
        v.setContentsMargins(14, 6, 14, 6)
        v.setSpacing(0)
        val = QLabel(value)
        val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lab = QLabel(label)
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(val)
        v.addWidget(lab)
        self._cards[key] = card
        self._values[key] = val
        self._labels[key] = lab
        return card

    def set_stats(self, lifetime_tex: int, games: int, session_tex: int):
        self._values["lifetime"].setText(f"{lifetime_tex:,}")
        self._values["games"].setText(f"{games:,}")
        self._values["session"].setText(f"{session_tex:,}")

    def apply_theme(self):
        self._brand.setStyleSheet(
            f"color: {THEME['text']}; font-size: 14px; font-weight: bold;"
        )
        for key, card in self._cards.items():
            card.setStyleSheet(
                f"QFrame {{ background: {THEME['tile_bg']};"
                f" border: 1px solid {THEME['tile_border']};"
                f" border-radius: 12px; }}"
            )
            self._values[key].setStyleSheet(
                f"color: {THEME['accent']}; font-size: 17px;"
                f" font-weight: bold; border: none;"
            )
            self._labels[key].setStyleSheet(
                f"color: {THEME['text_dim']}; font-size: 10px; border: none;"
            )
        self.theme_combo.setStyleSheet(
            f"QComboBox {{ background: {THEME['tile_bg']}; color: {THEME['text']};"
            f" border: 1px solid {THEME['tile_border']}; border-radius: 10px;"
            f" padding: 5px 12px; font-size: 11px; }}"
            f" QComboBox::drop-down {{ border: none; width: 18px; }}"
            f" QComboBox QAbstractItemView {{ background: {THEME['tile_bg']};"
            f" color: {THEME['text']};"
            f" selection-background-color: {THEME['accent']};"
            f" selection-color: #ffffff; outline: none; }}"
        )
        self.btn_settings.setStyleSheet(
            f"QPushButton {{ background: {THEME['tile_bg']}; color: {THEME['text']};"
            f" font-size: 11px; font-weight: bold; padding: 5px 14px;"
            f" border-radius: 10px; border: 1px solid {THEME['tile_border']}; }}"
            f" QPushButton:hover {{ background: {THEME['panel']}; }}"
        )


# ==============================================================
# Workbench (bottom screen): path bar, game grid, controls, queue
# ==============================================================

class Workbench(QWidget):
    tile_selected = Signal(str)
    queue_requested = Signal(str)
    start_requested = Signal()
    stop_requested = Signal()
    jobs_changed = Signal()

    GRID_COLS = 5

    STATE_BADGE = {
        Job.QUEUED:   ("•", "#5C7682"),   # bullet, dim
        Job.RUNNING:  ("▶", "#00B7EB"),   # play, accent
        Job.COMPLETE: ("✓", "#2E9E54"),   # check, green
        Job.FAILED:   ("✗", "#E60012"),   # cross, red
        Job.CANCELED: ("⊘", "#9A7B00"),   # slashed-o, amber
    }

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._tiles: List[GameTile] = []
        self._selected_tile: Optional[GameTile] = None
        self.jobs: List[Job] = []
        self.setStyleSheet(
            f"Workbench {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 {THEME['bg_top']}, stop:1 {THEME['bg_bottom']}); }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 12)
        root.setSpacing(10)

        # activity shelf (heartbeat stats + theme picker)
        self.shelf = ActivityShelf(cfg.get("theme", "sky"))
        root.addWidget(self.shelf)

        # path bar
        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        self.path_input = QLineEdit("; ".join(cfg.get("library_paths", [])))
        self.path_input.setStyleSheet(
            f"QLineEdit {{ background: #ffffff; color: {THEME['text']};"
            f" border: 1px solid {THEME['tile_border']}; border-radius: 8px;"
            f" padding: 6px 10px; font-size: 11px; }}"
        )
        self.path_input.setToolTip(
            "Library folders, separated by ';'. Edit and press Rescan."
        )
        path_row.addWidget(self.path_input, 1)

        self.btn_add = QPushButton("Add folder")
        self.btn_add.setStyleSheet(self._btn_style())
        self.btn_add.clicked.connect(self._add_folder)
        path_row.addWidget(self.btn_add)

        self.btn_rescan = QPushButton("Rescan")
        self.btn_rescan.setStyleSheet(self._btn_style(primary=True))
        self.btn_rescan.clicked.connect(self._rescan_clicked)
        path_row.addWidget(self.btn_rescan)
        root.addLayout(path_row)

        # filter + batch row
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText(
            "Filter games (type part of a filename)...")
        self.filter_input.setClearButtonEnabled(True)
        self.filter_input.setStyleSheet(self._input_style())
        self.filter_input.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self.filter_input, 1)

        self.btn_queue_all = QPushButton("Queue All")
        self.btn_queue_all.setStyleSheet(self._btn_style())
        self.btn_queue_all.setToolTip(
            "Queue every visible game (respects the filter).")
        self.btn_queue_all.clicked.connect(self._queue_all_visible)
        filter_row.addWidget(self.btn_queue_all)
        root.addLayout(filter_row)

        # grid + queue side by side
        mid = QHBoxLayout()
        mid.setSpacing(12)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.grid_host = QWidget()
        self.grid_host.setStyleSheet("background: transparent;")
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(2, 2, 2, 2)
        self.grid.setSpacing(10)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scroll.setWidget(self.grid_host)
        mid.addWidget(self.scroll, 3)

        # queue column
        queue_col = QVBoxLayout()
        queue_col.setSpacing(6)
        self.queue_label = QLabel("Queue")
        self.queue_label.setStyleSheet(
            f"color: {THEME['text']}; font-size: 13px; font-weight: bold;"
        )
        queue_col.addWidget(self.queue_label)
        self.queue_list = QListWidget()
        self.queue_list.setFixedWidth(220)
        self.queue_list.setStyleSheet(
            f"QListWidget {{ background: #ffffff; color: {THEME['text']};"
            f" border: 1px solid {THEME['tile_border']}; border-radius: 10px;"
            f" font-size: 11px; }}"
            f" QListWidget::item {{ padding: 6px 8px; }}"
        )
        self.queue_list.setToolTip("Double-click a completed job to open its "
                                   "output folder. Right-click to remove an "
                                   "item.")
        self.queue_list.itemDoubleClicked.connect(self._open_job_output)
        self.queue_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.queue_list.customContextMenuRequested.connect(
            self._queue_context_menu)
        queue_col.addWidget(self.queue_list, 1)

        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(6)
        self.btn_start = QPushButton("Start")
        self.btn_start.setStyleSheet(self._btn_style(primary=True))
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self.start_requested.emit)
        ctrl_row.addWidget(self.btn_start)
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setStyleSheet(self._btn_style())
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_requested.emit)
        ctrl_row.addWidget(self.btn_stop)
        queue_col.addLayout(ctrl_row)

        self.btn_clear = QPushButton("Clear Queue")
        self.btn_clear.setStyleSheet(self._btn_style())
        self.btn_clear.clicked.connect(self._clear_queue)
        queue_col.addWidget(self.btn_clear)

        mid.addLayout(queue_col)
        root.addLayout(mid, 1)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {THEME['text_dim']}; font-size: 11px;")
        root.addWidget(self.status)

    # ---- styling helpers ----

    def _btn_style(self, primary: bool = False) -> str:
        if primary:
            bg, fg, hover = THEME["accent"], "#ffffff", _lighten(THEME["accent"])
        else:
            bg, fg, hover = THEME["tile_bg"], THEME["text"], THEME["panel"]
        return (
            f"QPushButton {{ background: {bg}; color: {fg}; font-size: 12px;"
            f" font-weight: bold; padding: 7px 16px; border-radius: 16px;"
            f" border: 1px solid {THEME['tile_border']}; }}"
            f" QPushButton:hover {{ background: {hover}; }}"
            f" QPushButton:disabled {{ background: #d7e7ef; color: #9bb3bf;"
            f" border-color: #cfe1ea; }}"
        )

    def _input_style(self) -> str:
        return (
            f"QLineEdit {{ background: {THEME['tile_bg']}; color: {THEME['text']};"
            f" border: 1px solid {THEME['tile_border']}; border-radius: 8px;"
            f" padding: 6px 10px; font-size: 11px; }}"
        )

    def _list_style(self) -> str:
        return (
            f"QListWidget {{ background: {THEME['tile_bg']}; color: {THEME['text']};"
            f" border: 1px solid {THEME['tile_border']}; border-radius: 10px;"
            f" font-size: 11px; }}"
            f" QListWidget::item {{ padding: 6px 8px; }}"
        )

    def apply_theme(self):
        self.setStyleSheet(
            f"Workbench {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 {THEME['bg_top']}, stop:1 {THEME['bg_bottom']}); }}"
        )
        self.shelf.apply_theme()
        self.path_input.setStyleSheet(self._input_style())
        self.queue_list.setStyleSheet(self._list_style())
        self.queue_label.setStyleSheet(
            f"color: {THEME['text']}; font-size: 13px; font-weight: bold;"
        )
        self.status.setStyleSheet(
            f"color: {THEME['text_dim']}; font-size: 11px;"
        )
        self.btn_add.setStyleSheet(self._btn_style())
        self.btn_rescan.setStyleSheet(self._btn_style(primary=True))
        self.btn_start.setStyleSheet(self._btn_style(primary=True))
        self.btn_stop.setStyleSheet(self._btn_style())
        self.btn_clear.setStyleSheet(self._btn_style())
        self.filter_input.setStyleSheet(self._input_style())
        self.btn_queue_all.setStyleSheet(self._btn_style())
        for tile in self._tiles:
            tile._apply_style()
            tile.plate.update()

    # ---- grid population ----

    def populate(self, rom_paths: List[str], truncated: bool):
        # clear existing tiles
        for t in self._tiles:
            t.setParent(None)
            t.deleteLater()
        self._tiles = []
        self._selected_tile = None

        if not rom_paths:
            self.status.setText(
                "No ROMs found. Add a folder of decrypted .3ds/.cia files, "
                "then press Rescan."
            )
            return

        for i, path in enumerate(rom_paths):
            tile = GameTile(path)
            tile.clicked.connect(self._on_tile_clicked)
            r, c = divmod(i, self.GRID_COLS)
            self.grid.addWidget(tile, r, c)
            self._tiles.append(tile)

        msg = f"{len(rom_paths)} ROMs"
        if truncated:
            msg += f" (showing first {DISCOVERY_CAP}; narrow the library paths to see the rest)"
        self.status.setText(msg)
        # A rescan must not silently clear an active filter.
        if self.filter_input.text().strip():
            self._apply_filter()

    def _on_tile_clicked(self, path: str):
        for t in self._tiles:
            t.set_selected(t.filepath == path)
            if t.filepath == path:
                self._selected_tile = t
        self.tile_selected.emit(path)
        # "queues its textures": add to the queue on selection
        self.queue_requested.emit(path)

    # ---- filter + batch queueing ----

    def _apply_filter(self, _text: str = ""):
        """Show only tiles whose filename contains the filter text, and
        re-pack the grid so visible tiles fill rows without gaps."""
        needle = self.filter_input.text().strip().lower()
        visible = []
        for tile in self._tiles:
            hit = (not needle) or (needle in
                                   os.path.basename(tile.filepath).lower())
            # setHidden + isHidden track the tile's OWN flag, which stays
            # correct even while the window itself is not yet shown
            # (isVisible() is false for every child of an unshown window).
            tile.setHidden(not hit)
            if hit:
                visible.append(tile)
        # re-grid the visible tiles contiguously
        for tile in self._tiles:
            self.grid.removeWidget(tile)
        for i, tile in enumerate(visible):
            r, c = divmod(i, self.GRID_COLS)
            self.grid.addWidget(tile, r, c)
        if needle:
            self.status.setText(
                f"{len(visible)} of {len(self._tiles)} ROMs match "
                f"'{self.filter_input.text().strip()}'")
        elif self._tiles:
            self.status.setText(f"{len(self._tiles)} ROMs")

    def _queue_all_visible(self):
        added = 0
        for tile in self._tiles:
            if not tile.isHidden():
                before = len(self.queued_jobs())
                self.add_to_queue(tile.filepath)
                if len(self.queued_jobs()) > before:
                    added += 1
        if added:
            self.status.setText(f"Queued {added} game(s). Press Start.")
        elif self._tiles:
            self.status.setText("Everything visible is already queued "
                                "or running.")

    def add_to_queue(self, path: str):
        existing = self.job_for(path)
        if existing is not None:
            # Clicking a finished (or failed/canceled) game re-queues it for
            # another run; a QUEUED or RUNNING job is left alone. Previously a
            # terminal job blocked re-running until Clear Queue was pressed.
            if existing.state in Job.TERMINAL:
                existing.state = Job.QUEUED
                existing.summary = {}
                existing.error = ""
                existing.decoded_ok = 0
                existing.progress_text = ""
                self._render_queue()
                self.jobs_changed.emit()
            return
        self.jobs.append(Job(path))
        self._render_queue()
        self.jobs_changed.emit()

    def job_for(self, path: str) -> Optional[Job]:
        for j in self.jobs:
            if j.path == path:
                return j
        return None

    def queued_jobs(self) -> List[Job]:
        return [j for j in self.jobs if j.state == Job.QUEUED]

    def set_job_state(self, path: str, state: str):
        j = self.job_for(path)
        if j:
            j.state = state
            self._render_queue()
            self.jobs_changed.emit()

    def _render_queue(self):
        self.queue_list.clear()
        for j in self.jobs:
            badge, color = self.STATE_BADGE.get(j.state, ("•", THEME["text_dim"]))
            label = f"{badge}  {os.path.basename(j.path)}"
            if j.state == Job.RUNNING and j.progress_text:
                label += f"   {j.progress_text}"
            elif j.state == Job.COMPLETE and j.decoded_ok:
                label += f"   {j.decoded_ok:,} tex"
            item = QListWidgetItem(label)
            item.setToolTip(j.path)
            item.setForeground(QColor(color))
            self.queue_list.addItem(item)

    def update_controls(self, running: bool):
        self.btn_start.setEnabled(bool(self.queued_jobs()) and not running)
        self.btn_stop.setEnabled(running)

    def _clear_queue(self):
        # Remove everything not currently RUNNING. QUEUED jobs are exactly
        # what someone pressing "Clear Queue" wants gone; the old
        # terminal-only rule made the button a no-op on a fresh queue.
        self.jobs = [j for j in self.jobs if j.state == Job.RUNNING]
        self._render_queue()
        self.jobs_changed.emit()

    def _queue_context_menu(self, pos):
        """Right-click on a queue item: remove it, or open its output."""
        item = self.queue_list.itemAt(pos)
        if item is None:
            return
        row = self.queue_list.row(item)
        if not (0 <= row < len(self.jobs)):
            return
        job = self.jobs[row]
        menu = QMenu(self)
        act_remove = None
        if job.state != Job.RUNNING:
            act_remove = menu.addAction("Remove from queue")
        act_open = None
        if job.output_dir and os.path.isdir(job.output_dir):
            act_open = menu.addAction("Open output folder")
        if menu.isEmpty():
            return
        chosen = menu.exec(self.queue_list.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is act_remove:
            self.jobs.remove(job)
            self._render_queue()
            self.jobs_changed.emit()
        elif chosen is act_open:
            self._open_job_output(item)

    def _open_job_output(self, item: QListWidgetItem):
        """Open a finished job's output folder in the system file manager."""
        row = self.queue_list.row(item)
        if not (0 <= row < len(self.jobs)):
            return
        job = self.jobs[row]
        if not job.output_dir or not os.path.isdir(job.output_dir):
            return
        try:
            if sys.platform == "win32":
                os.startfile(job.output_dir)  # noqa: S606 (user-initiated)
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", job.output_dir])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", job.output_dir])
        except OSError:
            pass

    # ---- path bar actions ----

    def current_paths(self) -> List[str]:
        return [p.strip() for p in self.path_input.text().split(";") if p.strip()]

    def _add_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Add ROM folder")
        if path:
            paths = self.current_paths()
            if path not in paths:
                paths.append(path)
            self.path_input.setText("; ".join(paths))
            self._rescan_clicked()

    def _rescan_clicked(self):
        paths = self.current_paths()
        self.cfg["library_paths"] = paths
        save_config(self.cfg)
        self.status.setText("Scanning library...")
        self.rescan(paths)

    # set by the window so the workbench can kick off discovery
    rescan_callback = None

    def rescan(self, paths: List[str]):
        if callable(self.rescan_callback):
            self.rescan_callback(paths)


# ==============================================================
# Main window: status strip + stage + hinge seam + workbench
# ==============================================================

class HomeMenuWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        # Scan workers are never terminated (QThread.terminate can corrupt
        # interpreter state mid-parse). Instead every launched worker is kept
        # alive in this list until its own finished signal fires, and
        # _on_scan_done drops results for anything that is no longer the
        # selected tile. Rapid tile-clicking therefore just races harmlessly.
        self._scan_workers: List[ScanWorker] = []
        self._selected_path: str = ""
        self._discover_worker: Optional[DiscoverWorker] = None
        self._pending_paths: List[str] = []
        self._launched_paths: List[str] = []
        self._scan_cache: Dict[str, dict] = {}
        self._extract_worker: Optional[ExtractWorker] = None
        self._current_job: Optional[Job] = None
        self._queue_running = False
        self._stop_requested = False
        self._milestone_step = 5000   # orange flash every N decoded textures
        self._milestone_bucket = 0
        self._icon_cache: Dict[str, QPixmap] = {}
        self._icon_loader: Optional[IconLoader] = None
        # Banner art for the stage: decoded on demand for the selected title,
        # cached by path. None is cached too, so a title with no usable
        # banner is not re-read on every click.
        self._banner_cache: Dict[str, Optional[QPixmap]] = {}
        self._banner_workers: List[BannerWorker] = []
        self._session_textures = 0
        self._session_games = 0

        self._seed_lifetime_if_needed()
        set_theme(self.cfg.get("theme", "sky"))

        self.setWindowTitle("3DS Texture Forge")
        self.setMinimumSize(900, 680)
        self.resize(self.cfg.get("window_width", 1040),
                    self.cfg.get("window_height", 760))

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.status_strip = StatusStrip()
        root.addWidget(self.status_strip)

        # stage / workbench split with a hinge seam
        self.split = QSplitter(Qt.Orientation.Vertical)
        self.split.setHandleWidth(6)
        self.split.setStyleSheet(
            f"QSplitter::handle {{ background: {THEME['seam']}; }}"
        )
        self.stage = Stage()
        self.workbench = Workbench(self.cfg)
        self.workbench.rescan_callback = self._start_discovery
        self.split.addWidget(self.stage)
        self.split.addWidget(self.workbench)
        self.split.setStretchFactor(0, 2)
        self.split.setStretchFactor(1, 3)
        self.split.setSizes([300, 420])
        root.addWidget(self.split, 1)

        self.workbench.tile_selected.connect(self._on_tile_selected)
        self.workbench.queue_requested.connect(self.workbench.add_to_queue)
        self.workbench.start_requested.connect(self._start_queue)
        self.workbench.stop_requested.connect(self._stop_queue)
        self.workbench.jobs_changed.connect(
            lambda: self.workbench.update_controls(self._queue_running)
        )
        self.workbench.shelf.theme_changed.connect(self._on_theme_changed)
        self.workbench.shelf.settings_requested.connect(self._open_settings)
        self._refresh_shelf()

        # Apply the saved theme once so startup matches it (construction-time
        # styles are otherwise only refreshed on a theme change).
        self.apply_theme()

        # Drag a ROM (or a handful) anywhere onto the window to queue it, even
        # if it lives outside the library paths.
        self.setAcceptDrops(True)

        # initial discovery from configured paths
        self._start_discovery(self.cfg.get("library_paths", []))

    # ---- drag and drop ----

    def dragEnterEvent(self, event):
        if any(u.isLocalFile()
               and u.toLocalFile().lower().endswith(ROM_EXTS)
               for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls()
                 if u.isLocalFile()
                 and u.toLocalFile().lower().endswith(ROM_EXTS)]
        self._ingest_dropped_paths(paths)
        event.acceptProposedAction()

    def _ingest_dropped_paths(self, paths: List[str]):
        """Queue dropped ROM files and stage-scan the first one.

        Queueing works by path alone, so a dropped ROM outside the library
        folders still extracts fine; it simply has no grid tile.
        """
        valid = [p for p in paths if os.path.isfile(p)]
        if not valid:
            return
        for p in valid:
            self.workbench.add_to_queue(p)
        self._on_tile_selected(valid[0])
        self.workbench.status.setText(
            f"Queued {len(valid)} dropped ROM(s). Press Start.")

    # ---- discovery ----

    def _start_discovery(self, paths: List[str]):
        # Record the latest request. If a walk is already in flight, it will be
        # relaunched with these paths when it finishes, so rapid Rescans are
        # never silently dropped.
        self._pending_paths = list(paths)
        if self._discover_worker and self._discover_worker.isRunning():
            return
        self._launch_discovery()

    def _launch_discovery(self):
        self._launched_paths = list(self._pending_paths)
        self._discover_worker = DiscoverWorker(self._launched_paths)
        self._discover_worker.done.connect(self._on_discovery_done)
        self._discover_worker.start()

    def _on_discovery_done(self, roms: list, truncated: bool):
        self.workbench.populate(roms, truncated)
        self._apply_cached_icons()
        self._start_icon_loading(roms)
        if self._pending_paths != self._launched_paths:
            self._launch_discovery()

    # ---- HOME Menu icons (read-only accessor, cached in memory) ----

    def _apply_cached_icons(self):
        for tile in self.workbench._tiles:
            pix = self._icon_cache.get(tile.filepath)
            if pix is not None:
                tile.set_icon(pix)

    def _start_icon_loading(self, paths: list):
        if self._icon_loader and self._icon_loader.isRunning():
            self._icon_loader.stop()  # let it exit; a fresh loader takes over
        self._icon_loader = IconLoader(paths, set(self._icon_cache.keys()))
        self._icon_loader.icon_ready.connect(self._on_icon_ready)
        self._icon_loader.start()

    def _on_icon_ready(self, path: str, rgba: object):
        pix = rgba_to_pixmap(rgba)
        if pix is None:
            return
        self._icon_cache[path] = pix
        for tile in self.workbench._tiles:
            if tile.filepath == path:
                tile.set_icon(pix)
                break

    # ---- lifetime stats (the heartbeat) ----

    SEED_LIFETIME_TEXTURES = 1_000_000  # placeholder baseline: the project's
    SEED_LIFETIME_GAMES = 35            # claimed ~1M textures across 35+ games

    def _seed_lifetime_if_needed(self):
        # Seed the lifetime counters once so the Activity Log is not empty before
        # real run history accrues. THIS IS A PLACEHOLDER; real successful runs
        # add on top of this baseline. Cleared/recounted only if a user resets.
        if not self.cfg.get("lifetime_seeded"):
            self.cfg["lifetime_textures"] = self.SEED_LIFETIME_TEXTURES
            self.cfg["lifetime_games"] = self.SEED_LIFETIME_GAMES
            self.cfg["lifetime_seeded"] = True
            save_config(self.cfg)

    def _refresh_shelf(self):
        self.workbench.shelf.set_stats(
            self.cfg.get("lifetime_textures", 0),
            self.cfg.get("lifetime_games", 0),
            self._session_textures,
        )

    def _record_run(self, decoded: int):
        self._session_textures += decoded
        self._session_games += 1
        self.cfg["lifetime_textures"] = self.cfg.get("lifetime_textures", 0) + decoded
        self.cfg["lifetime_games"] = self.cfg.get("lifetime_games", 0) + 1
        save_config(self.cfg)
        self._refresh_shelf()

    # ---- theme ----

    def _on_theme_changed(self, name: str):
        set_theme(name)
        self.cfg["theme"] = name
        save_config(self.cfg)
        self.apply_theme()

    # ---- settings ----

    def _open_settings(self):
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec():
            mode = self.cfg.get("output_mode", "normal")
            self.workbench.status.setText(
                f"Settings saved (output mode: {mode}).")

    def apply_theme(self):
        self.split.setStyleSheet(
            f"QSplitter::handle {{ background: {THEME['seam']}; }}"
        )
        self.status_strip.apply_theme()
        self.stage.apply_theme()
        self.workbench.apply_theme()

    # ---- selection -> scan -> stage ----

    def _on_tile_selected(self, path: str):
        self._selected_path = path
        # Do not interrupt the stage or LED while an extraction is running.
        if not self._queue_running:
            self.stage.show_loading(path)
        worker = ScanWorker(path)
        worker.done.connect(self._on_scan_done)
        worker.finished.connect(lambda w=worker: self._reap_scan_worker(w))
        self._scan_workers.append(worker)
        worker.start()

    def _reap_scan_worker(self, worker: "ScanWorker"):
        if worker in self._scan_workers:
            self._scan_workers.remove(worker)
        worker.deleteLater()

    def _on_scan_done(self, filepath: str, result: dict):
        self._scan_cache[filepath] = result
        if filepath != self._selected_path:
            return  # stale: the user has clicked another tile since
        # Do not stomp the stage if an extraction is mid-flight.
        if not self._queue_running:
            self.stage.show_metadata(filepath, result)
            if result.get("success"):
                self._stage_banner_for(filepath)
        if not result.get("success") and not self._queue_running:
            self.status_strip.led.set_error()
        elif not self._queue_running:
            self.status_strip.led.set_idle()

    # ---- stage banner (HOME Menu banner art on the top screen) ----

    def _stage_banner_for(self, path: str):
        """Show the title's banner on the stage, with the crisp-scaled SMDH
        icon as instant fallback while (or if) the banner decode runs."""
        if path in self._banner_cache:
            pix = self._banner_cache[path]
            if pix is not None:
                self.stage.preview.set_pixmap(pix)
            else:
                self._stage_icon_fallback(path)
            return
        # Instant feedback from the already-cached grid icon, banner swaps in
        # when the worker lands.
        self._stage_icon_fallback(path)
        if any(w.filepath == path and w.isRunning()
               for w in self._banner_workers):
            return
        worker = BannerWorker(path)
        worker.banner_ready.connect(self._on_banner_ready)
        worker.finished.connect(lambda w=worker: self._reap_banner_worker(w))
        self._banner_workers.append(worker)
        worker.start()

    def _stage_icon_fallback(self, path: str):
        icon = self._icon_cache.get(path)
        if icon is None or icon.isNull():
            return
        # 48x48 source: pre-scale 4x nearest-neighbour so the stage shows
        # crisp pixel art instead of a smooth-scaled blur.
        crisp = icon.scaled(icon.width() * 4, icon.height() * 4,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.FastTransformation)
        self.stage.preview.set_pixmap(crisp)

    def _reap_banner_worker(self, worker: "BannerWorker"):
        if worker in self._banner_workers:
            self._banner_workers.remove(worker)
        worker.deleteLater()

    def _on_banner_ready(self, path: str, rgba: object):
        pix = rgba_to_pixmap(rgba)
        self._banner_cache[path] = pix  # None cached too: no re-reads
        if pix is None:
            return
        if path == self._selected_path and not self._queue_running:
            self.stage.preview.set_pixmap(pix)

    # ---- output dir + options ----

    def _game_name_for(self, path: str) -> str:
        res = self._scan_cache.get(path)
        if res and res.get("success"):
            return get_game_name(res.get("title_id", ""),
                                res.get("product_code", ""))
        return os.path.splitext(os.path.basename(path))[0]

    # Windows refuses these as file/folder names regardless of extension.
    _WIN_RESERVED = frozenset(
        {"CON", "PRN", "AUX", "NUL"}
        | {f"COM{i}" for i in range(1, 10)}
        | {f"LPT{i}" for i in range(1, 10)}
    )

    def _output_dir_for(self, path: str) -> str:
        base = self.cfg.get("last_output_path", "") or os.path.abspath("output")
        name = self._game_name_for(path)
        safe = re.sub(r'[<>:"/\\|?*]', "", name)
        # Windows also rejects trailing dots/spaces and reserved device names
        # (CON, NUL, COM1...). "Output" suffix keeps those usable.
        safe = safe.strip().rstrip(". ")
        if not safe or safe.upper() in self._WIN_RESERVED:
            safe = (safe + " Output").strip() or "output"
        out = os.path.join(base, safe)
        # new_folder_per_run (config default True, previously ignored by this
        # UI): timestamp normal-mode runs so a re-run cannot overwrite the
        # previous manifest and PNGs. Azahar mode intentionally keeps ONE
        # stable folder; its hash filenames are idempotent and the folder is
        # the drop-in pack, so fragmenting it per run would break the
        # workflow.
        if (self.cfg.get("new_folder_per_run", True)
                and self.cfg.get("output_mode") != "azahar"):
            from datetime import datetime
            out = os.path.join(out, datetime.now().strftime("run_%Y%m%d-%H%M%S"))
        return out

    def _extract_options(self) -> dict:
        return {
            "output_mode": "azahar"
            if self.cfg.get("output_mode") == "azahar" else "normal",
            "scan_all": bool(self.cfg.get("scan_all_files", False)),
            "dedup": bool(self.cfg.get("dedup", False)),
            "dump_raw": bool(self.cfg.get("dump_raw", False)),
            "verbose": bool(self.cfg.get("verbose_logging", False)),
        }

    # ---- queue run ----

    def _start_queue(self):
        if self._queue_running:
            return
        if not self.workbench.queued_jobs():
            return
        self._queue_running = True
        self._stop_requested = False
        self.status_strip.led.set_busy()
        self.workbench.update_controls(True)
        self._run_next()

    def _run_next(self):
        if self._stop_requested:
            return self._finish_queue()
        pending = self.workbench.queued_jobs()
        if not pending:
            return self._finish_queue()
        job = pending[0]
        self._current_job = job
        self._milestone_bucket = 0
        out_dir = self._output_dir_for(job.path)
        job.output_dir = out_dir
        self.workbench.set_job_state(job.path, Job.RUNNING)
        self.stage.show_extracting(self._game_name_for(job.path), 0, 0, 0)

        self._extract_worker = ExtractWorker(job.path, out_dir,
                                            self._extract_options())
        self._extract_worker.progress.connect(self._on_extract_progress)
        self._extract_worker.done.connect(self._on_extract_done)
        self._extract_worker.start()

    def _on_extract_progress(self, current: int, total: int, path: str,
                            decoded_ok: int):
        job = self._current_job
        if not job:
            return
        job.decoded_ok = decoded_ok
        job.progress_text = f"{current}/{total}"
        self.workbench._render_queue()
        self.stage.show_extracting(self._game_name_for(job.path),
                                  current, total, decoded_ok)
        # milestone flash on crossing each decoded-texture threshold
        bucket = decoded_ok // self._milestone_step
        if bucket > self._milestone_bucket:
            self._milestone_bucket = bucket
            self.status_strip.led.flash_milestone()

    def _on_extract_done(self, result: dict):
        self._extract_worker = None
        job = self._current_job
        canceled = bool(result.get("canceled")) or self._stop_requested
        if job:
            job.summary = result.get("summary", {})
            job.decoded_ok = job.summary.get("textures_decoded_ok", job.decoded_ok)
            job.progress_text = ""
            if canceled:
                # Partial outputs were still written; do not bump lifetime
                # stats for an aborted run, and leave the stage alone.
                job.state = Job.CANCELED
                job.error = ""
            elif result.get("success"):
                job.state = Job.COMPLETE
                job.error = ""
                self._record_run(job.decoded_ok)
                self._show_sample_texture(job)
            else:
                job.state = Job.FAILED
                job.error = result.get("error_message", "Unknown error")
                self.status_strip.led.set_error()
            self.workbench._render_queue()
            self.workbench.jobs_changed.emit()
        self._current_job = None
        if not self._stop_requested:
            self._run_next()
        else:
            self._finish_queue()

    def _show_sample_texture(self, job: Job):
        """Pick a real decoded texture from the manifest and show it on stage."""
        out_dir = job.output_dir
        png = ""
        rec = {}
        manifest_path = os.path.join(out_dir, "manifest.json")
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            for r in manifest.get("textures", []):
                if r.get("duplicate_of"):
                    continue
                p = r.get("decoded_png_path", "")
                if not p:
                    continue
                cand = p if os.path.isabs(p) else os.path.join(out_dir, p)
                if os.path.isfile(cand):
                    png, rec = cand, r
                    break
        except (OSError, ValueError):
            pass
        if not png:
            previews = get_output_previews(out_dir, max_count=1)
            png = previews[0] if previews else ""
        self.stage.show_texture(self._game_name_for(job.path), png, rec,
                               job.summary)

    def _stop_queue(self):
        self._stop_requested = True
        if self._extract_worker and self._extract_worker.isRunning():
            # Cooperative: the pipeline checks the cancel event between files,
            # drains its PNG writers, writes partial outputs, and returns;
            # _on_extract_done then marks the job CANCELED and finishes the
            # queue. terminate() is gone: it left the pipeline's PNG-writer
            # pool running and could corrupt interpreter state.
            self._extract_worker.request_cancel()
            self.workbench.btn_stop.setEnabled(False)
            self.workbench.status.setText(
                "Stopping after the current file (partial output is kept)...")
        else:
            if self._current_job:
                self.workbench.set_job_state(self._current_job.path,
                                             Job.CANCELED)
                self._current_job = None
            self._finish_queue()

    def _finish_queue(self):
        self._queue_running = False
        self._stop_requested = False
        self._current_job = None
        if self.status_strip.led._color != HingeLED.ERROR:
            self.status_strip.led.set_idle()
        self.workbench.update_controls(False)

    # ---- lifecycle ----

    def closeEvent(self, event):
        if self._icon_loader and self._icon_loader.isRunning():
            self._icon_loader.stop()
            self._icon_loader.wait(2000)
        for w in list(self._scan_workers):
            w.wait(1000)
        for w in list(self._banner_workers):
            w.wait(1000)
        if self._extract_worker and self._extract_worker.isRunning():
            # Ask nicely first; the pipeline exits between files. terminate()
            # remains only as a last resort on app exit, where the process is
            # going away regardless.
            self._extract_worker.request_cancel()
            if not self._extract_worker.wait(8000):
                self._extract_worker.terminate()
                self._extract_worker.wait(2000)
        self.cfg["window_width"] = self.width()
        self.cfg["window_height"] = self.height()
        self.cfg["library_paths"] = self.workbench.current_paths()
        save_config(self.cfg)
        super().closeEvent(event)


def _setup_file_logging(verbose: bool) -> None:
    """Rotating log at ~/.3ds-texture-forge/forge.log plus an excepthook.

    The packaged exe is windowed (no console), so until now a crash or a
    misbehaving extraction left nothing to inspect. Best-effort: a logging
    failure must never block launch.
    """
    try:
        import logging
        from logging.handlers import RotatingFileHandler
        from tex_forge.gui.config import CONFIG_DIR

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            CONFIG_DIR / "forge.log", maxBytes=1_000_000, backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root = logging.getLogger()
        root.addHandler(handler)
        root.setLevel(logging.DEBUG if verbose else logging.INFO)
        logging.getLogger(__name__).info(
            "Texture Forge GUI starting (verbose=%s)", verbose)

        prev_hook = sys.excepthook

        def _log_uncaught(exc_type, exc, tb):
            try:
                logging.getLogger("tex_forge.gui").critical(
                    "Uncaught exception", exc_info=(exc_type, exc, tb))
            finally:
                prev_hook(exc_type, exc, tb)

        sys.excepthook = _log_uncaught
    except Exception:
        pass


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    _setup_file_logging(bool(load_config().get("verbose_logging", False)))
    family = load_app_font()
    app.setFont(QFont(family, 10))
    w = HomeMenuWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
