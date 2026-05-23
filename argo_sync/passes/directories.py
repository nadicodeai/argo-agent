"""argo_sync.passes.directories — directory-rename pass.

Walk the source tree **bottom-up** (deepest directories first) so that renaming
a child never invalidates a queued parent path.  For each directory whose
basename contains a mapping ``from`` key:

1. Skip if any component of the repo-relative path is in
   :data:`~argo_sync.passes._constants.SKIP_DIRS` — this prunes the directory
   itself *and* all descendants of skip dirs (e.g. ``.git/foo/`` is not
   renamed even though ``foo`` is not in the skip set).
2. Skip if the repo-relative path matches any exception glob
   (:meth:`~argo_sync.config.RenameConfig.matches_exception`).
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
from argo_sync.passes._constants import SKIP_DIRS, apply_mappings as _apply_mappings


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

            # --- Exception glob check (needs repo-relative path) ---
            try:
                rel = directory.relative_to(root)
            except ValueError:
                # Should not happen for descendants, but guard anyway.
                continue

            # --- Ancestor-based skip: skip this dir and ALL its descendants
            #     when any component of the repo-relative path is in SKIP_DIRS.
            #     This prevents renaming e.g. .git/foo_pkg/ when mapping foo→bar.
            if any(part in SKIP_DIRS for part in rel.parts):
                continue

            rel_posix = rel.as_posix()
            if self.config.matches_exception(rel_posix):
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
