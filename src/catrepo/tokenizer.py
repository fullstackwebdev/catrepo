"""Token counting helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .loader import load_text


def approximate_tokens(text: str) -> int:
    """Return approximate token count of ``text``."""
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, len(text) // 4)


def total_tokens(paths: Iterable[Path]) -> int:
    """Return total tokens for ``paths``."""
    total = 0
    for path in paths:
        try:
            total += approximate_tokens(load_text(path))
        except Exception:
            continue
    return total
