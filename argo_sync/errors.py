"""argo_sync error hierarchy.

All domain errors inherit from :class:`ArgoSyncError`.  Never raise the
bare base; use the specific subclass that carries the right context fields.
"""

from __future__ import annotations


class ArgoSyncError(RuntimeError):
    """Base class for all argo_sync domain errors."""


class ConfigError(ArgoSyncError):
    """Raised when argo-rename.yaml cannot be loaded or fails validation.

    Attributes
    ----------
    path:
        The filesystem path of the config file that triggered the error.
    """

    def __init__(self, message: str, path: object = None) -> None:
        detail = f"{path}: {message}" if path is not None else message
        super().__init__(detail)
        self.path = path


class RenameConflictError(ArgoSyncError):
    """Raised when a rename target path already exists and would be clobbered.

    Attributes
    ----------
    source:
        Path being renamed.
    target:
        Destination path that already exists.
    """

    def __init__(self, source: object, target: object) -> None:
        super().__init__(
            f"rename conflict: {source} → {target} (target exists)"
        )
        self.source = source
        self.target = target


class UpstreamMergeConflict(ArgoSyncError):
    """Raised when a git merge conflict is encountered during upstream sync.

    Used in M4 (argo update / git_ops layer).  The engine itself does not
    raise this; the git_ops layer does after detecting unresolved conflict
    markers left by ``git merge``.

    Attributes
    ----------
    conflicting_files:
        Sequence of file paths that contain conflict markers.
    """

    def __init__(self, conflicting_files: object) -> None:
        super().__init__(
            f"upstream merge conflict in: {conflicting_files}"
        )
        self.conflicting_files = conflicting_files
