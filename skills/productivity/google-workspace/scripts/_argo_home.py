"""Resolve ARGO_HOME for standalone skill scripts.

Skill scripts may run outside the Argo process (e.g. system Python,
nix env, CI) where ``argo_constants`` is not importable.  This module
provides the same ``get_argo_home()`` and ``display_argo_home()``
contracts as ``argo_constants`` without requiring it on ``sys.path``.

When ``argo_constants`` IS available it is used directly so that any
future enhancements (profile resolution, Docker detection, etc.) are
picked up automatically.  The fallback path replicates the core logic
from ``argo_constants.py`` using only the stdlib.

All scripts under ``google-workspace/scripts/`` should import from here
instead of duplicating the ``ARGO_HOME = Path(os.getenv(...))`` pattern.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from argo_constants import display_argo_home as display_argo_home
    from argo_constants import get_argo_home as get_argo_home
except (ModuleNotFoundError, ImportError):

    def get_argo_home() -> Path:
        """Return the Argo home directory (default: ~/.argo).

        Mirrors ``argo_constants.get_argo_home()``."""
        val = os.environ.get("ARGO_HOME", "").strip()
        return Path(val) if val else Path.home() / ".argo"

    def display_argo_home() -> str:
        """Return a user-friendly ``~/``-shortened display string.

        Mirrors ``argo_constants.display_argo_home()``."""
        home = get_argo_home()
        try:
            return "~/" + str(home.relative_to(Path.home()))
        except ValueError:
            return str(home)
