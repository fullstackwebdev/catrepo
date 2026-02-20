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
    encoding: str = "utf-8",
    **cli_kwargs: Any,
) -> str:
    """Return a repository dump as a string.

    Args:
        path_or_url: Local directory or remote repository URL.
        fmt: Output format ("text", "json" or "html").
        encoding: Suggested encoding if the caller writes the dump to disk. The
            value is not used by ``dump_repo`` itself.
        **cli_kwargs: Extra options matching the CLI such as ``include``,
            ``exclude``, ``max_size``, ``max_tokens``, ``binary_strict``,
            ``use_gitignore``, ``show_tree``, ``tree_max_depth``, 
            ``tree_show_tokens``, ``tree_show_size``, ``tree_sort_by``, 
            ``tree_dirs_first`` and ``private_token``.

    Returns:
        The rendered dump.
    """

    include = cli_kwargs.get("include", ["*"])
    exclude = cli_kwargs.get("exclude", [])
    max_size = cli_kwargs.get("max_size", DEFAULT_MAX_SIZE)
    max_tokens = cli_kwargs.get("max_tokens")
    binary_strict = cli_kwargs.get("binary_strict", True)
    use_gitignore = cli_kwargs.get("use_gitignore", True)
    private_token = cli_kwargs.get("private_token")
    
    # Tree options
    show_tree = cli_kwargs.get("show_tree", True)
    tree_max_depth = cli_kwargs.get("tree_max_depth")
    tree_show_tokens = cli_kwargs.get("tree_show_tokens", True)
    tree_show_size = cli_kwargs.get("tree_show_size", False)
    tree_sort_by = cli_kwargs.get("tree_sort_by", "name")
    tree_dirs_first = cli_kwargs.get("tree_dirs_first", True)

    path = Path(path_or_url)
    if path.exists():
        files = collect_files(
            path,
            include,
            exclude,
            max_size=max_size,
            binary_strict=binary_strict,
            use_gitignore=use_gitignore,
        )
        return render(
            files,
            path,
            max_tokens=max_tokens,
            fmt=fmt,
            show_tree=show_tree,
            tree_max_depth=tree_max_depth,
            tree_show_tokens=tree_show_tokens,
            tree_show_size=tree_show_size,
            tree_sort_by=tree_sort_by,
            tree_dirs_first=tree_dirs_first,
        )

    url = str(path_or_url)
    with download_repo(url, private_token) as tmp:
        files = collect_files(
            tmp,
            include,
            exclude,
            max_size=max_size,
            binary_strict=binary_strict,
            use_gitignore=use_gitignore,
        )
        return render(
            files,
            tmp,
            max_tokens=max_tokens,
            fmt=fmt,
            show_tree=show_tree,
            tree_max_depth=tree_max_depth,
            tree_show_tokens=tree_show_tokens,
            tree_show_size=tree_show_size,
            tree_sort_by=tree_sort_by,
            tree_dirs_first=tree_dirs_first,
        )
