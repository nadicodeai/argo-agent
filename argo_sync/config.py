"""RenameConfig — loads and validates argo-rename.yaml.

The YAML schema is::

    mappings:
      - {from: "OldLongName", to: "NewLongName"}
      - ...
    exceptions:
      - path: ".shepherd/**"
        why: "Orchestrator state."
      - ...
    skip_contexts:
      - 'https?://[^\\s]*'
      - ...

All fields are required at the top level (may be empty lists).
Mappings are sorted longest-``from``-first after load so that longer tokens
shadow shorter overlapping ones (e.g. a 12-char key applies before a 6-char
key that would otherwise overlap it).
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
import yaml

from .errors import ConfigError

# ---------------------------------------------------------------------------
# Supporting types
# ---------------------------------------------------------------------------

_REQUIRED_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {"mappings", "exceptions", "skip_contexts"}
)


@dataclass(frozen=True)
class ExceptionRule:
    """A single exception entry from the ``exceptions:`` list."""

    path: str
    why: str


# ---------------------------------------------------------------------------
# Main config dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RenameConfig:
    """Immutable, validated snapshot of argo-rename.yaml.

    Attributes
    ----------
    mappings:
        Ordered ``(from, to)`` pairs.  Sorted longest-``from``-first so that
        more-specific tokens shadow shorter overlapping ones.
    exceptions:
        Glob paths whose file contents are left untouched by the rename
        engine and skipped by ``argo doctor --static``.
    skip_contexts:
        Per-file-content regex patterns: matches inside these patterns are
        NOT rewritten (e.g. URLs, commit hashes).
    """

    mappings: tuple[tuple[str, str], ...]
    exceptions: tuple[ExceptionRule, ...]
    skip_contexts: tuple[str, ...]

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: Path) -> "RenameConfig":
        """Load and validate *path*, returning a frozen :class:`RenameConfig`.

        Raises
        ------
        ConfigError
            If the file cannot be parsed as YAML, is missing a required key,
            or contains an invalid mapping entry (e.g. empty ``from``).
        """
        try:
            raw_text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(str(exc), path) from exc

        try:
            data: object = yaml.safe_load(raw_text)
        except yaml.YAMLError as exc:
            raise ConfigError(f"YAML parse error: {exc}", path) from exc

        if not isinstance(data, dict):
            raise ConfigError(
                "top-level value must be a mapping, got"
                f" {type(data).__name__!r}",
                path,
            )

        # Check for required keys
        missing = _REQUIRED_TOP_LEVEL_KEYS - data.keys()
        if missing:
            raise ConfigError(
                f"missing required key(s): {', '.join(sorted(missing))}",
                path,
            )

        # --- mappings ---
        raw_mappings: object = data["mappings"]
        if not isinstance(raw_mappings, list):
            raise ConfigError("'mappings' must be a list", path)

        parsed_mappings: list[tuple[str, str]] = []
        for i, entry in enumerate(raw_mappings):
            if not isinstance(entry, dict):
                raise ConfigError(
                    f"mappings[{i}] must be a dict with 'from' and 'to' keys",
                    path,
                )
            if "from" not in entry or "to" not in entry:
                raise ConfigError(
                    f"mappings[{i}] is missing 'from' or 'to'",
                    path,
                )
            from_val: object = entry["from"]
            to_val: object = entry["to"]
            if not isinstance(from_val, str) or not isinstance(to_val, str):
                raise ConfigError(
                    f"mappings[{i}] 'from' and 'to' must be strings",
                    path,
                )
            if from_val == "":
                raise ConfigError(
                    f"mappings[{i}] 'from' must not be empty",
                    path,
                )
            parsed_mappings.append((from_val, to_val))

        # Sort longest-from-first (stable sort preserves relative order of equal lengths)
        parsed_mappings.sort(key=lambda t: len(t[0]), reverse=True)

        # --- exceptions ---
        raw_exceptions: object = data["exceptions"]
        if not isinstance(raw_exceptions, list):
            raise ConfigError("'exceptions' must be a list", path)

        parsed_exceptions: list[ExceptionRule] = []
        for i, entry in enumerate(raw_exceptions):
            if not isinstance(entry, dict):
                raise ConfigError(
                    f"exceptions[{i}] must be a dict with 'path' and 'why' keys",
                    path,
                )
            if "path" not in entry or "why" not in entry:
                raise ConfigError(
                    f"exceptions[{i}] is missing 'path' or 'why'",
                    path,
                )
            ep: object = entry["path"]
            ew: object = entry["why"]
            if not isinstance(ep, str) or not isinstance(ew, str):
                raise ConfigError(
                    f"exceptions[{i}] 'path' and 'why' must be strings",
                    path,
                )
            parsed_exceptions.append(ExceptionRule(path=ep, why=ew))

        # --- skip_contexts ---
        raw_skip: object = data["skip_contexts"]
        if not isinstance(raw_skip, list):
            raise ConfigError("'skip_contexts' must be a list", path)

        parsed_skip: list[str] = []
        for i, pattern in enumerate(raw_skip):
            if not isinstance(pattern, str):
                raise ConfigError(
                    f"skip_contexts[{i}] must be a string, got"
                    f" {type(pattern).__name__!r}",
                    path,
                )
            parsed_skip.append(pattern)

        return cls(
            mappings=tuple(parsed_mappings),
            exceptions=tuple(parsed_exceptions),
            skip_contexts=tuple(parsed_skip),
        )

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def matches_exception(self, repo_relative_path: str) -> bool:
        """Return True if *repo_relative_path* matches any exception glob.

        Uses :func:`fnmatch.fnmatch` for ``*``/``?``/``[…]`` patterns and
        also checks whether the path starts with a prefix stripped of its
        trailing ``**`` component, to handle ``dir/**`` globs correctly.

        Parameters
        ----------
        repo_relative_path:
            Path relative to the repository root, using forward slashes.
        """
        for rule in self.exceptions:
            if fnmatch.fnmatch(repo_relative_path, rule.path):
                return True
            # Handle "dir/**" by also matching the directory itself and any
            # descendant via a prefix check, since fnmatch("a/b", "a/**")
            # returns False on some platforms.
            if rule.path.endswith("/**"):
                prefix = rule.path[: -len("/**")]
                if repo_relative_path == prefix or repo_relative_path.startswith(
                    prefix + "/"
                ):
                    return True
        return False
