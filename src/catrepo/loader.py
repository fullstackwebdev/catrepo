"""Safe file loader with encoding fallback."""

from __future__ import annotations

from pathlib import Path


def load_text(path: Path) -> str:
    """Return text of *path* with UTF-8 fallback."""

    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")
