"""Render repository files into a single dump."""

from __future__ import annotations

import html
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .loader import load_text
from .tokenizer import approximate_tokens
from .walker import FileInfo
from .tree import generate_tree_view

# GUARDRAIL: the old size-only pareto filter dropped REAL source files (click's
# core.py is 78× the median token count) — "outlier == noise" is false when a repo
# has a legitimately large central module. Only files matching these generated/noise
# names are now eligible for filtering; real source is never removed.
NOISE_BASENAMES = frozenset({
    # lockfiles / generated dependency artifacts
    "uv.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "npm-shrinkwrap.json", "cargo.lock", "poetry.lock", "pipfile.lock",
    "composer.lock", "gemfile.lock", "go.sum", "bun.lock",
    # changelogs (long prose, low code density)
    "changelog", "changelog.md", "changelog.rst",
    "changes.md", "changes.rst", "history.md", "news.md",
})
NOISE_SUFFIXES = (".min.js", ".min.css", ".map", ".csv", ".tsv")


def _is_noise_file(path: Path) -> bool:
    """True if the file is generated/noise by name (lockfile, changelog, minified, data)."""
    name = path.name.lower()
    return name in NOISE_BASENAMES or name.endswith(NOISE_SUFFIXES)


class FileDump:
    """A file plus its loaded contents and token count."""

    def __init__(self, info: FileInfo, root: Path) -> None:
        self.path = info.path
        self.full_path = root / info.path
        self.size = info.size
        # GUARDRAIL: FileDump used to throw away info.mtime, which made ordering
        # the contents section by edit recency impossible — keep it for sorting.
        self.mtime = info.mtime
        self.tokens = 0
        self.content = ""
        try:
            self.content = load_text(self.full_path)
            self.tokens = approximate_tokens(self.content)
        except OSError:
            # GUARDRAIL: was `except Exception` — that silently turned real bugs
            # (typos, logic errors) into empty files. load_text handles decode errors
            # internally (errors="replace") and can only raise OSError, so catch only
            # what can actually happen — fail first on anything else.
            self.content = ""
            self.tokens = 0


