"""CLI entry point for catrepo."""

from __future__ import annotations

from pathlib import Path
from typing import List, cast

import click

from .renderer import render
from .walker import DEFAULT_MAX_SIZE, collect_files
from .downloader import download_repo


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument(
    "path",
    required=False,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option("--remote-url", help="Git repo URL to download")
@click.option("--private-token", envvar="GITHUB_TOKEN", help="Token for private repos")
@click.option(
    "--include",
    multiple=True,
    default=["*"],
    help=("Glob(s) to include. Trailing '/' or '\\' expands recursively."),
)
@click.option(
    "--exclude",
    multiple=True,
    help=(
        "Glob(s) to exclude. Trailing '/' or '\\' expands recursively. "
        "'.git/' is excluded by default."
    ),
)
@click.option(
    "--max-size",
    type=int,
    default=DEFAULT_MAX_SIZE,
    show_default=f"{DEFAULT_MAX_SIZE} bytes",
    help="Skip files larger than this many bytes",
)
@click.option("--max-tokens", type=int, help="Hard cap; truncate largest files first")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["text", "json", "html"]),
    default="text",
)
@click.option(
    "--binary-strict/--no-binary-strict",
    default=True,
    help="Use strict binary detection",
)
@click.option(
    "--gitignore/--no-gitignore",
    default=True,
    help="Respect .gitignore patterns (default: on)",
)
@click.option(
    "--tree/--no-tree",
    default=True,
    help="Show tree view at top of output (default: on)",
)
@click.option(
    "--tree-depth",
    type=int,
    default=None,
    help="Maximum depth for tree view (default: unlimited)",
)
@click.option(
    "--tree-tokens/--no-tree-tokens",
    default=True,
    help="Show token counts in tree view (default: on)",
)
@click.option(
    "--tree-size/--no-tree-size",
    default=False,
    help="Show file sizes in tree view (default: off)",
)
@click.option(
    "--tree-sort",
    type=click.Choice(["name", "size", "tokens"]),
    default="name",
    help="Sort order for tree view (default: name)",
)
@click.option(
    "--tree-dirs-first/--tree-files-first",
    default=True,
    help="List directories before files in tree (default: dirs first)",
)
@click.option("--stdout/--no-stdout", default=True, help="Print dump to STDOUT")
@click.option("--outfile", type=click.Path(path_type=Path), help="Write dump to file")
@click.option(
    "--encoding",
    default="utf-8",
    show_default=True,
    help="Encoding for --outfile",
)
@click.version_option()
def main(
    path: Path | None,
    remote_url: str | None,
    private_token: str | None,
    include: List[str],
    exclude: List[str],
    max_size: int,
    max_tokens: int | None,
    fmt: str,
    binary_strict: bool,
    gitignore: bool,
    tree: bool,
    tree_depth: int | None,
    tree_tokens: bool,
    tree_size: bool,
    tree_sort: str,
    tree_dirs_first: bool,
    stdout: bool,
    outfile: Path | None,
    encoding: str,
) -> None:
    """Flatten a repository into one text dump."""
    if remote_url and path:
        raise click.UsageError("--remote-url cannot be used with PATH")
    if not remote_url and not path:
        raise click.UsageError("PATH or --remote-url required")

    try:
        if remote_url:
            with download_repo(remote_url, private_token) as tmp:
                files = collect_files(
                    tmp,
                    include,
                    exclude,
                    max_size=max_size,
                    binary_strict=binary_strict,
                    use_gitignore=gitignore,
                )
                output = render(
                    files,
                    tmp,
                    max_tokens=max_tokens,
                    fmt=fmt,
                    show_tree=tree,
                    tree_max_depth=tree_depth,
                    tree_show_tokens=tree_tokens,
                    tree_show_size=tree_size,
                    tree_sort_by=tree_sort,
                    tree_dirs_first=tree_dirs_first,
                )
        else:
            files = collect_files(
                cast(Path, path),
                include,
                exclude,
                max_size=max_size,
                binary_strict=binary_strict,
                use_gitignore=gitignore,
            )
            output = render(
                files,
                cast(Path, path),
                max_tokens=max_tokens,
                fmt=fmt,
                show_tree=tree,
                tree_max_depth=tree_depth,
                tree_show_tokens=tree_tokens,
                tree_show_size=tree_size,
                tree_sort_by=tree_sort,
                tree_dirs_first=tree_dirs_first,
            )
    except Exception as exc:  # pragma: no cover - fatal CLI errors
        click.echo(str(exc), err=True)
        raise SystemExit(1)

    if outfile:
        outfile.write_text(output, encoding=encoding, errors="replace")
    if stdout:
        click.echo(output)


if __name__ == "__main__":  # pragma: no cover
    main()
