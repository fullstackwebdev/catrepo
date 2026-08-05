"""High-level programmatic API for catrepo."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .downloader import download_repo
from .renderer import render_repo


def dump_repo(
    path_or_url: str | Path,
    *,
    fmt: str = "text",
    **cli_kwargs: Any,
) -> str:
    """Return a repository dump as a string.

    Args:
        path_or_url: Local directory or remote repository URL.
        fmt: Output format ("text", "json" or "html").
        **cli_kwargs: Any option accepted by :func:`render_repo`, plus
            ``private_token`` for remote downloads. Unknown keys raise
            TypeError (fail first — no silent typos).

    Returns:
        The rendered dump.
    """
    # GUARDRAIL: this used to re-declare every option default via
    # cli_kwargs.get(...) and duplicate the collect+render call. Defaults now
    # live ONLY in render_repo's signature; unknown cli_kwargs raise TypeError
    # instead of being silently ignored (a typo'd option used to vanish).
    private_token = cli_kwargs.pop("private_token", None)

    path = Path(path_or_url)
    if path.exists():
        return render_repo(path, fmt=fmt, **cli_kwargs)
    with download_repo(str(path_or_url), private_token) as tmp:
        return render_repo(tmp, fmt=fmt, **cli_kwargs)
