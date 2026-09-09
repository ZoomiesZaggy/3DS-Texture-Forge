"""Settings persistence for 3DS Texture Forge GUI."""

import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".3ds-texture-forge"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "last_input_path": "",
    "last_output_path": "",
    "verbose_logging": False,
    "scan_all_files": False,
    "dump_raw": False,
    "new_folder_per_run": True,
    "window_width": 1000,
    "window_height": 720,
}


def load_config() -> dict:
    """Load config from disk, returning defaults for missing keys."""
    cfg = dict(DEFAULT_CONFIG)
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                cfg.update(saved)
    except Exception:
        pass
    return cfg


def save_config(cfg: dict):
    """Save config to disk."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass
