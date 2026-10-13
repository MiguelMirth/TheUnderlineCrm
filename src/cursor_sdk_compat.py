"""Windows compatibility shim for cursor-sdk (must run before importing cursor_sdk)."""
from __future__ import annotations

import os
import sys


def apply_windows_shims() -> None:
    if sys.platform != "win32":
        return
    if not hasattr(os, "get_blocking"):
        os.get_blocking = lambda fd: True  # type: ignore[attr-defined]
    if not hasattr(os, "set_blocking"):
        os.set_blocking = lambda fd, blocking: None  # type: ignore[attr-defined]
