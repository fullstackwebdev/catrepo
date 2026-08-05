"""Unit tests for the pattern-aware pareto filter.

The filter was originally size-only and default-on, which amputated real
source files (click's core.py is ~78× the median token count). These tests
pin the new contract:
  1. multiplier <= 0  → filter disabled entirely
  2. only generated/noise files (lockfiles, changelogs, minified, .csv/.tsv)
     are eligible — real source over the threshold is KEPT
  3. noise files under the threshold are KEPT
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Ensure the src package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from catrepo.renderer import Dump, FileDump
from catrepo.walker import FileInfo


def _make_fd(path: str, tokens: int) -> FileDump:
    """Build a FileDump without touching the filesystem (tokens set manually)."""
    fd = object.__new__(FileDump)
    fd.path = Path(path)
    fd.full_path = Path(".") / fd.path
    fd.size = tokens * 4
    fd.mtime = 1.0
    fd.tokens = tokens
    fd.content = ""
    return fd


def _filter(files_tokens, multiplier: float) -> list:
    """Run _filter_outliers over (path, tokens) pairs, return surviving paths."""
    d = object.__new__(Dump)
    d.file_dumps = [_make_fd(p, t) for p, t in files_tokens]
    d.total_tokens = sum(fd.tokens for fd in d.file_dumps)
    d._filter_outliers(multiplier)
    return [fd.path.as_posix() for fd in d.file_dumps]


# tokens chosen so the many small files keep median low (~120) → threshold 20× = ~2400
FIXTURE = [
    ("uv.lock", 100_000),            # noise lockfile, WAY over threshold
    ("src/click/core.py", 40_000),   # real source, over threshold — must survive
    ("bundle.min.js", 50_000),       # minified, over threshold
    ("data.csv", 7_000),             # data dump, over threshold
    ("package-lock.json", 100),      # noise, UNDER threshold — must survive
    ("a.py", 100), ("b.py", 200), ("c.py", 300),   # source, tiny
    ("d.py", 50), ("e.py", 80), ("f.py", 120),      # source, tiny
    ("g.py", 90), ("h.py", 60),                     # source, tiny
]
# median of the 13 values = 120; 20× = 2400; 2× = 240


class TestParetoFilter(unittest.TestCase):
    def test_disabled_when_multiplier_zero(self) -> None:
        # GUARDRAIL: 0 must mean "off" — the old default-on filter had no off switch.
        surviving = _filter(FIXTURE, 0.0)
        self.assertEqual(sorted(surviving), sorted(p for p, _ in FIXTURE))

    def test_disabled_when_multiplier_negative(self) -> None:
        surviving = _filter(FIXTURE, -5.0)
        self.assertEqual(sorted(surviving), sorted(p for p, _ in FIXTURE))

    def test_noise_over_threshold_removed(self) -> None:
        surviving = _filter(FIXTURE, 20.0)
        self.assertNotIn("uv.lock", surviving)
        self.assertNotIn("bundle.min.js", surviving)
        self.assertNotIn("data.csv", surviving)

    def test_real_source_over_threshold_kept(self) -> None:
        # GUARDRAIL: core.py is 40K tokens vs 6K threshold — the size-only filter
        # dropped it; the pattern-aware filter must keep it.
        surviving = _filter(FIXTURE, 20.0)
        self.assertIn("src/click/core.py", surviving)

    def test_noise_under_threshold_kept(self) -> None:
        surviving = _filter(FIXTURE, 20.0)
        self.assertIn("package-lock.json", surviving)

    def test_small_source_always_kept(self) -> None:
        surviving = _filter(FIXTURE, 20.0)
        for p, _ in FIXTURE:
            if p in ("a.py", "b.py", "c.py"):
                self.assertIn(p, surviving)

    def test_all_noise_removed_with_aggressive_multiplier(self) -> None:
        # 2× median → threshold 600; only package-lock.json (100) survives of noise
        surviving = _filter(FIXTURE, 2.0)
        self.assertNotIn("uv.lock", surviving)
        self.assertNotIn("data.csv", surviving)
        self.assertIn("package-lock.json", surviving)
        self.assertIn("src/click/core.py", surviving)


if __name__ == "__main__":
    unittest.main()
