"""Render repository files into a single dump."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
import html

from .loader import load_text
from .tokenizer import approximate_tokens
from .walker import FileInfo
from .tree import generate_tree_view


class FileDump:
    """A file plus its loaded contents and token count."""

    def __init__(self, info: FileInfo, root: Path) -> None:
        self.path = info.path
        self.full_path = root / info.path
        self.size = info.size
        self.tokens = 0
        self.content = ""
        try:
            self.content = load_text(self.full_path)
            self.tokens = approximate_tokens(self.content)
        except Exception:
            self.content = ""
            self.tokens = 0


class Dump:
    def __init__(
        self,
        files: List[FileInfo],
        root: Path,
        max_tokens: int | None = None,
        show_tree: bool = True,
        tree_max_depth: Optional[int] = None,
        tree_show_tokens: bool = True,
        tree_show_size: bool = False,
        tree_sort_by: str = "name",
        tree_dirs_first: bool = True,
    ) -> None:
        self.root = root
        self.files = files
        self.file_dumps: List[FileDump] = [FileDump(info, root) for info in files]
        self.total_tokens = sum(fd.tokens for fd in self.file_dumps)
        
        # Tree options
        self.show_tree = show_tree
        self.tree_max_depth = tree_max_depth
        self.tree_show_tokens = tree_show_tokens
        self.tree_show_size = tree_show_size
        self.tree_sort_by = tree_sort_by
        self.tree_dirs_first = tree_dirs_first
        
        if max_tokens is not None and self.total_tokens > max_tokens:
            self._truncate(max_tokens)

    def _truncate(self, limit: int) -> None:
        self.file_dumps.sort(key=lambda f: (f.tokens, f.path.as_posix()), reverse=True)
        while self.total_tokens > limit and self.file_dumps:
            victim = self.file_dumps.pop(0)
            self.total_tokens -= victim.tokens

    def as_text(self, repo_name: str) -> str:
        timestamp = datetime.now(timezone.utc).isoformat()
        lines = [f"# Catrepo dump – {repo_name} – {timestamp}"]
        lines.append(f"# ≈ {self.total_tokens} tokens")
        lines.append("")
        
        # Add tree view at the top
        if self.show_tree:
            lines.append("## File Structure")
            lines.append("")
            lines.append("```")
            tree_view = generate_tree_view(
                self.files,
                self.root,
                max_depth=self.tree_max_depth,
                show_tokens=self.tree_show_tokens,
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
    show_tree: bool = True,
    tree_max_depth: Optional[int] = None,
    tree_show_tokens: bool = True,
    tree_show_size: bool = False,
    tree_sort_by: str = "name",
    tree_dirs_first: bool = True,
) -> str:
    dump = Dump(
        files,
        root,
        max_tokens=max_tokens,
        show_tree=show_tree,
        tree_max_depth=tree_max_depth,
        tree_show_tokens=tree_show_tokens,
        tree_show_size=tree_show_size,
        tree_sort_by=tree_sort_by,
        tree_dirs_first=tree_dirs_first,
    )
    resolved = root.resolve()
    repo_name = resolved.name or resolved.parent.name
    if fmt == "json":
        return dump.as_json(repo_name)
    if fmt == "html":
        return dump.as_html(repo_name)
    return dump.as_text(repo_name)
