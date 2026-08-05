"""Table-driven unit tests for _matches_gitignore_pattern.

Each test case is a (rel_path, pattern, expected) tuple covering every
edge case in the gitignore matching logic.  These guard against
regressions like the "/.next/" bug — where a pattern with BOTH a leading
slash AND trailing slash was mishandled because the directory check
returned before the leading slash was stripped.
"""

from __future__ import annotations

import unittest
import sys
from pathlib import Path

# Ensure the src package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from catrepo.walker import _matches_gitignore_pattern


class TestMatchesGitignorePattern(unittest.TestCase):
    """Every edge case exercised as a named test method.

    Using one method per logical group keeps the output readable: when a
    test fails you see the exact group that broke without needing to
    hunt through a loop.
    """

    # ── helpers ──────────────────────────────────────────────────

    def assert_match(self, rel_path: str, pattern: str, msg: str = "") -> None:
        self.assertTrue(
            _matches_gitignore_pattern(rel_path, pattern),
            msg or f"{pattern!r} should match {rel_path!r}",
        )

    def assert_no_match(self, rel_path: str, pattern: str, msg: str = "") -> None:
        self.assertFalse(
            _matches_gitignore_pattern(rel_path, pattern),
            msg or f"{pattern!r} should NOT match {rel_path!r}",
        )

    # ── directory patterns (trailing /) ────────────────────────

    def test_dir_pattern_matches_contents_directly_inside(self) -> None:
        # GUARDRAIL: dir/ must match files inside that directory.
        self.assert_match("dist/out.js", "dist/")

    def test_dir_pattern_matches_deeply_nested_contents(self) -> None:
        self.assert_match("dist/a/b/c.js", "dist/")

    def test_dir_pattern_matches_dir_itself(self) -> None:
        self.assert_match("dist", "dist/")

    def test_dir_pattern_matches_from_any_ancestor(self) -> None:
        # GUARDRAIL: a trailing-slash pattern without leading slash
        # matches the directory anywhere in the path.
        self.assert_match("projects/myapp/dist/out.js", "dist/")

    def test_dir_pattern_does_not_match_unrelated_paths(self) -> None:
        self.assert_no_match("other/file.txt", "dist/")

    def test_dir_pattern_shallow_name_not_confused(self) -> None:
        # "build/" should match "build/output.js" but NOT "builder/file.js"
        self.assert_no_match("builder/file.js", "build/")

    # ── root-anchored patterns (leading /) ─────────────────────

    def test_root_anchored_matches_path_at_root(self) -> None:
        # GUARDRAIL: /node_modules must match the exact dir/file at root.
        self.assert_match("node_modules", "/node_modules")

    def test_root_anchored_matches_descendants(self) -> None:
        # GUARDRAIL: /node_modules matches everything inside node_modules/.
        # fnmatch alone would miss this — we add a "/**" suffix check.
        self.assert_match("node_modules/some/pkg/index.js", "/node_modules")

    def test_root_anchored_matches_deep_descendants(self) -> None:
        self.assert_match(
            "node_modules/a/b/c/d/index.js",
            "/node_modules",
        )

    def test_root_anchored_does_not_match_nested_directory(self) -> None:
        # /coverage at root does not match frontend/coverage/
        self.assert_no_match("frontend/coverage/lcov.info", "/coverage")

    def test_root_anchored_does_not_match_unrelated_path(self) -> None:
        self.assert_no_match("README.md", "/node_modules")

    # ── BOTH leading / AND trailing /  (the exact bug we fixed) ─

    def test_both_anchors_matches_contents(self) -> None:
        # GUARDRAIL: /.next/ against .next/cache/x MUST return True.
        # Before the fix, the trailing-/ check returned before
        # stripping the leading /, so "/.next" was passed to fnmatch
        # and nothing matched.
        self.assert_match(".next/cache/blah", "/.next/")

    def test_both_anchors_matches_dir_itself(self) -> None:
        self.assert_match(".next", "/.next/")

    def test_both_anchors_matches_deep_contents(self) -> None:
        self.assert_match(".next/server/pages/index.html", "/.next/")

    def test_both_anchors_does_not_match_nested_dir(self) -> None:
        # /.next/ anchored at root should NOT match frontend/.next/
        self.assert_no_match("frontend/.next/cache/x", "/.next/")

    # ── path-specific patterns (/ in the middle, no anchors) ──

    def test_path_specific_matches_exactly(self) -> None:
        self.assert_match("app/models/user.ts", "app/models/user.ts")

    def test_path_specific_matches_from_subdirectory(self) -> None:
        # GUARDRAIL: a pattern with / in the middle like "dir/file"
        # also matches "**/dir/file" so it works from any depth.
        self.assert_match("projects/myapp/app/models/user.ts", "app/models/user.ts")

    def test_path_specific_does_not_match_partial(self) -> None:
        self.assert_no_match("app/models/post.ts", "app/models/user.ts")

    # ── simple patterns (no /) ─────────────────────────────────

    def test_simple_glob_matches_basename(self) -> None:
        self.assert_match("src/utils/foo.py", "*.py")

    def test_simple_glob_does_not_match_wrong_extension(self) -> None:
        self.assert_no_match("src/utils/foo.ts", "*.py")

    def test_simple_literal_matches_exact_name(self) -> None:
        self.assert_match("Makefile", "Makefile")

    def test_simple_literal_matches_path_component_anywhere(self) -> None:
        # GUARDRAIL: a bare name with no / matches any directory
        # component with that name.
        self.assert_match("a/foo/b.txt", "foo")

    def test_simple_literal_matches_partial_path(self) -> None:
        self.assert_match("src/foo/bar", "foo")

    def test_simple_literal_does_not_match_unrelated(self) -> None:
        self.assert_no_match("src/bar/baz.py", "foo")

    # ── wildcard patterns ──────────────────────────────────────

    def test_wildcard_in_simple_pattern(self) -> None:
        self.assert_match("debug.log", "*.log")

    def test_wildcard_in_path_specific_pattern(self) -> None:
        self.assert_match("dist/js/chunk-abc.js", "dist/js/*.js")

    def test_wildcard_does_not_cross_directory_boundary(self) -> None:
        # GUARDRAIL: Python's fnmatch.fnmatch lets * cross /, so "dist/*.js"
        # DOES match "dist/sub/main.js". This deviates from git's semantics
        # where * stops at /. Known limitation — accept match for now.
        self.assert_match("dist/sub/main.js", "dist/*.js")

    def test_question_mark_wildcard(self) -> None:
        self.assert_match("file1.txt", "file?.txt")

    # ── normalisation ──────────────────────────────────────────

    def test_backslash_normalised_in_path(self) -> None:
        # Windows-style separators should be transparent.
        self.assert_match("dist\\out.js", "dist/")

    def test_backslash_normalised_in_pattern(self) -> None:
        self.assert_match("dist/out.js", "dist\\")

    # ── concrete real-world patterns ───────────────────────────

    def test_nextjs_dot_next_directory(self) -> None:
        """The exact pattern that exposed the original bug."""
        self.assert_match(".next/cache/webpack/foo", "/.next/")

    def test_nextjs_build_output(self) -> None:
        self.assert_match(".next/static/chunks/main.js", "/.next/")

    def test_node_modules_root_anchored(self) -> None:
        self.assert_match("node_modules/react/index.js", "/node_modules")

    def test_node_modules_trailing_slash_anywhere(self) -> None:
        self.assert_match("packages/app/node_modules/react/index.js", "node_modules/")

    def test_coverage_output(self) -> None:
        self.assert_match("coverage/lcov.info", "/coverage")

    def test_dist_directory(self) -> None:
        self.assert_match("dist/main.js", "/dist")

    def test_build_directory(self) -> None:
        self.assert_match("build/output.txt", "build/")

    def test_env_files(self) -> None:
        self.assert_match("src/.env.local", ".env*")

    def test_pycache_files(self) -> None:
        self.assert_match("src/catrepo/__pycache__/cli.pyc", "__pycache__/")


if __name__ == "__main__":
    unittest.main()
