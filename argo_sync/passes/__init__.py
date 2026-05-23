"""argo_sync.passes — individual rename transformation passes.

Each pass is a self-contained class with a ``run(root: Path) -> list[Path]``
method that applies one class of transformation (content, filenames, directories)
and returns the list of paths that were actually modified.

Passes are stateless between runs; the orchestrator in
:mod:`argo_sync.engine` calls them in the required order:
content → filenames → directories.
"""

from __future__ import annotations
