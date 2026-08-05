"""Safe file loader with encoding fallback."""

from __future__ import annotations

from pathlib import Path


def load_text(path: Path) -> str:
    """Return text of *path* with UTF-8 decoding (replacement chars on invalid bytes)."""
    # GUARDRAIL: the old strict-then-retry double read produced byte-identical output
    # (valid UTF-8 never triggers replacement) but cost a second I/O pass per bad file.
    # One read with errors="replace" is the same result in one pass — and leaves no
    # UnicodeDecodeError to catch, only OSError.
    return path.read_text(encoding="utf-8", errors="replace")
