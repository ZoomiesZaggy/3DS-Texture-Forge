"""GUI settings persistence (~/.3ds-texture-forge/config.json)."""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".3ds-texture-forge"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "last_input_path": "",
    "last_output_path": "",
    "verbose_logging": False,
    "scan_all_files": False,
    "dump_raw": False,
    "dedup": False,
    "new_folder_per_run": True,
    # "normal" or "azahar". Read by the HOME Menu UI's extract options and
    # editable in its Settings dialog (it was previously only reachable by
    # hand-editing this file).
    "output_mode": "normal",
    "window_width": 1000,
    "window_height": 720,
    # HOME Menu UI additions (Pass 1+). library_paths defaults to the two ROM
    # set locations from the handoff; both are user-configurable in the UI.
    "library_paths": [
        r"D:\3ds",
        r"D:\3ds Rom set\No-Intro\Nintendo - Nintendo 3DS (Decrypted)",
    ],
    "theme": "sky",
    # Persistent lifetime counters for the Activity Log heartbeat. Wired in a
    # later pass; seeded there with a clearly labelled placeholder until real
    # run history accrues.
    "lifetime_textures": 0,
    "lifetime_games": 0,
    "lifetime_seeded": False,
}


def load_config() -> dict:
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


def save_config(cfg: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass
