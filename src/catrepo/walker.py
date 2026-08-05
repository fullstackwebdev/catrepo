"""Collects file paths and metadata."""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, Iterator, List

from .utils import is_binary_path

DEFAULT_MAX_SIZE = 1_048_576


@dataclass
class FileInfo:
    """Metadata about a file in the repository."""

    path: Path
    size: int
    mtime: float


def _load_gitignore_patterns(directory: Path) -> List[str]:
    """Load patterns from a directory's .gitignore file if it exists.
    
    Returns a list of glob patterns to exclude.
    """
    gitignore_path = directory / ".gitignore"
    if not gitignore_path.exists():
        return []
    
    patterns = []
    try:
        with open(gitignore_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments
                if not line or line.startswith("#"):
                    continue
                # Handle negation patterns (skip them for exclusion)
                if line.startswith("!"):
                    continue
                patterns.append(line)
    except OSError:
        pass
    return patterns


def _matches_gitignore_pattern(rel_path: str, pattern: str) -> bool:
    """Check if a relative path matches a gitignore pattern."""
    # Normalize separators
    rel_path = rel_path.replace("\\", "/")
    pattern = pattern.replace("\\", "/")
    
    # GUARDRAIL: pattern can have BOTH a leading / (root-anchored) AND trailing / (directory).
    # The trailing-/ check must not return before stripping the leading / — e.g. "/.next/"
    # must become ".next" before matching. Extract both markers first, then match.
    is_dir_pattern = pattern.endswith("/")
    if is_dir_pattern:
        pattern = pattern.rstrip("/")
    is_root_anchored = pattern.startswith("/")
    if is_root_anchored:
        pattern = pattern[1:]
    
    if is_dir_pattern:
        # Directory pattern — match the directory itself or anything inside it
        if fnmatch.fnmatch(rel_path, pattern):
            return True
        if fnmatch.fnmatch(rel_path, f"{pattern}/**"):
            return True
        if not is_root_anchored:
            # GUARDRAIL: */{pattern} and */{pattern}/** only apply to non-anchored
            # directory patterns. If the pattern is root-anchored (e.g. /.next/),
            # the directory must be at the root — don't let */ defeat anchoring.
            if fnmatch.fnmatch(rel_path, f"*/{pattern}"):
                return True
            if fnmatch.fnmatch(rel_path, f"*/{pattern}/**"):
                return True
        return False
    
    if is_root_anchored:
        # Pattern anchored to root — match from start only.
        # GUARDRAIL: in git, /node_modules matches node_modules/ AND everything inside it.
        # fnmatch alone only matches the exact path, not descendants.
        if fnmatch.fnmatch(rel_path, pattern):
            return True
        if fnmatch.fnmatch(rel_path, f"{pattern}/**"):
            return True
        return False
    
    # Handle patterns with / in the middle (path-specific)
    if "/" in pattern:
        if fnmatch.fnmatch(rel_path, pattern):
            return True
        if fnmatch.fnmatch(rel_path, f"**/{pattern}"):
            return True
        return False
    
    # Simple pattern - match any path component (basename included).
    # GUARDRAIL: the old code had 3 redundant checks (basename, per-part loop,
    # partial-path join). The loop covers basename (it's the last part), and a
    # "/"-less pattern can never fnmatch a "/"-joined prefix — dead logic removed;
    # the 39 gitignore tests pin the behavior.
    parts = rel_path.split("/")
    for part in parts:
        if fnmatch.fnmatch(part, pattern):
            return True

    return False


def _should_exclude_by_gitignore(rel_path: str, patterns: List[str]) -> bool:
    """Check if a path should be excluded based on gitignore patterns."""
    for pattern in patterns:
        if _matches_gitignore_pattern(rel_path, pattern):
            return True
    return False


def _load_nested_gitignore_patterns(
    root: Path,
    exclude_patterns: List[str],
) -> Dict[str, List[str]]:
    """Load .gitignore patterns from root and all subdirectories.
    
    Returns dict mapping relative directory path → list of patterns.
    Root patterns are keyed by ".".
    """
    # GUARDRAIL: gitignores are hierarchical — a nested .gitignore in frontend/.gitignore
    # often excludes e.g. .next/, dist/ that the root .gitignore doesn't know about.
    # Walking only root .gitignore was the bug — always load every .gitignore in the tree.

    # GUARDRAIL: do NOT use root.rglob(".gitignore") here — rglob descends into every
    # directory (node_modules, .git, .venv) hunting for .gitignore files, re-creating
    # the exact 275K-stat problem _walksub pruning exists to avoid. Scan with os.scandir
    # and prune excluded subtrees while hunting.
    patterns_by_dir: Dict[str, List[str]] = {}

    def _scan(rel_dir: str) -> None:
        current = root / rel_dir if rel_dir else root
        patterns = _load_gitignore_patterns(current)
        if patterns:
            patterns_by_dir[rel_dir if rel_dir else "."] = patterns
        # A dir excluded by ancestor (or its own) patterns can never affect dumped
        # files, so it and everything below it can be skipped here too.
        if rel_dir and _should_prune_dir(rel_dir, patterns_by_dir, exclude_patterns):
            return
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        _scan(f"{rel_dir}/{entry.name}" if rel_dir else entry.name)
        except OSError:
            pass

    _scan("")
    return patterns_by_dir


def _should_exclude_by_nested_gitignore(rel_path: str, patterns_by_dir: Dict[str, List[str]]) -> bool:
    """Check if rel_path should be excluded by any parent directory's .gitignore.
    
    rel_path is relative to the repository root. For each parent directory
    that has a .gitignore, the file path relative to that directory is
    checked against that directory's patterns.
    """
    rel_path_normalized = rel_path.replace("\\", "/")
    
    # Check root .gitignore first
    if "." in patterns_by_dir and _should_exclude_by_gitignore(rel_path_normalized, patterns_by_dir["."]):
        return True
    
    # Check each parent directory's .gitignore
    parts = rel_path_normalized.split("/")
    for i in range(1, len(parts)):
        parent_dir = "/".join(parts[:i])
        if parent_dir in patterns_by_dir:
            # Path relative to the gitignore's directory
            path_in_dir = "/".join(parts[i:])
            if _should_exclude_by_gitignore(path_in_dir, patterns_by_dir[parent_dir]):
                return True
    
    return False


def _should_prune_dir(
    rel_dir_path: str,
    gitignore_patterns_by_dir: Dict[str, List[str]],
    exclude_patterns: List[str],
) -> bool:
    """Check if a directory should be skipped entirely (not recursed into).

    GUARDRAIL: rglob walks every file in node_modules even though gitignore
    excludes them — 275K wasted stat+match calls on sandagents. By checking
    directories BEFORE recursing, we skip entire subtrees in O(1) checks
    instead of O(n) per-file checks. Git does this; we must too.
    """
    # Check gitignore patterns — these are the big win
    if _should_exclude_by_nested_gitignore(rel_dir_path, gitignore_patterns_by_dir):
        return True
    # Check explicit exclude patterns
    for pattern in exclude_patterns:
        if _matches_exclude_pattern(rel_dir_path, pattern):
            return True
    return False


def _walksub(
    root: Path,
    rel_parent: str,
    gitignore_patterns_by_dir: Dict[str, List[str]],
    exclude_patterns: List[str],
) -> Iterator[Path]:
    """Recursively walk a directory, pruning gitignored/excluded subtrees.

    Yields relative file paths (as Path objects) lazily instead of building a
    full List[Path] — on 275K-file repos the intermediate list doubles peak
    memory for nothing.
    Uses os.scandir for fast iteration without stat per entry.
    """
    current_dir = root / rel_parent if rel_parent else root
    try:
        with os.scandir(current_dir) as entries:
            for entry in entries:
                rel_path = f"{rel_parent}/{entry.name}" if rel_parent else entry.name
                rel_path_n = rel_path.replace("\\", "/")
                if entry.is_dir(follow_symlinks=False):
                    if _should_prune_dir(rel_path_n, gitignore_patterns_by_dir, exclude_patterns):
                        continue
                    yield from _walksub(root, rel_path, gitignore_patterns_by_dir, exclude_patterns)
                elif entry.is_file(follow_symlinks=False):
                    yield Path(rel_path)
    except OSError:
        pass


def _matches_exclude_pattern(rel_path: str, pattern: str) -> bool:
    """Check if a relative path matches an exclude pattern.

    This handles directory names specially - if the pattern is a simple
    directory name (no wildcards, no slashes), it matches that directory
    name anywhere in the path.
    """
    import re
    # Normalize separators
    rel_path = rel_path.replace("\\", "/")
    pattern = pattern.replace("\\", "/")

    # Handle ** pattern (matches any path including multiple directories)
    if "**" in pattern:
        # Extract the base pattern (without **)
        base = pattern.replace("/**", "").replace("**/", "")
        
        # If base is a simple name (no slashes), match it anywhere in path
        if "/" not in base:
            parts = rel_path.split("/")
            for i, part in enumerate(parts):
                if fnmatch.fnmatch(part, base):
                    return True
            return False
        
        # Convert glob pattern to regex properly for complex patterns
        # First escape special regex chars except * and ?
        regex_pattern = re.escape(pattern)
        # Replace escaped ** with .* (matches anything including /)
        regex_pattern = regex_pattern.replace(r'\*\*', '.*')
        # Replace escaped * with [^/]* (matches anything except /)
        regex_pattern = regex_pattern.replace(r'\*', '[^/]*')
        # Replace escaped ? with .
        regex_pattern = regex_pattern.replace(r'\?', '.')
        regex_pattern = f"^{regex_pattern}$"
        try:
            if re.match(regex_pattern, rel_path):
                return True
        except re.error:
            pass
        return False

    # If pattern contains other wildcards or slashes, use fnmatch
    if "*" in pattern or "?" in pattern or "/" in pattern:
        return fnmatch.fnmatch(rel_path, pattern)

    # Simple directory/file name - check if it appears as a path component
    parts = rel_path.split("/")
    for part in parts:
        if fnmatch.fnmatch(part, pattern):
            return True

    return False


def collect_files(
    root_path: Path,
    include: Iterable[str] | None = None,
    exclude: Iterable[str] | None = None,
    max_size: int = DEFAULT_MAX_SIZE,
    *,
    binary_strict: bool = True,
) -> List[FileInfo]:
    """Return list of readable, non-binary files under *root_path*.

    Parameters
    ----------
    root_path:
        Directory to walk.
    include:
        Glob patterns to include.
    exclude:
        Glob patterns to exclude.
    max_size:
        Skip files larger than this number of bytes.
    binary_strict:
        Use strict binary detection.
    """
    include = list(include or ["*"])
    exclude = list(exclude or [])
    files: List[FileInfo] = []
    root = Path(root_path)

    def _expand(pattern: str) -> str:
        # normalize platform separators and strip only a "./" prefix
        # GUARDRAIL: str.lstrip("./") was a bug — it strips ALL leading dots and
        # slashes, so "--exclude .audit" became "audit" and silently never matched
        # (dot-directories were impossible to exclude). Strip an exact "./" prefix.
        pat = pattern.replace("\\", "/")
        if pat.startswith("./"):
            pat = pat[2:]
        pat = pat.rstrip("/")
        if pat in {"*", "**"}:
            return pat
        if (root / pat).is_dir():
            return f"{pat}/**"  # recurse
        return pat

    include = [_expand(p) for p in include]
    exclude = [_expand(p) for p in exclude]

    # Always exclude .git directory unless explicitly included
    git_included = any(pat.startswith(".git") for pat in include)
    if not git_included:
        exclude.append(".git/**")
        exclude.append(".git")

    # GUARDRAIL: .git patterns must be in exclude BEFORE the gitignore scan so the
    # scan can prune .git (and any other excluded subtree) instead of re-walking it.
    # Load all .gitignore patterns (root + nested) — always on; skipping leaks artifacts.
    gitignore_patterns_by_dir = _load_nested_gitignore_patterns(root, exclude)

    for file_rel in _walksub(root, "", gitignore_patterns_by_dir, exclude):
        try:
            file = root / file_rel
            rel_path = str(file_rel).replace("\\", "/")
            
            # Check include patterns
            if not any(fnmatch.fnmatch(rel_path, pattern) for pattern in include):
                continue
            
            # GUARDRAIL: directory pruning handles most gitignore/exclude hits,
            # but file-level patterns like *.log or *.pyc need a per-file check
            # since those patterns don't block directory traversal.
            if _should_exclude_by_nested_gitignore(rel_path, gitignore_patterns_by_dir):
                continue
            if any(_matches_exclude_pattern(rel_path, pattern) for pattern in exclude):
                continue
            
            if is_binary_path(file, strict=binary_strict):
                continue
            stat = file.stat()
            if not os.access(file, os.R_OK):
                continue
            if stat.st_size > max_size:
                continue
            files.append(FileInfo(path=file_rel, size=stat.st_size, mtime=stat.st_mtime))
        except OSError:
            continue
    return files
