"""Logging convenience -- one place to flip the verbosity knobs.

The CLI and GUI both call setup_logging() once at startup; library callers
either don't touch logging at all (default Python behaviour) or call this
themselves.

Why a custom helper instead of basicConfig in the entry points?
  * The CLI extract command suppresses INFO logs while the progress bar
    is on screen so the bar doesn't get fragmented.
  * The GUI wants logs on stderr but does NOT want them mixed with
    progress callbacks that go through Qt signals.

Both cases want the same formatter, so it lives here.
"""

from __future__ import annotations

import logging
import sys
from typing import Optional


def setup_logging(verbose: bool = False, quiet: bool = False, stream=None) -> None:
    """Configure the root logger for tex_forge.

    Precedence: quiet > verbose > default(INFO).
    """
    if quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s",
        stream=stream or sys.stderr,
        force=True,
    )


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Get a named logger. Module callers should pass __name__."""
    return logging.getLogger(name)
