"""Catrepo package - Flatten a repository into one text dump."""

from .api import dump_repo

# GUARDRAIL: __all__ used to list submodule names ("cli", "loader", ...) that were
# never imported by this package — `from catrepo import *` raised AttributeError.
# dump_repo is the only real top-level export; submodules are imported explicitly.
__all__ = ["dump_repo"]