class Dump:
    def __init__(
        self,
        files: List[FileInfo],
        root: Path,
        max_tokens: int | None = None,
        tree_max_depth: Optional[int] = None,
        tree_show_size: bool = False,
        tree_sort_by: str = "name",
        tree_dirs_first: bool = True,
        max_token_size_multiplier: float = 0.0,
        contents_sort: str = "mtime",
    ) -> None:
        self.root = root
        self.files = files
        self.file_dumps: List[FileDump] = [FileDump(info, root) for info in files]
        self.total_tokens = sum(fd.tokens for fd in self.file_dumps)
        
        # GUARDRAIL: filter is opt-in (multiplier <= 0 = off) and pattern-aware —
        # the size-only default-on version amputated real source (click's core.py).
        self._filter_outliers(max_token_size_multiplier)
        
        # Tree options
        self.tree_max_depth = tree_max_depth
        self.tree_show_size = tree_show_size
        self.tree_sort_by = tree_sort_by
        self.tree_dirs_first = tree_dirs_first
        
        if max_tokens is not None and self.total_tokens > max_tokens:
            self._truncate(max_tokens)

        # GUARDRAIL: contents sort must run AFTER _truncate — _truncate re-sorts
        # file_dumps by token size and pops victims, so any order set before it is
        # destroyed. Sort last so the presentation order is always the requested one.
        self.contents_sort = contents_sort
        self._sort_contents()

    def _truncate(self, limit: int) -> None:
        self.file_dumps.sort(key=lambda f: (f.tokens, f.path.as_posix()), reverse=True)
        while self.total_tokens > limit and self.file_dumps:
            victim = self.file_dumps.pop(0)
            self.total_tokens -= victim.tokens

    def _sort_contents(self) -> None:
        """Order the contents section for output.

        "mtime": newest-edited first (tie-break: path, ascending).
        "path":  alphabetical by relative path — deterministic alternative.
        """
        if self.contents_sort == "mtime":
            # GUARDRAIL: tie-break on path is mandatory — git checkouts and remote
            # zipball extractions stamp identical mtimes on every file, so without
            # the tie-break the order would be arbitrary (non-deterministic output).
            self.file_dumps.sort(key=lambda fd: (-fd.mtime, fd.path.as_posix()))
        else:
            self.file_dumps.sort(key=lambda fd: fd.path.as_posix())

    def _filter_outliers(self, multiplier: float) -> None:
        """Remove generated/noise files whose token count exceeds multiplier × median.

        Disabled when ``multiplier <= 0``. When enabled, only files matching
        known noise patterns (lockfiles, changelogs, minified bundles, data
        dumps) are eligible — real source files are never removed.
        """
        if multiplier <= 0:
            return
        # GUARDRAIL: 0/negative multiplier must mean "off" — previously a user
        # could not disable the filter at all (0 × median removed everything).
        nonzero_tokens = [fd.tokens for fd in self.file_dumps if fd.tokens > 0]
        if not nonzero_tokens:
            return
        median = statistics.median(nonzero_tokens)
        threshold = median * multiplier
        before = len(self.file_dumps)
        before_tokens = self.total_tokens
        self.file_dumps = [
            fd for fd in self.file_dumps
            if not (_is_noise_file(fd.path) and fd.tokens > threshold)
        ]
        self.total_tokens = sum(fd.tokens for fd in self.file_dumps)
        removed = before - len(self.file_dumps)
        if removed:
            print(
                f"[catrepo] pareto filter: median={median:,.0f} tok, "
                f"threshold={threshold:,.0f} tok ({multiplier:.1f}×), "
                f"removed {removed} noise file(s), "
                f"{before_tokens:,} → {self.total_tokens:,} tokens",
                file=sys.stderr,
            )

    def as_text(self, repo_name: str) -> str:
        timestamp = datetime.now(timezone.utc).isoformat()
        lines = [f"# Catrepo dump – {repo_name} – {timestamp}"]
        lines.append(f"# ≈ {self.total_tokens} tokens")
        lines.append("")
        
        # Tree view — always on (was gated behind show_tree which was always True; no-tag is harmful)
        lines.append("## File Structure")
        lines.append("")
        lines.append("```")
        tree_view = generate_tree_view(
            self.files,
            self.root,
            max_depth=self.tree_max_depth,
            show_size=self.tree_show_size,
            sort_by=self.tree_sort_by,
            dirs_first=self.tree_dirs_first,
        )
        lines.append(tree_view)
        lines.append("```")
        lines.append("")
        
        # Add file contents
        for fd in self.file_dumps:
            lines.append(f"\n### {fd.path.as_posix()}")
            lines.append(fd.content)
        lines.append("")
        return "\n".join(lines)

    def as_json(self, repo_name: str) -> str:
        obj = {
            "repo": repo_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_tokens": self.total_tokens,
            "files": [
                {
                    "path": fd.path.as_posix(),
                    "contents": fd.content,
                    "tokens": fd.tokens,
                }
                for fd in self.file_dumps
            ],
        }
        return json.dumps(obj, indent=2)

    def as_html(self, repo_name: str) -> str:
        timestamp = datetime.now(timezone.utc).isoformat()
        style = """
        <style>
        html {
            font-size:14px;
            font-family:ui-monospace, SFMono-Regular, Menlo, monospace;
        }
        body {
            margin:0;
            background:#0d1117;
            color:#c9d1d9;
        }
        .container {
            max-width:1100px;
            padding:2rem;
            margin:0 auto;
            display:flex;
            flex-direction:column;
            gap:1rem;
        }
        .header-card, details.file-card {
            border:1px solid #30363d;
            border-radius:6px;
            box-shadow:0 2px 4px rgba(0,0,0,.6);
            background:#161b22;
        }
        .header-card {
            padding:1rem 1.25rem;
        }
        .header-card h1 {
            margin:0 0 .5rem;
            font-size:1.25rem;
        }
        .header-card p {
            margin:0;
            color:#8b949e;
            font-size:.9rem;
        }
        details.file-card summary {
            display:flex;
            align-items:center;
            gap:.75rem;
            cursor:pointer;
            background:#161b22;
            color:inherit;
            list-style:none;
        }
        details.file-card summary:hover {
            background:#21262d;
        }
        details.file-card summary::-webkit-details-marker {display:none;}
        .chevron {
            fill:#58a6ff;
            transition:transform .15s;
            flex:none;
        }
        @media (prefers-reduced-motion: reduce) {
            .chevron {transition:none;}
        }
        details.file-card[open] > summary .chevron {
            transform:rotate(90deg);
        }
        summary:focus-visible {
            outline:2px solid #58a6ff;
            outline-offset:2px;
        }
        .path {
            font-weight:bold;
            flex:1;
            overflow:hidden;
            text-overflow:ellipsis;
            white-space:nowrap;
            direction:rtl;
        }
        .badge {
            font-size:.7rem;
            background:#238636;
            color:#fff;
            padding:.15rem .45rem;
            border-radius:9999px;
        }
        details.file-card pre {
            background:#0d1117;
            padding:1rem 1.25rem;
            margin:0;
            overflow:auto;
            line-height:1.45;
            white-space:pre;
            border-top:1px solid #30363d;
            border-radius:0 0 6px 6px;
            background-image:linear-gradient(transparent 97%,
                rgba(255,255,255,.05) 97%);
            background-size:100% 1.6em;
        }
        @media (max-width:600px) {
            .container {padding:1rem;}
        }
        </style>
        """
        lines = [
            "<!DOCTYPE html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="UTF-8">',
            '<meta name="viewport" content="width=device-width,initial-scale=1">',
            f"<title>{repo_name} dump</title>",
            style,
            "</head>",
            "<body>",
            "<div class='container'>",
            "<div class='header-card'>",
            f"<h1>Catrepo dump – {repo_name}</h1>",
            f"<p>{timestamp} · ≈ {self.total_tokens} tokens</p>",
            "</div>",
        ]
        for fd in self.file_dumps:
            path = html.escape(fd.path.as_posix())
            lines.append("<details class='file-card'>")
            lines.append(
                "<summary>"
                "<svg class='chevron' width='10' height='10'"
                " viewBox='0 0 8 8' aria-hidden='true'>"
                "<path d='M0 0 L6 4 L0 8z'/></svg>"
                f"<span class='path'>{path}</span>"
                "</summary>"
            )
            lines.append("<pre><code>")
            lines.append(html.escape(fd.content))
            lines.append("</code></pre>")
            lines.append("</details>")
        lines.append("</div></body></html>")
        return "\n".join(lines)


def render(
    files: List[FileInfo],
    root: Path,
    *,
    max_tokens: int | None = None,
    fmt: str = "text",
    tree_max_depth: Optional[int] = None,
    tree_show_size: bool = False,
    tree_sort_by: str = "name",
    tree_dirs_first: bool = True,
    max_token_size_multiplier: float = 0.0,
    contents_sort: str = "mtime",
) -> str:
    dump = Dump(
        files,
        root,
        max_tokens=max_tokens,
        tree_max_depth=tree_max_depth,
        tree_show_size=tree_show_size,
        tree_sort_by=tree_sort_by,
        tree_dirs_first=tree_dirs_first,
        max_token_size_multiplier=max_token_size_multiplier,
        contents_sort=contents_sort,
    )
    resolved = root.resolve()
    repo_name = resolved.name or resolved.parent.name
    if fmt == "json":
        return dump.as_json(repo_name)
    if fmt == "html":
        return dump.as_html(repo_name)
    return dump.as_text(repo_name)
