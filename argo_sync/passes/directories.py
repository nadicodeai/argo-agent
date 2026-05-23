"""argo_sync.passes.directories — directory-rename pass.

Walk the source tree **bottom-up** (deepest directories first) so that renaming
a child never invalidates a queued parent path.  For each directory whose
basename contains a mapping ``from`` key:

1. Skip if the repo-relative path matches any exception glob
   (:meth:`~argo_sync.config.RenameConfig.matches_exception`).
2. Skip if the directory name is in :data:`_HARD_SKIP_DIRS` (these names are
   never renamed regardless of mappings: ``.git``, ``.venv``, ``.argo``,
   ``__pycache__``, ``node_modules``).
3. Skip symlinks — renaming a symlink rather than its target would silently
   alter the link's meaning.  Real target directories are handled via their
   own traversal entries.
4. Compute the new name by applying each mapping in order (longest-``from``
   first, already guaranteed by :class:`~argo_sync.config.RenameConfig`).
5. If the target path already exists, raise
   :class:`~argo_sync.errors.RenameConflictError`.  No merging, no overwriting.
6. Otherwise rename atomically via :meth:`pathlib.Path.rename`.

Returns a :class:`list` of the **new** paths for every directory that was
renamed, in the order they were processed (bottom-up).

This pass is designed to run **after** ``ContentPass`` (T2.2) and
``FilenamePass`` (T2.3).  The orchestrator (T2.6) enforces that order.
"""

from __future__ import annotations

from pathlib import Path

from argo_sync.config import RenameConfig
from argo_sync.errors import RenameConflictError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Directory names that are **never** renamed regardless of mappings.
#: These are tool-internal directories whose names must remain stable.
_HARD_SKIP_DIRS: frozenset[str] = frozenset(
    {".git", ".venv", ".argo", "__pycache__", "node_modules"}
)


# ---------------------------------------------------------------------------
# Pass implementation
# ---------------------------------------------------------------------------


class DirectoryPass:
    """Rename directories in a source tree bottom-up.

    Parameters
    ----------
    config:
        Loaded, validated :class:`~argo_sync.config.RenameConfig`.  Mappings
        are already sorted longest-``from``-first by the loader.
    """

    def __init__(self, config: RenameConfig) -> None:
        self.config = config

    def run(self, root: Path) -> list[Path]:
        """Rename directories (not files). Returns new paths of renamed dirs.

        Parameters
        ----------
        root:
            Absolute path to the root of the source tree to process.

        Returns
        -------
        list[Path]
            New (post-rename) absolute paths for every directory that was
            renamed, in bottom-up processing order.

        Raises
        ------
        RenameConflictError
            If the computed target path already exists.
        """
        renamed: list[Path] = []

        # Collect all descendant directories (not root itself), then sort
        # bottom-up: deeper paths (more separators) come first.
        all_dirs = [p for p in root.rglob("*") if p.is_dir() and not p.is_symlink()]
        all_dirs.sort(key=lambda p: len(p.parts), reverse=True)

        for directory in all_dirs:
            basename = directory.name

            # --- Hard-coded skip set ---
            if basename in _HARD_SKIP_DIRS:
                continue

            # --- Exception glob check ---
            try:
                rel = directory.relative_to(root).as_posix()
            except ValueError:
                # Should not happen for descendants, but guard anyway.
                continue

            if self.config.matches_exception(rel):
                continue

            # --- Check whether any mapping applies ---
            new_name = _apply_mappings(basename, self.config.mappings)
            if new_name == basename:
                # No mapping matched this directory's name.
                continue

            source = directory
            target = directory.parent / new_name

            if target.exists():
                raise RenameConflictError(source, target)

            source.rename(target)
            renamed.append(target)

        return renamed


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _apply_mappings(name: str, mappings: tuple[tuple[str, str], ...]) -> str:
    """Apply mappings in order (longest-first) and return the result.

    Each mapping is a ``(from, to)`` pair.  Mappings are applied sequentially:
    the output of one mapping is the input to the next.  Because mappings are
    sorted longest-``from``-first by :class:`~argo_sync.config.RenameConfig`,
    longer tokens shadow shorter overlapping ones when applied.

    Parameters
    ----------
    name:
        The directory basename to transform.
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
