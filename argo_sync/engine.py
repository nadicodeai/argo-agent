"""RenameEngine — shell class for the ordered rename pipeline.

The three sub-passes (content rewrite, file rename, directory rename) are
implemented in T2.2–T2.5.  T2.6 wires them together inside :meth:`apply`.
"""

from __future__ import annotations

from pathlib import Path

from .config import RenameConfig


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
        """Run content -> filenames -> directories.  Returns touched paths.

        Sub-passes land in T2.2-T2.5.  T2.6 wires them here.
        """
        raise NotImplementedError(
            "T2.6 wires this; T2.2-T2.5 implement passes"
        )
