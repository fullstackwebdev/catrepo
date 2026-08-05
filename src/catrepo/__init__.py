"""Catrepo package - Flatten a repository into one text dump."""

from .api import dump_repo

# GUARDRAIL: __all__ used to list "cli" — never imported by this package, so
# `from catrepo import *` would raise AttributeError on it. Removed; dump_repo is
# the only real top-level export, the rest are reachable as catrepo.<module>.
__all__ = [
    "loader",
    "renderer",
    "tokenizer",
    "walker",
    "downloader",
    "dump_repo",
]
