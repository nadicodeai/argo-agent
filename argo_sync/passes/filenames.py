"""argo_sync.passes.filenames — filename-rename pass (T2.3).

Walks the tree under ``root`` **bottom-up** (children before parents) and
renames the *basename* of every regular file whose name contains at least one
mapping ``from`` key.

Traversal strategy
------------------
``Path.rglob("*")`` is *not* used because it does not guarantee bottom-up
order.  Instead we collect every path under ``root`` with ``os.walk`` using
``topdown=False``, which yields directories leaf-first.  For each directory
yielded we process its files (regular files only, not symlinks, not dirs)
before moving on to the parent directory.  This invariant ensures that if T2.4
(the directory-rename pass) runs after us, it never encounters a child whose
new path was already invalidated by a parent rename.

Symlink policy
--------------
Symlinks are **skipped**.  Renaming the symlink itself moves the pointer, not
the target; this is almost never what a rename engine wants.  The policy is
documented and tested (test 10 in ``tests/test_filename_pass.py``).

Mapping application
-------------------
Mappings are already sorted longest-``from``-first by :class:`~argo_sync.config.RenameConfig`.
We apply them in that order using :func:`str.replace` on the basename.  Because
``str.replace`` replaces ALL non-overlapping occurrences left-to-right in a
single scan, a shorter key that overlaps with a longer key that was already
replaced will naturally find no match (the longer key's region has changed),
preventing double-application.

Skip list
---------
The following directory names (as any path component under ``root``) are
unconditionally skipped, regardless of the exception globs:

* ``.git``
* ``.venv``
* ``.argo``
* ``__pycache__``
* ``node_modules``

Exception globs from ``config.exceptions`` are also checked against the
repo-relative POSIX path (forward slashes) of each candidate file.
"""

from __future__ import annotations

import os
from pathlib import Path

from argo_sync.config import RenameConfig
from argo_sync.errors import RenameConflictError
from argo_sync.passes._constants import SKIP_DIRS as _ALWAYS_SKIP, apply_mappings


class FilenamePass:
    """Rename files (not directories) whose basename matches a mapping key.

    Parameters
    ----------
    config:
        Loaded, validated :class:`~argo_sync.config.RenameConfig`.  Mappings
        must already be sorted longest-``from``-first (the loader guarantees
        this).
    """

    def __init__(self, config: RenameConfig) -> None:
        self.config = config

    def run(self, root: Path) -> list[Path]:
        """Rename files (not directories). Returns new paths of renamed files.

        Parameters
        ----------
        root:
            Root of the tree to walk.  Must be an existing directory.

        Returns
        -------
        list[Path]
            New absolute paths of every file that was renamed.  Files that
            required no rename are absent from the list.

        Raises
        ------
        RenameConflictError
            If a computed target path already exists (would clobber a file).
        """
        renamed: list[Path] = []

        # os.walk with topdown=False gives us bottom-up traversal.
        for dirpath_str, dirnames, filenames in os.walk(root, topdown=False):
            dirpath = Path(dirpath_str)

            # Compute the path of this directory relative to root for skip checks.
            try:
                rel_dir = dirpath.relative_to(root)
            except ValueError:
                # Should never happen during a normal walk, but be safe.
                continue

            # Skip if any component of the current directory path is in
            # _ALWAYS_SKIP.  rel_dir.parts includes every ancestor segment
            # between root and dirpath, so this correctly filters out both the
            # skip directory itself and any descendant.
            # Note: with topdown=False children are already visited before their
            # parent, so we cannot prune the walk here — we simply skip
            # processing this directory's files.
            if any(part in _ALWAYS_SKIP for part in rel_dir.parts):
                continue

            # Process each filename in this directory.
            for filename in filenames:
                current_path = dirpath / filename

                # Skip symlinks — see module docstring for rationale.
                if current_path.is_symlink():
                    continue

                # Skip non-regular files (devices, FIFOs, …).
                if not current_path.is_file():
                    continue

                # Compute repo-relative POSIX path for exception matching.
                try:
                    rel_file = current_path.relative_to(root)
                except ValueError:
                    continue
                rel_posix = rel_file.as_posix()

                # Check exception globs.
                if self.config.matches_exception(rel_posix):
                    continue

                # Apply mappings to the basename only.
                new_name = apply_mappings(filename, self.config.mappings)
                if new_name == filename:
                    # No mapping fired — leave the file alone.
                    continue

                target_path = dirpath / new_name

                # Collision check — do NOT overwrite.
                if target_path.exists():
                    raise RenameConflictError(
                        source=current_path,
                        target=target_path,
                    )

                # Atomic rename (same filesystem guaranteed within a worktree).
                current_path.rename(target_path)
                renamed.append(target_path)

        return renamed

