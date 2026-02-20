"""Utility helpers for catrepo."""

from __future__ import annotations

import mimetypes
from pathlib import Path

ASCII_WHITELIST = set(b"\t\n\r")


def is_binary_path(path: Path, *, strict: bool = True) -> bool:
    """Return True if file looks binary."""
    mime, _ = mimetypes.guess_type(path.as_posix())
    if mime is not None and not mime.startswith("text"):
        return True
    try:
        with open(path, "rb") as fh:
            chunk = fh.read(8192)
        if b"\0" in chunk:
            return True
        if strict and chunk:
            non_text = sum(
                1 for b in chunk if not (32 <= b <= 126 or b in ASCII_WHITELIST)
            )
            if non_text / len(chunk) > 0.30:
                return True
        return False
    except OSError:
        return True
