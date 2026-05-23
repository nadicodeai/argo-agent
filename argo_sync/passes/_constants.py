"""argo_sync.passes._constants — shared constants for the rename passes.

This module is private to the ``argo_sync.passes`` package.  Nothing outside
of ``argo_sync/passes/`` should import from here.
"""

from __future__ import annotations

#: Directory names (bare basenames) that are always excluded from all rename
#: passes.  Any directory *or* any descendant of a directory with one of
#: these names is left untouched.
SKIP_DIRS: frozenset[str] = frozenset(
    {".git", ".venv", ".argo", "__pycache__", "node_modules"}
)


def apply_mappings(name: str, mappings: tuple[tuple[str, str], ...]) -> str:
    """Apply *mappings* in longest-first order to *name* and return the result.

    Each mapping is a ``(from_str, to_str)`` pair.  Mappings are applied
    sequentially using :meth:`str.replace`.  Because mappings are sorted
    longest-``from``-first by :class:`~argo_sync.config.RenameConfig`, longer
    tokens shadow shorter overlapping ones.

    Parameters
    ----------
    name:
        The string (file basename or directory basename) to transform.
    mappings:
        Ordered sequence of ``(from_str, to_str)`` pairs, longest-first.

    Returns
    -------
    str
        Transformed name.  Equal to *name* if no mapping matched.
    """
    result = name
    for from_str, to_str in mappings:
        result = result.replace(from_str, to_str)
    return result
