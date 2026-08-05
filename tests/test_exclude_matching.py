"""Unit tests for --exclude pattern matching (the wrapper over the gitignore matcher).

Exclude patterns map onto the shared matcher (_matches_pattern):
  'dir/**' (the _expand output for directories) → gitignore dir pattern, so the
    directory itself AND everything under it match from any depth (this is what
    keeps subtree pruning working)
  other '**' patterns → passed through (fnmatch handles any depth)
  'a/b' (path-specific) → root-anchored '/a/b' (matches from root only,
    preserving the old full-fnmatch behavior)
  bare names / wildcards → matched as any path component
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Ensure the src package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from catrepo.walker import _matches_exclude_pattern


class TestExcludePattern(unittest.TestCase):
    def assert_excludes(self, rel_path: str, pattern: str, msg: str = "") -> None:
        self.assertTrue(
            _matches_exclude_pattern(rel_path, pattern),
            msg or f"{pattern!r} should match {rel_path!r}",
        )

    def assert_keeps(self, rel_path: str, pattern: str, msg: str = "") -> None:
        self.assertFalse(
            _matches_exclude_pattern(rel_path, pattern),
            msg or f"{pattern!r} should NOT match {rel_path!r}",
        )

    # ── 'dir/**' — what _expand produces for --exclude <dir> ────────

    def test_expanded_dir_matches_file_inside(self) -> None:
        self.assert_excludes("docs/notes.md", "docs/**")

    def test_expanded_dir_matches_dir_itself_for_pruning(self) -> None:
        # GUARDRAIL: dir/** must match the bare dir path — without this the walker
        # would descend into excluded trees and per-file filter instead of pruning.
        self.assert_excludes("docs", "docs/**")

    def test_expanded_dir_matches_from_any_depth(self) -> None:
        self.assert_excludes("a/docs/x.md", "docs/**")
        self.assert_excludes("projects/app/dist/bundle.js", "dist/**")

    def test_expanded_dir_does_not_match_unrelated(self) -> None:
        self.assert_keeps("docx/notes.md", "docs/**")
        self.assert_keeps("src/app.py", "docs/**")

    # ── path-specific patterns stay root-relative ───────────────────

    def test_path_specific_root_relative(self) -> None:
        # GUARDRAIL: src/*.js must NOT match a/src/*.js — the wrapper maps
        # path-specific excludes to a root-anchored pattern (/src/*.js).
        self.assert_excludes("src/x.js", "src/*.js")
        self.assert_keeps("a/src/x.js", "src/*.js")

    def test_path_specific_exact(self) -> None:
        self.assert_excludes("app/models/user.ts", "app/models/user.ts")
        self.assert_keeps("app/models/post.ts", "app/models/user.ts")

    # ── bare names / wildcards match any component ("anywhere in the path") ──

    def test_bare_name_anywhere(self) -> None:
        self.assert_excludes("a/node_modules/x/index.js", "node_modules")
        self.assert_excludes("node_modules/x", "node_modules")

    def test_wildcard_extension(self) -> None:
        self.assert_excludes("debug.log", "*.log")
        self.assert_excludes("src/debug.log", "*.log")
        self.assert_keeps("src/app.py", "*.log")

    def test_question_mark(self) -> None:
        self.assert_excludes("file1.txt", "file?.txt")
        self.assert_keeps("file12.txt", "file?.txt")

    # ── middle '**' — fnmatch crosses /, consistent with the pinned gitignore stance ──

    def test_middle_double_star(self) -> None:
        self.assert_excludes("a/x/b", "a/**/b")
        self.assert_excludes("a/x/y/b", "a/**/b")
        self.assert_keeps("a/b", "a/**/b")

    def test_nested_expanded_dir_via_wildcard(self) -> None:
        self.assert_excludes("dist/js/chunk-1.js", "dist/**")
        self.assert_excludes("dist", "dist/**")


if __name__ == "__main__":
    unittest.main()
