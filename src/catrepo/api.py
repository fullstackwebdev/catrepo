"""High-level programmatic API for catrepo."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .downloader import download_repo
from .renderer import render
from .walker import DEFAULT_MAX_SIZE, collect_files


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
        **cli_kwargs: Extra options matching the CLI such as ``include``,
            ``exclude``, ``max_size``, ``max_tokens``, ``binary_strict``,
            ``tree_show_size``, ``tree_sort_by``,
            ``tree_dirs_first``, ``max_token_size_multiplier``,
            ``contents_sort`` and ``private_token``.

    Returns:
        The rendered dump.
    """
    # GUARDRAIL: `encoding` param was removed — it was documented as "not used by
    # dump_repo itself"; a dead keyword invites callers to pass options that do nothing.

    include = cli_kwargs.get("include", ["*"])
    exclude = cli_kwargs.get("exclude", [])
    max_size = cli_kwargs.get("max_size", DEFAULT_MAX_SIZE)
    max_tokens = cli_kwargs.get("max_tokens")
    binary_strict = cli_kwargs.get("binary_strict", True)
    private_token = cli_kwargs.get("private_token")
    tree_max_depth = cli_kwargs.get("tree_max_depth")
    tree_show_size = cli_kwargs.get("tree_show_size", False)
    tree_sort_by = cli_kwargs.get("tree_sort_by", "name")
    tree_dirs_first = cli_kwargs.get("tree_dirs_first", True)
    # GUARDRAIL: keep the 0.0 default in sync with cli.py --max-token-size — the
    # filter is opt-in; a stale 20.0 here would silently re-enable it for API users.
    max_token_size_multiplier = cli_kwargs.get("max_token_size_multiplier", 0.0)
    # GUARDRAIL: contents_sort mirrors the CLI's --contents-sort (default mtime,
    # newest-first). Keep the default in sync with cli.py or API vs CLI drift apart.
    contents_sort = cli_kwargs.get("contents_sort", "mtime")

    # GUARDRAIL: local and remote used to be two near-identical collect+render blocks
    # (only the root differed). One helper, one code path — options can't drift out of
    # sync between the two branches again.
    def _render_root(root: Path) -> str:
        files = collect_files(
            root,
            include,
            exclude,
            max_size=max_size,
            binary_strict=binary_strict,
        )
        return render(
            files,
            root,
            max_tokens=max_tokens,
            fmt=fmt,
            max_token_size_multiplier=max_token_size_multiplier,
            tree_max_depth=tree_max_depth,
            tree_show_size=tree_show_size,
            tree_sort_by=tree_sort_by,
            tree_dirs_first=tree_dirs_first,
            contents_sort=contents_sort,
        )

    path = Path(path_or_url)
    if path.exists():
        return _render_root(path)

    url = str(path_or_url)
    with download_repo(url, private_token) as tmp:
        return _render_root(tmp)
