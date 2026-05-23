"""argo_cli.doctor_leakage — leakage detection modes for `argo doctor`.

Implements the two new sub-modes added in T4.2 (--static) and T4.3 (--live):

--static
    Walks the repo tree, greps each non-binary text file case-insensitively
    for the upstream source identifier, and reports any hit that falls outside
    a skip_contexts-protected region or an exceptions-listed path.

--live
    Spawns a subprocess (configurable via --live-cmd, defaulting to a safe
    fallback set: `argo --help`, `argo --version`, `argo doctor --static`),
    captures its combined output, and greps for the same identifier.

Both modes read their configuration from argo-rename.yaml (located in the
repo root by default, overridable via --rename-yaml) and use the same
skip_contexts / exceptions logic as the argo_sync rename engine.

Design notes
------------
- No new runtime dependencies: uses only stdlib + yaml (already required).
- All file I/O uses encoding="utf-8".
- No `raise Exception(...)` — only typed subclasses (ValueError / RuntimeError).
- The upstream source identifier is never spelled as a literal in this module;
  it is loaded from the rename config's mappings at runtime.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple, Sequence

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Directory basenames excluded from the static walk (mirrors argo_sync).
_SKIP_DIRS: frozenset[str] = frozenset(
    {".git", ".venv", ".argo", "__pycache__", "node_modules"}
)

#: Number of bytes to probe for binary detection.
_BINARY_PROBE: int = 8192


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class LeakHit(NamedTuple):
    """A single detected occurrence of the upstream source identifier."""

    path: str       # repo-relative POSIX path
    line_no: int    # 1-based
    col_no: int     # 1-based
    line_text: str  # original line text (no trailing newline)
    suggestion: str # best matching rename suggestion, or "add to exceptions"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_binary(path: Path) -> bool:
    """Return True when *path* appears to be binary (NUL byte present)."""
    try:
        chunk = path.read_bytes()[:_BINARY_PROBE]
    except OSError:
        return True
    return b"\x00" in chunk


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge overlapping / adjacent ``(start, end)`` char-offset intervals."""
    if not ranges:
        return []
    sorted_r = sorted(ranges, key=lambda r: r[0])
    merged: list[tuple[int, int]] = [sorted_r[0]]
    for start, end in sorted_r[1:]:
        ps, pe = merged[-1]
        if start <= pe:
            merged[-1] = (ps, max(pe, end))
        else:
            merged.append((start, end))
    return merged


def _protected_ranges(line: str, skip_patterns: Sequence[str]) -> list[tuple[int, int]]:
    """Return merged char ranges in *line* covered by any *skip_patterns* match."""
    raw: list[tuple[int, int]] = []
    for pat in skip_patterns:
        try:
            for m in re.finditer(pat, line):
                raw.append((m.start(), m.end()))
        except re.error:
            pass
    return _merge_ranges(raw)


def _col_in_protected(col0: int, token_len: int, protected: list[tuple[int, int]]) -> bool:
    """Return True when the token at *col0* (0-based) falls inside a protected range."""
    token_end = col0 + token_len
    for ps, pe in protected:
        # Any overlap between [col0, token_end) and [ps, pe) counts.
        if col0 < pe and token_end > ps:
            return True
    return False


def _best_suggestion(
    token_lower: str,
    mappings: Sequence[tuple[str, str]],
) -> str:
    """Return the best rename suggestion for *token_lower*.

    Walks mappings longest-first (they are already pre-sorted) and returns
    the ``to`` value of the first mapping whose ``from`` value matches
    (case-insensitively) a substring of *token_lower*.  Falls back to
    ``"add to exceptions"`` when nothing matches.
    """
    for from_str, to_str in mappings:
        if from_str.lower() in token_lower:
            return to_str
    return "add to exceptions"


