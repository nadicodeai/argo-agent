"""argo_sync.passes.content — in-file content rename pass.

Walks every regular file under a given root directory, detects and skips binary
files and excluded paths, then applies all ``(from, to)`` mappings from
:class:`~argo_sync.config.RenameConfig` via ``str.replace``.

``skip_contexts`` strategy
--------------------------
Some mapping keys appear inside contexts that must not be rewritten — for
example, a key that is part of an upstream URL like
``https://example.com/old-name/api``.  Naively replacing the entire file
content would corrupt those URLs.

The approach used here:

1. For the current file's content, find *all* regex matches for every
   ``skip_contexts`` pattern and record their ``(start, end)`` byte-offset
   ranges.
2. Split the content into alternating *outside* / *inside* segments based
   on those ranges — the segment boundaries are sorted and merged so that
   overlapping or adjacent protected ranges are treated as one contiguous
   block.
3. Apply ``str.replace`` **only** to the *outside* segments.
4. Re-join all segments (outside-replaced and inside-preserved) in order.

This guarantees that text inside any ``skip_contexts`` match is never
modified, while text outside those matches is transformed normally.
"""

from __future__ import annotations

import collections.abc
import os
import re
from pathlib import Path

from argo_sync.config import RenameConfig
from argo_sync.passes._constants import SKIP_DIRS as _SKIP_DIRS

# Number of bytes to inspect for binary detection.
_BINARY_PROBE_BYTES: int = 8192


def _is_binary(path: Path) -> bool:
    """Return True if *path* appears to be a binary file.

    Reads the first :data:`_BINARY_PROBE_BYTES` bytes; if a NUL byte is
    found, the file is treated as binary and skipped.
    """
    try:
        chunk = path.read_bytes()[:_BINARY_PROBE_BYTES]
    except OSError:
        # Unreadable file — skip it safely.
        return True
    return b"\x00" in chunk


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge overlapping or adjacent ``(start, end)`` intervals.

    Returns a sorted list of non-overlapping intervals covering the same
    positions as the input.
    """
    if not ranges:
        return []
    sorted_ranges = sorted(ranges, key=lambda r: r[0])
    merged: list[tuple[int, int]] = [sorted_ranges[0]]
    for start, end in sorted_ranges[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            # Overlapping or touching — extend the current interval.
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def _apply_mappings_with_skip_contexts(
    content: str,
    mappings: tuple[tuple[str, str], ...],
    skip_patterns: tuple[str, ...],
) -> str:
    """Apply *mappings* to *content*, leaving *skip_patterns* matches intact.

    Parameters
    ----------
    content:
        The full text of the file.
    mappings:
        ``(from, to)`` pairs already sorted longest-first.
    skip_patterns:
        Regex patterns whose matches are protected from substitution.

    Returns
    -------
    str
        The rewritten content (may be identical to *content* if no mapping
        applied outside protected regions).
    """
    # Collect all protected ranges from every skip_contexts pattern.
    protected: list[tuple[int, int]] = []
    for pattern in skip_patterns:
        for m in re.finditer(pattern, content):
            protected.append((m.start(), m.end()))

    if not protected:
        # Fast path — no skip_contexts active; apply all mappings directly.
        result = content
        for from_str, to_str in mappings:
            result = result.replace(from_str, to_str)
        return result

    merged = _merge_ranges(protected)

    # Split content into segments: [(text, is_protected), ...]
    # "outside" segments are subject to replacement; "inside" segments are not.
    segments: list[tuple[str, bool]] = []
    cursor = 0
    for prot_start, prot_end in merged:
        if cursor < prot_start:
            segments.append((content[cursor:prot_start], False))
        segments.append((content[prot_start:prot_end], True))
        cursor = prot_end
    if cursor < len(content):
        segments.append((content[cursor:], False))

    # Apply mappings only to unprotected segments.
    out_parts: list[str] = []
    for text, is_protected in segments:
        if is_protected:
            out_parts.append(text)
        else:
            for from_str, to_str in mappings:
                text = text.replace(from_str, to_str)
            out_parts.append(text)

    return "".join(out_parts)


class ContentPass:
    """Apply in-file content renames to all eligible files under a root.

    Parameters
    ----------
    config:
        A loaded :class:`~argo_sync.config.RenameConfig` instance providing
        the ordered mappings, exception globs, and skip_contexts patterns.
    """

    def __init__(self, config: RenameConfig) -> None:
        self._config = config

    def run(self, root: Path) -> list[Path]:
        """Apply content renames in-place. Returns paths whose content changed.

        For each regular file reachable from *root*:

        - Directories named ``.git``, ``.venv``, ``.argo``, ``__pycache__``,
          or ``node_modules`` are skipped entirely (not descended into).
        - Files matched by any ``config.exceptions`` glob are skipped.
        - Files that appear binary (contain a NUL byte in the first 8 KB)
          are skipped.
        - For the remaining files, all ``(from, to)`` mappings are applied
          via ``str.replace`` in longest-key-first order, while text inside
          any ``skip_contexts`` regex match is left unchanged.

        Files whose content is unchanged after applying all mappings are
        *not* written back and are *not* included in the returned list.

        Parameters
        ----------
        root:
            Directory to walk.  Must exist.

        Returns
        -------
        list[Path]
            Absolute paths of files whose on-disk content was changed.
        """
        config = self._config
        touched: list[Path] = []

        # Walk the tree, pruning skipped directories in-place.
        for dirpath, dirnames, filenames in _walk(root):
            # Prune skipped dirs so we don't descend into them.
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]

            for filename in filenames:
                file_path = dirpath / filename

                # Compute repo-relative POSIX path for exception matching.
                try:
                    rel = file_path.relative_to(root).as_posix()
                except ValueError:
                    rel = file_path.as_posix()

                if config.matches_exception(rel):
                    continue

                if _is_binary(file_path):
                    continue

                try:
                    original = file_path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    # Skip files that can't be decoded as UTF-8.
                    continue

                rewritten = _apply_mappings_with_skip_contexts(
                    original,
                    config.mappings,
                    config.skip_contexts,
                )

                if rewritten != original:
                    file_path.write_text(rewritten, encoding="utf-8")
                    touched.append(file_path)

        return touched


def _walk(
    root: Path,
) -> collections.abc.Generator[tuple[Path, list[str], list[str]], None, None]:
    """Yield ``(dirpath, dirnames, filenames)`` tuples starting from *root*.

    This is a thin wrapper around :func:`os.walk` that works with
    :class:`~pathlib.Path` objects and supports in-place pruning of
    *dirnames* (the caller modifies the list to prevent descent).
    """
    for dirpath_str, dirnames, filenames in os.walk(root):
        yield Path(dirpath_str), dirnames, filenames
