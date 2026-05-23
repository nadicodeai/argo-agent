"""argo_sync.manifest — writes the per-sync manifest at .argo/sync-manifest.json.

Determinism guarantee
---------------------
The output is fully determined by (upstream_sha, files_touched, exceptions_used, now):

- ``files_touched`` is de-duplicated and sorted before serialisation so that
  differing insertion orders produce identical bytes.
- ``exceptions_used`` is sorted for the same reason.
- ``json.dumps(..., indent=2, sort_keys=True)`` produces a canonical key order
  regardless of dict insertion order (Python 3.7+ dicts are ordered, but we
  do not rely on that — ``sort_keys`` makes it explicit and stable).
- A trailing newline is always appended so the file is POSIX-compliant and
  ``diff`` output is clean.

Two calls with identical arguments (including the same ``now=`` override) will
always produce byte-identical files.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class SyncManifest:
    """Immutable value object describing the result of a single sync run.

    Parameters
    ----------
    upstream_sha:
        Full upstream commit SHA.
    files_touched:
        Paths of every file modified during the sync (may be in any order;
        duplicates are accepted and deduplicated on write).
    exceptions_used:
        ``path`` strings from the rename config that matched at least one file.
        Defaults to an empty tuple when the caller has no matched exceptions.
    """

    upstream_sha: str
    files_touched: tuple[Path, ...]
    exceptions_used: tuple[str, ...] = field(default=())


class ManifestWriter:
    """Writes :class:`SyncManifest` instances to ``<repo_root>/.argo/sync-manifest.json``.

    Parameters
    ----------
    repo_root:
        Absolute path to the repository root.  The ``.argo/`` sub-directory
        is created automatically if it does not yet exist.
    """

    _MANIFEST_RELPATH = Path(".argo") / "sync-manifest.json"

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    def write(self, manifest: SyncManifest, *, now: str | None = None) -> Path:
        """Serialise *manifest* and write it to ``.argo/sync-manifest.json``.

        Parameters
        ----------
        manifest:
            The sync result to persist.
        now:
            Optional ISO-8601 timestamp string injected by tests for
            deterministic output.  When omitted, the current UTC time is used.

        Returns
        -------
        Path
            Absolute path of the written file.
        """
        ran_at: str = now if now is not None else datetime.now(timezone.utc).isoformat()

        # De-duplicate and convert to sorted relative POSIX paths.
        # Path.relative_to() is used so callers may pass absolute paths
        # (e.g. from engine.apply()) without breaking portability.
        seen: set[str] = set()
        posix_paths: list[str] = []
        for p in manifest.files_touched:
            try:
                rel = Path(p).relative_to(self._repo_root)
            except ValueError:
                # Path already relative or outside root — use as-is.
                rel = Path(p)
            posix = rel.as_posix()
            if posix not in seen:
                seen.add(posix)
                posix_paths.append(posix)

        posix_paths.sort()

        exceptions_sorted = sorted(manifest.exceptions_used)

        data: dict[str, object] = {
            "exceptions_used": exceptions_sorted,
            "files_touched": posix_paths,
            "ran_at": ran_at,
            "upstream_sha": manifest.upstream_sha,
        }

        # sort_keys=True is redundant given we already control insertion order
        # above, but it makes the determinism guarantee explicit and immune to
        # future refactors that might change dict construction order.
        serialised = json.dumps(data, indent=2, sort_keys=True) + "\n"

        dest = self._repo_root / self._MANIFEST_RELPATH
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(serialised, encoding="utf-8")

        return dest
