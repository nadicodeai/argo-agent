"""Regression test: ContentPass must not rewrite argo-rename.yaml itself.

The seed argo-rename.yaml lists itself in exceptions::

    exceptions:
      - path: "argo-rename.yaml"
        why: "..."

This test verifies that ContentPass honours that exception, so that the
config file is never corrupted (e.g. ``from: foo`` rewritten to
``from: bar`` when the mapping ``foo→bar`` is active).

Issue 1 in M2 review: reviewer claimed ContentPass.run() rewrites the
config, producing ``from: argo, to: argo``.  This test is the definitive
reproducer: if it PASSES the exception mechanism already works correctly
(false positive); if it FAILS the exception logic is broken and must be
fixed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from argo_sync.config import ExceptionRule, RenameConfig
from argo_sync.engine import RenameEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    mappings: list[tuple[str, str]],
    exceptions: list[tuple[str, str]],
    *,
    skip_contexts: tuple[str, ...] = (),
) -> RenameConfig:
    """Build a RenameConfig without touching the filesystem."""
    exc_rules = tuple(ExceptionRule(path=p, why=w) for p, w in exceptions)
    sorted_mappings = tuple(
        sorted(mappings, key=lambda t: len(t[0]), reverse=True)
    )
    return RenameConfig(
        mappings=sorted_mappings,
        exceptions=exc_rules,
        skip_contexts=skip_contexts,
    )


# ---------------------------------------------------------------------------
# Test: config file survives the full engine run unchanged
# ---------------------------------------------------------------------------


def test_config_file_is_not_rewritten(tmp_path: Path) -> None:
    """argo-rename.yaml is preserved byte-for-byte when listed in exceptions.

    Scenario
    --------
    * Mapping: ``foo → bar``
    * Config file sits at ``tmp_path/argo-rename.yaml`` and contains the
      literal string "foo" (the mapping key) in its YAML body.
    * The config lists ``argo-rename.yaml`` in exceptions.
    * After running RenameEngine.apply(), the config file must be unchanged.
    * A sibling file (``module.py``) that is NOT excepted must have "foo"
      replaced with "bar", proving the engine did actually process the tree.
    """
    # --- Build the config YAML content (contains mapping key "foo") ---
    config_yaml = (
        "mappings:\n"
        "  - {from: foo, to: bar}\n"
        "exceptions:\n"
        "  - path: argo-rename.yaml\n"
        "    why: Config file must not be rewritten.\n"
        "skip_contexts: []\n"
    )
    config_path = tmp_path / "argo-rename.yaml"
    config_path.write_text(config_yaml, encoding="utf-8")

    # --- A regular source file that should be rewritten ---
    source_file = tmp_path / "module.py"
    source_file.write_text(
        "# foo module\nfoo_value = 42\n", encoding="utf-8"
    )

    # --- Build config object (exception covers the yaml file) ---
    cfg = _make_config(
        mappings=[("foo", "bar")],
        exceptions=[("argo-rename.yaml", "Config file must not be rewritten.")],
    )

    # --- Run the full engine ---
    RenameEngine(cfg).apply(tmp_path)

    # --- Assert 1: config file is byte-identical ---
    after = config_path.read_text(encoding="utf-8")
    assert after == config_yaml, (
        "argo-rename.yaml was modified by ContentPass despite being listed "
        f"in exceptions.\nExpected:\n{config_yaml!r}\nGot:\n{after!r}"
    )

    # --- Assert 2: sibling file WAS rewritten (engine is working) ---
    # module.py is NOT in exceptions, so its content should be transformed.
    # FilenamePass may also rename "module.py" if "foo" appears in the name,
    # but in this case the basename is "module.py" which has no "foo", so
    # the file is found at its original path.
    rewritten = source_file.read_text(encoding="utf-8")
    assert "foo" not in rewritten, (
        f"module.py still contains 'foo' after engine run: {rewritten!r}"
    )
    assert "bar" in rewritten, (
        f"module.py does not contain 'bar' after engine run: {rewritten!r}"
    )


def test_config_file_exception_covers_root_bare_basename(tmp_path: Path) -> None:
    """Exception ``path: argo-rename.yaml`` matches a root-level file.

    This test isolates the matches_exception() method to confirm that a
    bare filename (no directory component) in the exceptions list correctly
    matches a root-level file passed as a repo-relative POSIX path.
    """
    cfg = _make_config(
        mappings=[("foo", "bar")],
        exceptions=[("argo-rename.yaml", "self-protection")],
    )

    # Root-level file: repo-relative path is just the filename.
    assert cfg.matches_exception("argo-rename.yaml"), (
        "matches_exception() returned False for a bare filename exception "
        "when called with the exact same bare filename."
    )
    # Deeper path should NOT match the bare-filename exception.
    assert not cfg.matches_exception("subdir/argo-rename.yaml"), (
        "matches_exception() returned True for a nested path when the "
        "exception is only a bare root-level filename."
    )