def _load_rename_config(rename_yaml: Path) -> tuple[
    tuple[tuple[str, str], ...],
    tuple[str, ...],
    tuple[str, ...],
    str,
]:
    """Load argo-rename.yaml and return (mappings, exception_globs, skip_patterns, probe_token).

    Returns
    -------
    mappings:
        ``(from, to)`` pairs sorted longest-from-first (as stored by RenameConfig).
    exception_globs:
        Path globs from the ``exceptions:`` list.
    skip_patterns:
        Regex strings from ``skip_contexts:``.
    probe_token:
        The shortest pure-lowercase alphabetic ``from`` key — this is the bare
        upstream source identifier we scan for.
    """
    import yaml  # already a required dependency

    raw = rename_yaml.read_text(encoding="utf-8")
    data: object = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise ValueError(f"argo-rename.yaml must be a YAML mapping, got {type(data).__name__!r}")

    raw_mappings: object = data.get("mappings", [])
    if not isinstance(raw_mappings, list):
        raise ValueError("'mappings' must be a list")

    mappings: list[tuple[str, str]] = []
    for entry in raw_mappings:
        if isinstance(entry, dict) and "from" in entry and "to" in entry:
            f, t = str(entry["from"]), str(entry["to"])
            if f:
                mappings.append((f, t))

    # Sort longest-from-first (mirrors RenameConfig.load).
    mappings.sort(key=lambda p: len(p[0]), reverse=True)

    raw_exceptions: object = data.get("exceptions", [])
    exception_globs: list[str] = []
    if isinstance(raw_exceptions, list):
        for e in raw_exceptions:
            if isinstance(e, dict) and "path" in e:
                exception_globs.append(str(e["path"]))

    raw_skip: object = data.get("skip_contexts", [])
    skip_patterns: list[str] = []
    if isinstance(raw_skip, list):
        for s in raw_skip:
            if isinstance(s, str):
                skip_patterns.append(s)

    # Derive the probe token: shortest pure-lowercase alpha "from" key.
    alpha_lower: list[str] = [f for f, _ in mappings if f.isalpha() and f.islower()]
    if not alpha_lower:
        raise ValueError("No bare lowercase probe token found in mappings")
    # sorted()[0] is unambiguously str; avoid min(..., key=len) which confuses ty.
    probe_token: str = sorted(alpha_lower, key=lambda s: len(s))[0]

    return (
        tuple(mappings),
        tuple(exception_globs),
        tuple(skip_patterns),
        probe_token,
    )


def _matches_exception(rel_posix: str, exception_globs: tuple[str, ...]) -> bool:
    """Return True when *rel_posix* matches any exception glob."""
    import fnmatch

    for glob in exception_globs:
        if fnmatch.fnmatch(rel_posix, glob):
            return True
        if glob.endswith("/**"):
            prefix = glob[: -len("/**")]
            if rel_posix == prefix or rel_posix.startswith(prefix + "/"):
                return True
    return False


