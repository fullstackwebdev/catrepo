"""Tests for AST/lexical importance ranking (--contents-sort ast).

Pins the contract:
  1. entry points (__main__ guard, conventional names, require.main) come first
  2. files reachable from entries via imports come next, then unreachable source
  3. within a tier: complexity desc, then in-degree desc, then path
  4. Python = real AST; TS/JS = lexical proxy; non-source ranks last
  5. broken Python warns and ranks last instead of failing the dump
"""

from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path

# Ensure the src package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from catrepo.analyzer import rank_files
from catrepo.renderer import Dump, FileDump, render_repo

PY_SAMPLE = {
    "main.py": (
        "import utils\n"
        "import handlers\n"
        "\n"
        "def main():\n"
        "    handlers.handle(1)\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    ),
    "handlers.py": (
        "import utils\n"
        "\n"
        "def handle(x):\n"
        "    if x:\n"
        "        for i in range(10):\n"
        "            while i:\n"
        "                i -= 1\n"
        "    return utils.helper(x)\n"
    ),
    "utils.py": "def helper(x):\n    return x\n",
    "dead.py": "def unused():\n    pass\n",
    "README.md": "# docs\n",
}

TS_SAMPLE = {
    "src/main.ts": (
        "import { handler } from './handler';\n"
        "handler(1);\n"
    ),
    "src/handler.ts": (
        "import { util } from './util';\n"
        "export function handler(x: number) {\n"
        "  if (x > 0) {\n"
        "    for (let i = 0; i < x; i++) {\n"
        "      while (i) { i--; }\n"
        "    }\n"
        "  }\n"
        "  return util(x);\n"
        "}\n"
    ),
    "src/util.ts": "export function util(x: number) { return x; }\n",
    "src/old.js": "// legacy entry, never imported\nexports.foo = function() {};\n",
}


class TestRankPython(unittest.TestCase):
    def test_entry_then_complexity_then_unreachable(self):
        rank = rank_files(PY_SAMPLE)
        order = sorted(rank, key=rank.get)
        # main.py is the only entry → tier 0; handlers (4) before utils (1);
        # dead.py unreachable; README non-source last.
        self.assertEqual(
            order,
            ["main.py", "handlers.py", "utils.py", "dead.py", "README.md"],
        )

    def test_cli_name_is_entry_without_guard(self):
        rank = rank_files({"cli.py": "def main():\n    pass\n"})
        self.assertEqual(rank["cli.py"], 0)

    def test_broken_python_ranks_last_without_crashing(self):
        rank = rank_files({"ok.py": "x = 1\n", "broken.py": "def foo(:\n"})
        self.assertEqual(rank["ok.py"], 0)
        self.assertEqual(rank["broken.py"], 1)

    def test_relative_and_package_imports_resolve(self):
        contents = {
            "pkg/__init__.py": "from . import core\n",
            "pkg/core.py": "from .util import x\n",
            "pkg/util.py": "X = 1\n",
            "runner.py": "import pkg.core\n",
        }
        rank = rank_files(contents)
        # GUARDRAIL: no entry point here (no guard, no conventional name) —
        # everything is tier 2 sorted by in_degree desc then path. core is
        # imported by both pkg/__init__ and runner (in_degree 2); util has
        # in_degree 1; pkg/__init__ and runner have in_degree 0 → path tie-break
        # ("pkg/__init__.py" < "runner.py") puts runner last.
        order = sorted(rank, key=rank.get)
        self.assertEqual(
            order,
            ["pkg/core.py", "pkg/util.py", "pkg/__init__.py", "runner.py"],
        )


class TestRankTypeScript(unittest.TestCase):
    def test_ts_lexical_ranking(self):
        rank = rank_files(TS_SAMPLE)
        order = sorted(rank, key=rank.get)
        # GUARDRAIL: TS_SAMPLE has no README.md — main.ts entry, handler.ts
        # complex (4) before util.ts, old.js unreachable.
        self.assertEqual(
            order,
            ["src/main.ts", "src/handler.ts", "src/util.ts", "src/old.js"],
        )

    def test_require_main_is_entry(self):
        rank = rank_files({"server.js": "if (require.main === module) { main(); }\n"})
        self.assertEqual(rank["server.js"], 0)

    def test_js_specifier_resolves_to_ts(self):
        rank = rank_files({
            "src/main.ts": "import { x } from './util.js';\n",
            "src/util.ts": "export const x = 1;\n",
        })
        self.assertEqual(rank["src/util.ts"], 1)  # reachable, not entry

    def test_package_import_ignored(self):
        rank = rank_files({
            "src/main.ts": "import React from 'react';\n",
            "src/util.ts": "export const x = 1;\n",
        })
        # util.ts is not reachable (bare package import ignored) → tier 2
        self.assertEqual(rank["src/util.ts"], 1)
        self.assertEqual(rank["src/main.ts"], 0)


class TestRendererIntegration(unittest.TestCase):
    def _ast_order(self, files):
        """Run Dump._sort_contents over (path, content) pairs — no filesystem."""
        d = object.__new__(Dump)
        d.file_dumps = []
        for path, content in files:
            fd = object.__new__(FileDump)
            fd.path = Path(path)
            fd.full_path = Path(".") / fd.path
            fd.size = len(content)
            fd.mtime = 1.0
            fd.tokens = 0
            fd.content = content
            d.file_dumps.append(fd)
        d.contents_sort = "ast"
        d._sort_contents()
        return [fd.path.as_posix() for fd in d.file_dumps]

    def test_sort_contents_ast(self):
        order = self._ast_order(list(PY_SAMPLE.items()))
        self.assertEqual(
            order,
            ["main.py", "handlers.py", "utils.py", "dead.py", "README.md"],
        )

    def test_mtime_and_path_sorts_unaffected(self):
        files = list(PY_SAMPLE.items())
        d = object.__new__(Dump)
        d.file_dumps = []
        for path, content in files:
            fd = object.__new__(FileDump)
            fd.path = Path(path)
            fd.full_path = Path(".") / fd.path
            fd.size = len(content)
            fd.mtime = 5.0 if path == "main.py" else 1.0
            fd.tokens = 0
            fd.content = content
            d.file_dumps.append(fd)
        d.contents_sort = "mtime"
        d._sort_contents()
        self.assertEqual(d.file_dumps[0].path.as_posix(), "main.py")
        d.contents_sort = "path"
        d._sort_contents()
        self.assertEqual(
            [fd.path.as_posix() for fd in d.file_dumps],
            sorted(path for path, _ in files),
        )

    def test_end_to_end_render_repo(self):
        # GUARDRAIL: never use /tmp for fixtures — tests create a scratch dir
        # under the repo root and always clean it up (even on failure).
        fixture = Path(__file__).resolve().parents[1] / ".tmp_ast_e2e"
        try:
            fixture.mkdir()
            (fixture / "entry.py").write_text(
                "import lib\nlib.work()\n\nif __name__ == '__main__':\n    entry()\n"
            )
            (fixture / "lib.py").write_text(
                "def work():\n    if True:\n        for i in range(3):\n            pass\n"
            )
            (fixture / "notes.md").write_text("# notes\n")
            out = render_repo(fixture, contents_sort="ast")
            sections = [
                line for line in out.splitlines() if line.startswith("### ")
            ]
            self.assertEqual(
                sections, ["### entry.py", "### lib.py", "### notes.md"]
            )
        finally:
            shutil.rmtree(fixture, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
