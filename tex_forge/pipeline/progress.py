"""ProgressCallback abstraction so the CLI bar and GUI signals share an API.

Implementations:

    NullProgress         -- discard all updates (default for library callers)
    CLIBarProgress       -- ASCII bar on stderr with ETA
    CallableProgress     -- wrap a (current, total, path, decoded, ...) function
                            Used by the GUI worker thread to forward into Qt signals.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol, runtime_checkable


@runtime_checkable
class ProgressCallback(Protocol):
    def __call__(
        self,
        current: int,
        total: int,
        path: str,
        decoded_ok: int,
    ) -> None: ...


class NullProgress:
    """No-op progress reporter."""

    def __call__(self, current: int, total: int, path: str, decoded_ok: int) -> None:
        return


@dataclass
class CallableProgress:
    """Wrap a 4-arg function. Used by the GUI to forward updates into Qt signals."""

    fn: Callable[[int, int, str, int], None]

    def __call__(self, current: int, total: int, path: str, decoded_ok: int) -> None:
        try:
            self.fn(current, total, path, decoded_ok)
        except Exception:
            # Progress callbacks are advisory; never let them crash the pipeline.
            pass


@dataclass
class CLIBarProgress:
    """ASCII progress bar on stderr -- one redraw every ~150 ms."""

    width: int = 30
    min_interval_s: float = 0.15
    _start_ts: float = field(default_factory=time.time)
    _last_print_ts: float = 0.0

    def __call__(self, current: int, total: int, path: str, decoded_ok: int) -> None:
        now = time.time()
        if now - self._last_print_ts < self.min_interval_s and current < total:
            return
        self._last_print_ts = now

        elapsed = now - self._start_ts
        pct = current / total if total > 0 else 0.0
        filled = int(self.width * pct)
        bar = "=" * filled + "-" * (self.width - filled)

        eta = ""
        if pct > 0.01 and elapsed > 1:
            remaining = elapsed / pct * (1 - pct)
            m, s = divmod(int(remaining), 60)
            eta = f" | ETA: {m}:{s:02d}"

        line = (f"\r  [{bar}] {pct*100:4.0f}% | "
                f"File {current}/{total} | {decoded_ok:,} textures{eta}   ")
        sys.stderr.write(line)
        sys.stderr.flush()
        if current >= total:
            sys.stderr.write("\n")
            sys.stderr.flush()
