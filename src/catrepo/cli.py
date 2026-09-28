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
    build_dump,
    dump_to_format,
    repo_name_for,
)
from .walker import DEFAULT_MAX_SIZE


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument(
    "path",
    required=False,
    default=".",
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
# GUARDRAIL: bare `catrepo` must exclude jsonl/log/venv/git/node_modules by default
# — without these, a single session transcript (4MB) blows past any token cap
@click.option(
    "--exclude",
    multiple=True,
    default=["*.jsonl", "*.log", ".venv/", ".git/", "node_modules/"],
    help=(
        "Glob(s) to exclude. Trailing '/' or '\\' expands recursively. "
        "Default: *.jsonl, *.log, .venv/, .git/, node_modules/"
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
    type=click.Choice(["text", "json", "jsonl", "html"]),
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
    type=click.Choice(["name", "size", "tokens", "mtime"]),
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
# GUARDRAIL: 'ast' sorts by importance — Python via a real AST, TS/JS via a
# lexical proxy (no native deps). Entry points first, then by complexity and
# import count. Default stays 'mtime' (newest first) for parity.
@click.option(
    "--contents-sort",
    type=click.Choice(["mtime", "path", "ast"]),
    default=DEFAULT_CONTENTS_SORT,
    show_default=True,
    help=(
        "Order the file contents section: 'mtime' sorts newest-edited first, "
        "'path' sorts alphabetically, 'ast' ranks by importance (entry points "
        "first, then complexity/import count — Python via a real AST, TS/JS "
        "via a lexical proxy). Tree view is unaffected."
    ),
)
@click.option(
    "--tree-lines/--no-tree-lines",
    default=True,
    help="Show line ranges [Lstart-Lend] in tree view (default: on)",
)
@click.option("--stdout/--no-stdout", default=False, help="Print dump to STDOUT (default: off)")
# GUARDRAIL: outfile defaults to CATREPO.md so bare `catrepo` produces a file, not stdout
@click.option("--outfile", type=click.Path(path_type=Path), default="CATREPO.md", show_default=True, help="Write dump to file")
@click.option(
    "--encoding",
    default="utf-8",
    show_default=True,
    help="Encoding for --outfile",
)
# GUARDRAIL: structured siblings are ON by default — the memory system consumes the
# .json/.jsonl, and making them opt-in meant every consumer re-parsed the tree text.
@click.option(
    "--structured/--no-structured",
    default=True,
    help="Also write structured .json and .jsonl dumps (default: on)",
)
@click.option(
    "--json-out",
    type=click.Path(path_type=Path),
    default=None,
    help="Path for structured JSON (default: <outfile>.json)",
)
@click.option(
    "--jsonl-out",
    type=click.Path(path_type=Path),
    default=None,
    help="Path for JSONL, one file per line (default: <outfile>.jsonl)",
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
    tree_lines: bool,
    stdout: bool,
    outfile: Path | None,
    encoding: str,
    structured: bool,
    json_out: Path | None,
    jsonl_out: Path | None,
) -> None:
    """Flatten a repository into one text dump."""
    # GUARDRAIL: path now defaults to "." so bare `catrepo` works — only error if remote_url with explicit path
    if remote_url and path and str(path) != ".":
        raise click.UsageError("--remote-url cannot be used with PATH")

    # GUARDRAIL: --contents-sort mtime must also set tree_sort so the tree matches the content order
    # — without this, the tree sorts by name while content is by mtime, making line numbers confusing
    if contents_sort == "mtime" and tree_sort == "name":
        tree_sort = "mtime"

    try:
        # GUARDRAIL: build the Dump ONCE — text + json + jsonl are three views of the
        # same walk; calling render_repo three times re-reads every file three times.
        def _build(root: Path):
            dump = build_dump(
                root,
                include=include,
                exclude=exclude,
                max_size=max_size,
                binary_strict=binary_strict,
                max_tokens=max_tokens,
                max_token_size_multiplier=max_token_size,
                tree_max_depth=tree_depth,
                tree_show_size=tree_size,
                tree_sort_by=tree_sort,
                tree_dirs_first=tree_dirs_first,
                contents_sort=contents_sort,
                tree_show_lines=tree_lines,
            )
            return dump, repo_name_for(root)

        if remote_url:
            with download_repo(remote_url, private_token) as tmp:
                dump, repo = _build(tmp)
        else:
            dump, repo = _build(cast(Path, path))
    except Exception as exc:  # pragma: no cover - fatal CLI errors
        click.echo(str(exc), err=True)
        raise SystemExit(1)

    output = dump_to_format(dump, repo, fmt)
    if outfile:
        outfile.write_text(output, encoding=encoding, errors="replace")

    # GUARDRAIL: structured siblings are derived from --outfile so consumers get
    # machine-readable data without a second required flag; -no-structured disables.
    if structured and outfile:
        json_path = json_out or outfile.with_suffix(".json")
        jsonl_path = jsonl_out or outfile.with_suffix(".jsonl")
        json_path.write_text(dump.as_json(repo), encoding=encoding, errors="replace")
        jsonl_path.write_text(dump.as_jsonl(repo), encoding=encoding, errors="replace")

    if stdout:
        click.echo(output)


if __name__ == "__main__":  # pragma: no cover
    main()
