"""Catrepo package - Flatten a repository into one text dump."""

from .api import dump_repo

# GUARDRAIL: single source of truth for the version — pyproject.toml reads it via
# [tool.setuptools.dynamic] (static AST, no import needed at build time).
# Bump HERE only; the installed package reports it via importlib.metadata.
__version__ = "1.0.1"

# GUARDRAIL: __all__ used to list submodule names ("cli", "loader", ...) that were
# never imported by this package — `from catrepo import *` raised AttributeError.
# dump_repo is the only real top-level export; submodules are imported explicitly.
__all__ = ["dump_repo"]
