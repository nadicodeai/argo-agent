"""RenameEngine — orchestrates the ordered rename pipeline.

Pass order is mandated by FR-2 and spec § "Resolved Decisions":

  1. ContentPass  — rewrite tokens *inside* files in-place.
  2. FilenamePass — rename file basenames (bottom-up within each directory).
  3. DirectoryPass — rename directory basenames (bottom-up, deepest first).

Running content before filenames prevents a filename rename from
invalidating the path that ContentPass is about to walk.  Running
filenames before directories prevents a directory rename from
invalidating the file paths that FilenamePass still needs to visit.

Return type
-----------
:meth:`apply` returns ``list[Path]``.  Every element is an **absolute**
:class:`~pathlib.Path` so callers can pass the list directly to
:class:`~argo_sync.manifest.ManifestWriter` without any path arithmetic.
The list is sorted and deduplicated (a path cannot appear in more than one
pass result because each pass operates on a different dimension: content vs
filename vs directory name).
"""

from __future__ import annotations

from pathlib import Path

from .config import RenameConfig
from .manifest import ManifestWriter, SyncManifest
from .passes.content import ContentPass
from .passes.directories import DirectoryPass
from .passes.filenames import FilenamePass


class RenameEngine:
    """Orchestrates the ordered rename passes over a source tree.

    Parameters
    ----------
    config:
        Loaded, validated :class:`~argo_sync.config.RenameConfig`.
    """

    def __init__(self, config: RenameConfig) -> None:
        self.config = config

    def apply(self, root: Path) -> list[Path]:
        """Run content → filenames → directories; return all touched paths.

        Executes the three rename passes in the order that preserves
        correctness (FR-2):

        1. :class:`~argo_sync.passes.content.ContentPass` — rewrites tokens
           inside file contents and returns the absolute paths of files whose
           on-disk bytes changed.
        2. :class:`~argo_sync.passes.filenames.FilenamePass` — renames file
           basenames and returns the new absolute paths of renamed files.
        3. :class:`~argo_sync.passes.directories.DirectoryPass` — renames
           directory basenames (deepest first) and returns the new absolute
           paths of renamed directories.

        The three result sets are unioned, sorted, and deduplicated before
        being returned.  Sorting uses the natural ``Path`` ordering (which
        on all platforms is lexicographic on the string representation).

        Parameters
        ----------
        root:
            Absolute path to the root of the source tree.  Must exist.

        Returns
        -------
        list[Path]
            Sorted, deduplicated list of absolute :class:`~pathlib.Path`
            objects representing every file or directory whose content or
            name changed.  An empty list means the tree was already fully
            renamed (idempotency, AC-3).

        Raises
        ------
        argo_sync.errors.RenameConflictError
            Re-raised from :class:`~argo_sync.passes.filenames.FilenamePass`
            or :class:`~argo_sync.passes.directories.DirectoryPass` if a
            rename target already exists.
        argo_sync.errors.ConfigError
            Should not occur here (config is validated at load time), but
            propagates if the config object is somehow invalid.
        """
        # Pass 1 — content rewrite (returns absolute paths of changed files).
        content_touched: set[Path] = set(ContentPass(self.config).run(root))

        # Pass 2 — filename rename (returns new absolute paths of renamed files).
        filename_touched: set[Path] = set(FilenamePass(self.config).run(root))

        # Pass 3 — directory rename (returns new absolute paths of renamed dirs).
        directory_touched: set[Path] = set(DirectoryPass(self.config).run(root))

        # Union all three sets, then sort and deduplicate.
        all_touched: set[Path] = content_touched | filename_touched | directory_touched
        return sorted(all_touched)

    def apply_and_write_manifest(
        self,
        root: Path,
        *,
        upstream_sha: str,
        now: str | None = None,
    ) -> Path:
        """Run :meth:`apply` and persist the result as a sync manifest.

        Convenience method that combines the rename pass with manifest
        writing so callers in ``bin/argo-sync`` can do this in one call.

        Parameters
        ----------
        root:
            Absolute path to the root of the source tree.
        upstream_sha:
            Full upstream commit SHA to embed in the manifest.
        now:
            Optional ISO-8601 timestamp string.  When supplied, the manifest's
            ``ran_at`` field is set to this value exactly (useful for
            deterministic tests).  When omitted, the current UTC time is used.

        Returns
        -------
        Path
            Absolute path of the written manifest file
            (``<root>/.argo/sync-manifest.json``).
        """
        files_touched = self.apply(root)

        manifest = SyncManifest(
            upstream_sha=upstream_sha,
            files_touched=tuple(files_touched),
        )

        return ManifestWriter(root).write(manifest, now=now)
