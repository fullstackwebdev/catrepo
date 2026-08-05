"""CLI entry point for catrepo."""

from __future__ import annotations

from pathlib import Path
from typing import List, cast

import click

from . import __version__
from .downloader import download_repo
from .renderer import (
    DEFAULT_CONTENTS_SORT,
    DEFAULT_MAX_TOKEN_SIZE_MULTIPLIER,
    render_repo,
)
from .walker import DEFAULT_MAX_SIZE


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
# GUARDRAIL: default flipped 20.0 → 0.0 — the size-only filter amputated real
# source (click's core.py is 78× median); the filter is now opt-in AND
# pattern-aware (only generated/noise files are eligible). Default imported from
# renderer.py so cli/api can't drift.
@click.option(
    "--max-token-size",
    type=float,
    default=DEFAULT_MAX_TOKEN_SIZE_MULTIPLIER,
    show_default=True,
    help=(
        "Opt-in filter (0 = off): exclude generated/noise files (lockfiles, "
        "changelogs, minified bundles, .csv/.tsv) whose token count exceeds "
        "N × median of all files. Real source files are never removed."
    ),
)
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
# GUARDRAIL: --gitignore, --tree, --tree-tokens removed — were always default=True; disabling leaks artifacts or strips useful output
@click.option(
    "--tree-depth",
    type=int,
    default=None,
    help="Maximum depth for tree view (default: unlimited)",
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
# GUARDRAIL: contents ordering is a deliberate default behavior change — mtime
# newest-first is on by default; --contents-sort path gives deterministic
# alphabetical order for stable diffs. Tree view is never affected.
@click.option(
    "--contents-sort",
    type=click.Choice(["mtime", "path"]),
    default=DEFAULT_CONTENTS_SORT,
    show_default=True,
    help=(
        "Order the file contents section: 'mtime' sorts newest-edited first, "
        "'path' sorts alphabetically. Tree view is unaffected."
    ),
)
@click.option("--stdout/--no-stdout", default=True, help="Print dump to STDOUT")
@click.option("--outfile", type=click.Path(path_type=Path), help="Write dump to file")
@click.option(
    "--encoding",
    default="utf-8",
    show_default=True,
    help="Encoding for --outfile",
)
# GUARDRAIL: explicit version instead of click's metadata lookup — importlib.metadata
# only works when installed (a bare checkout has no dist metadata and --version broke).
@click.version_option(version=__version__)
def main(
    path: Path | None,
    remote_url: str | None,
    private_token: str | None,
    include: List[str],
    exclude: List[str],
    max_size: int,
    max_tokens: int | None,
    max_token_size: float,
    fmt: str,
    binary_strict: bool,
    tree_depth: int | None,
    tree_size: bool,
    tree_sort: str,
    tree_dirs_first: bool,
    contents_sort: str,
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
        # GUARDRAIL: collect+render plumbing lives in renderer.render_repo (shared
        # with the API) — the two entry points can't drift apart when options change.
        def _render_root(root: Path) -> str:
            return render_repo(
                root,
                include=include,
                exclude=exclude,
                max_size=max_size,
                binary_strict=binary_strict,
                max_tokens=max_tokens,
                fmt=fmt,
                max_token_size_multiplier=max_token_size,
                tree_max_depth=tree_depth,
                tree_show_size=tree_size,
                tree_sort_by=tree_sort,
                tree_dirs_first=tree_dirs_first,
                contents_sort=contents_sort,
            )

        if remote_url:
            with download_repo(remote_url, private_token) as tmp:
                output = _render_root(tmp)
        else:
            output = _render_root(cast(Path, path))
    except Exception as exc:  # pragma: no cover - fatal CLI errors
        click.echo(str(exc), err=True)
        raise SystemExit(1)

    if outfile:
        outfile.write_text(output, encoding=encoding, errors="replace")
    if stdout:
        click.echo(output)


if __name__ == "__main__":  # pragma: no cover
    main()
