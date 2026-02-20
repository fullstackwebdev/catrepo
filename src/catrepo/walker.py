"""Collects file paths and metadata."""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from .utils import is_binary_path

DEFAULT_MAX_SIZE = 1_048_576


@dataclass
class FileInfo:
    """Metadata about a file in the repository."""

    path: Path
    size: int
    mtime: float


def _load_gitignore_patterns(root: Path) -> List[str]:
    """Load patterns from .gitignore file if it exists.
    
    Returns a list of glob patterns to exclude.
    """
    gitignore_path = root / ".gitignore"
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
    
    # Handle directory patterns (ending with /)
    is_dir_pattern = pattern.endswith("/")
    if is_dir_pattern:
        pattern = pattern.rstrip("/")
        # For directory patterns, match the directory itself or anything inside
        if fnmatch.fnmatch(rel_path, pattern):
            return True
        if fnmatch.fnmatch(rel_path, f"{pattern}/**"):
            return True
        if fnmatch.fnmatch(rel_path, f"*/{pattern}"):
            return True
        if fnmatch.fnmatch(rel_path, f"*/{pattern}/**"):
            return True
        return False
    
    # Handle patterns starting with /
    if pattern.startswith("/"):
        pattern = pattern[1:]
        # Match from root only
        return fnmatch.fnmatch(rel_path, pattern)
    
    # Handle patterns with / in the middle (path-specific)
    if "/" in pattern:
        if fnmatch.fnmatch(rel_path, pattern):
            return True
        if fnmatch.fnmatch(rel_path, f"**/{pattern}"):
            return True
        return False
    
    # Simple pattern - match basename or any path component
    basename = os.path.basename(rel_path)
    if fnmatch.fnmatch(basename, pattern):
        return True
    # Also check if any parent directory matches
    parts = rel_path.split("/")
    for i, part in enumerate(parts):
        if fnmatch.fnmatch(part, pattern):
            return True
        # Check partial paths
        partial = "/".join(parts[:i+1])
        if fnmatch.fnmatch(partial, pattern):
            return True
    
    return False


def _should_exclude_by_gitignore(rel_path: str, patterns: List[str]) -> bool:
    """Check if a path should be excluded based on gitignore patterns."""
    for pattern in patterns:
        if _matches_gitignore_pattern(rel_path, pattern):
            return True
    return False


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
    use_gitignore: bool = True,
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
    use_gitignore:
        Respect .gitignore patterns (default: True).
    """
    include = list(include or ["*"])
    exclude = list(exclude or [])
    files: List[FileInfo] = []
    root = Path(root_path)

    # Load .gitignore patterns if enabled
    gitignore_patterns: List[str] = []
    if use_gitignore:
        gitignore_patterns = _load_gitignore_patterns(root)

    def _expand(pattern: str) -> str:
        # normalize platform separators and remove leading ./
        pat = pattern.replace("\\", "/").lstrip("./").rstrip("/")
        if pat in {"*", "**"}:
            return pat
        if (root / pat).is_dir():
            return f"{pat}/**"  # recurse
        return pat

    include = [_expand(p) for p in include]
    exclude = [_expand(p) for p in exclude]

    # Always exclude .git directory unless explicitly included
    git_included = any(pat.lstrip("./").startswith(".git") for pat in include)
    if not git_included:
        exclude.append(".git/**")
        exclude.append(".git")

    for file in root.rglob("*"):
        try:
            rel = file.relative_to(root)
            rel_path = str(rel).replace("\\", "/")
            if not file.is_file():
                continue
            
            # Check include patterns
            if not any(fnmatch.fnmatch(rel_path, pattern) for pattern in include):
                continue
            
            # Check explicit exclude patterns using improved matching
            if any(_matches_exclude_pattern(rel_path, pattern) for pattern in exclude):
                continue
            
            # Check gitignore patterns
            if use_gitignore and _should_exclude_by_gitignore(rel_path, gitignore_patterns):
                continue
            
            if is_binary_path(file, strict=binary_strict):
                continue
            stat = file.stat()
            if not os.access(file, os.R_OK):
                continue
            if stat.st_size > max_size:
                continue
            files.append(FileInfo(path=rel, size=stat.st_size, mtime=stat.st_mtime))
        except OSError:
            continue
    return files
