"""argo_sync.passes — individual rename passes.

Each pass is a standalone class that takes a :class:`~argo_sync.config.RenameConfig`
and operates on a directory tree.  The engine (T2.6) wires them in order:
content → filenames → directories.
"""
