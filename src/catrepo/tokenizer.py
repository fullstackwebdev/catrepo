"""Token counting helpers."""

from __future__ import annotations


# GUARDRAIL: total_tokens() was dead code (no callers) and dragged in the loader
# dependency — removed. The tiktoken try/except fallback stays: tiktoken is an
# optional dependency, len(text)//4 must keep working when it's not installed.
def approximate_tokens(text: str) -> int:
    """Return approximate token count of ``text``."""
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, len(text) // 4)