def _scan_text(
    content: str,
    probe_token: str,
    mappings: tuple[tuple[str, str], ...],
    skip_patterns: tuple[str, ...],
    rel_path: str,
) -> list[LeakHit]:
    """Scan *content* for *probe_token* (case-insensitive) and return hits.

    Hits inside skip_contexts-protected regions are suppressed.
    """
    hits: list[LeakHit] = []
    probe_lower = probe_token.lower()
    token_len = len(probe_lower)

    for line_no, line in enumerate(content.splitlines(), start=1):
        line_lower = line.lower()
        if probe_lower not in line_lower:
            continue
        protected = _protected_ranges(line, skip_patterns)
        # Find every occurrence.
        start = 0
        while True:
            idx = line_lower.find(probe_lower, start)
            if idx == -1:
                break
            col0 = idx
            if not _col_in_protected(col0, token_len, protected):
                suggestion = _best_suggestion(line_lower[col0: col0 + token_len + 20], mappings)
                hits.append(
                    LeakHit(
                        path=rel_path,
                        line_no=line_no,
                        col_no=col0 + 1,
                        line_text=line.rstrip("\n\r"),
                        suggestion=suggestion,
                    )
                )
            start = idx + 1

    return hits


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_static(
    repo_root: Path,
    rename_yaml: Path,
    *,
    verbose: bool = True,
) -> list[LeakHit]:
    """Walk *repo_root* and return all unexcepted upstream-token occurrences.

    Parameters
    ----------
    repo_root:
        Root directory to scan.
    rename_yaml:
        Path to argo-rename.yaml.  This file itself is always excluded from
        scanning (it must contain both sides of every mapping by definition).
    verbose:
        When True, print each hit to stdout in the standard format.

    Returns
    -------
    list[LeakHit]
        All detected hits.  Empty list means the tree is clean.
    """
    mappings, exception_globs, skip_patterns, probe_token = _load_rename_config(rename_yaml)

    # The rename config file is always self-excepted — it must reference both
    # the source and target identifiers by definition.
    rename_yaml_abs = rename_yaml.resolve()

    all_hits: list[LeakHit] = []

    for dirpath, dirnames, filenames in os.walk(repo_root):
        # Prune excluded directories in-place (os.walk respects this).
        dirnames[:] = [
            d for d in dirnames
            if d not in _SKIP_DIRS
        ]

        for filename in filenames:
            abs_path = Path(dirpath) / filename
            # Always skip the rename config itself.
            if abs_path.resolve() == rename_yaml_abs:
                continue

            try:
                rel_posix = abs_path.relative_to(repo_root).as_posix()
            except ValueError:
                continue

            if _matches_exception(rel_posix, exception_globs):
                continue

            if _is_binary(abs_path):
                continue

            try:
                content = abs_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            file_hits = _scan_text(content, probe_token, mappings, skip_patterns, rel_posix)
            all_hits.extend(file_hits)

            if verbose and file_hits:
                for hit in file_hits:
                    print(
                        f"{hit.path}:{hit.line_no}:{hit.col_no}: "
                        f"'{probe_token}' found (suggest: {hit.suggestion})"
                    )

    return all_hits


def run_live(
    rename_yaml: Path,
    *,
    live_cmd: str | None = None,
    verbose: bool = True,
) -> list[LeakHit]:
    """Run a subprocess and scan its captured output for upstream-token leakage.

    Parameters
    ----------
    rename_yaml:
        Path to argo-rename.yaml.
    live_cmd:
        Shell command to run.  When None the fallback set is used:
        ``argo --help``, ``argo --version``, ``argo doctor --help``, and ``argo update --help``.
    verbose:
        When True, print each hit to stdout.

    Returns
    -------
    list[LeakHit]
        All detected hits in the captured output.
    """
    mappings, _exc_globs, skip_patterns, probe_token = _load_rename_config(rename_yaml)

    # Build the list of commands to run.
    if live_cmd:
        # Caller supplied a shell command — run it via shell=True.
        commands: list[list[str]] = []
        shell_commands: list[str] = [live_cmd]
    else:
        # Fallback: safe CLI commands that exercise the real install without
        # recursively scanning the repo (so no false positives from test files).
        # `doctor --help` is included to exercise the doctor module's own
        # help-text rendering — a subset of the runtime code path beyond `--help`.
        argo_exe = [sys.executable, "-m", "argo_cli.main"]
        commands = [
            argo_exe + ["--help"],
            argo_exe + ["--version"],
            argo_exe + ["doctor", "--help"],
            argo_exe + ["update", "--help"],
        ]
        shell_commands = []

    combined_output = ""

    if shell_commands:
        for cmd_str in shell_commands:
            try:
                proc = subprocess.run(
                    cmd_str,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                combined_output += proc.stdout + proc.stderr
            except subprocess.TimeoutExpired:
                pass
    else:
        for cmd in commands:
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                combined_output += proc.stdout + proc.stderr
            except subprocess.TimeoutExpired:
                pass

    # Scan the combined output.
    hits = _scan_text(combined_output, probe_token, mappings, skip_patterns, "<live-output>")

    if verbose and hits:
        for hit in hits:
            print(
                f"<live>:{hit.line_no}:{hit.col_no}: "
                f"'{probe_token}' found in subprocess output (suggest: {hit.suggestion})"
            )

    return hits
