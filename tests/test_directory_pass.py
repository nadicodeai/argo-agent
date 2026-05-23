"""Tests for argo_sync.passes.directories.DirectoryPass.

Covers:
  1. Single dir rename.
  2. Nested bottom-up traversal.
  3. Exception glob prevents rename.
  4. Hard-coded skip set (.git, .venv, .argo, __pycache__, node_modules).
  5. Files inside renamed dirs are preserved.
  6. Collision raises RenameConflictError.
  7. Longest-first mapping ordering.
  8. Empty dir rename.
  9. Dirs with no matching mapping are not renamed / not in returned list.
  10. Symlink-to-directory is skipped.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from argo_sync.config import ExceptionRule, RenameConfig
from argo_sync.errors import RenameConflictError
from argo_sync.passes.directories import DirectoryPass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_config(
    mappings: list[tuple[str, str]],
    exceptions: list[tuple[str, str]] | None = None,
) -> RenameConfig:
    """Build a RenameConfig without touching the filesystem."""
    exc_rules = tuple(
        ExceptionRule(path=p, why=w) for p, w in (exceptions or [])
    )
    # Sort longest-first to match the loader behaviour.
    sorted_mappings = tuple(
        sorted(mappings, key=lambda t: len(t[0]), reverse=True)
    )
    return RenameConfig(
        mappings=sorted_mappings,
        exceptions=exc_rules,
        skip_contexts=(),
    )


# ---------------------------------------------------------------------------
# Test 1 — Single directory rename
# ---------------------------------------------------------------------------


def test_single_dir_rename(tmp_path: Path) -> None:
    """old_cli/ with mapping old→new becomes new_cli/."""
    (tmp_path / "old_cli").mkdir()
    cfg = make_config([("old", "new")])
    result = DirectoryPass(cfg).run(tmp_path)

    assert (tmp_path / "new_cli").is_dir()
    assert not (tmp_path / "old_cli").exists()
    assert result == [tmp_path / "new_cli"]


# ---------------------------------------------------------------------------
# Test 2 — Nested bottom-up traversal
# ---------------------------------------------------------------------------


def test_nested_bottom_up(tmp_path: Path) -> None:
    """old/middle_old/leaf_old → new/middle_new/leaf_new (leaf first).

    Bottom-up traversal renames leaf_old first (while still under old/middle_old),
    then middle_old (while still under old/), then old itself.  Because each rename
    is atomic and performed in depth order, the final tree is fully renamed.

    The returned paths are the new locations immediately after each rename step:
      result[0] = …/old/middle_old/leaf_new   (leaf renamed first)
      result[1] = …/old/middle_new            (middle renamed next)
      result[2] = …/new                       (top renamed last)
    """
    leaf = tmp_path / "old" / "middle_old" / "leaf_old"
    leaf.mkdir(parents=True)

    cfg = make_config([("old", "new")])
    result = DirectoryPass(cfg).run(tmp_path)

    # Final filesystem state must be fully renamed.
    expected_leaf = tmp_path / "new" / "middle_new" / "leaf_new"
    assert expected_leaf.is_dir()
    assert not (tmp_path / "old").exists()

    # Three dirs were renamed.
    assert len(result) == 3

    # Verify bottom-up order by checking that the shallowest path (fewest parts)
    # appears last in the list — i.e. leaf before middle before top.
    depths = [len(p.parts) for p in result]
    assert depths == sorted(depths, reverse=True), (
        f"Expected descending depth order (leaf first), got {depths}"
    )


# ---------------------------------------------------------------------------
# Test 3 — Exception glob prevents rename
# ---------------------------------------------------------------------------


def test_exception_glob_skips_rename(tmp_path: Path) -> None:
    """.shepherd/ is preserved via exception glob even if it matches mapping."""
    (tmp_path / ".shepherd").mkdir()
    cfg = make_config(
        [("shepherd", "navigator")],
        exceptions=[(".shepherd/**", "Orchestrator state.")],
    )
    result = DirectoryPass(cfg).run(tmp_path)

    assert (tmp_path / ".shepherd").is_dir()
    assert not (tmp_path / ".navigator").exists()
    assert result == []


# ---------------------------------------------------------------------------
# Test 4 — Hard-coded skip set is never renamed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skip_name", [".git", ".venv", ".argo", "__pycache__", "node_modules"])
def test_hard_coded_skip_dirs_not_renamed(tmp_path: Path, skip_name: str) -> None:
    """Hard-coded dirs are never renamed even when the mapping would match."""
    # Construct a mapping that would match the skip-dir name.
    # E.g. ".git" contains "git"; "__pycache__" contains "pycache".
    raw = skip_name.lstrip("._")  # "git", "venv", "argo", "pycache", "node_modules"
    target_name = raw + "_renamed"
    (tmp_path / skip_name).mkdir()

    cfg = make_config([(raw, target_name)])
    result = DirectoryPass(cfg).run(tmp_path)

    assert (tmp_path / skip_name).is_dir()
    assert result == []


# ---------------------------------------------------------------------------
# Test 5 — Files inside renamed dirs are preserved
# ---------------------------------------------------------------------------


def test_files_preserved_after_dir_rename(tmp_path: Path) -> None:
    """Files inside old_pkg/ are accessible after rename to new_pkg/."""
    pkg = tmp_path / "old_pkg"
    pkg.mkdir()
    sentinel = pkg / "module.py"
    sentinel.write_text("# content\nvalue = 42\n", encoding="utf-8")

    cfg = make_config([("old", "new")])
    DirectoryPass(cfg).run(tmp_path)

    new_sentinel = tmp_path / "new_pkg" / "module.py"
    assert new_sentinel.exists()
    assert new_sentinel.read_text(encoding="utf-8") == "# content\nvalue = 42\n"


# ---------------------------------------------------------------------------
# Test 6 — Collision raises RenameConflictError
# ---------------------------------------------------------------------------


def test_collision_raises_conflict_error(tmp_path: Path) -> None:
    """If target already exists, raise RenameConflictError (no overwrite)."""
    (tmp_path / "old_dir").mkdir()
    (tmp_path / "new_dir").mkdir()  # collision

    cfg = make_config([("old", "new")])
    with pytest.raises(RenameConflictError) as exc_info:
        DirectoryPass(cfg).run(tmp_path)

    err = exc_info.value
    assert err.source == tmp_path / "old_dir"
    assert err.target == tmp_path / "new_dir"


# ---------------------------------------------------------------------------
# Test 7 — Longest-first mapping ordering
# ---------------------------------------------------------------------------


def test_longest_first_mapping_wins(tmp_path: Path) -> None:
    """oldlong_dir with mappings oldlong→A and old→B becomes A_dir, not B_long_dir."""
    (tmp_path / "oldlong_dir").mkdir()
    cfg = make_config([("oldlong", "A"), ("old", "B")])
    result = DirectoryPass(cfg).run(tmp_path)

    assert (tmp_path / "A_dir").is_dir()
    assert not (tmp_path / "B_long_dir").exists()
    assert result == [tmp_path / "A_dir"]


# ---------------------------------------------------------------------------
# Test 8 — Empty directories are renamed cleanly
# ---------------------------------------------------------------------------


def test_empty_dir_rename(tmp_path: Path) -> None:
    """Empty old_empty/ renames cleanly to new_empty/."""
    (tmp_path / "old_empty").mkdir()
    cfg = make_config([("old", "new")])
    result = DirectoryPass(cfg).run(tmp_path)

    assert (tmp_path / "new_empty").is_dir()
    assert not (tmp_path / "old_empty").exists()
    assert result == [tmp_path / "new_empty"]
    # Verify it's truly empty.
    assert list((tmp_path / "new_empty").iterdir()) == []


# ---------------------------------------------------------------------------
# Test 9 — Dirs with no matching mapping not in returned list
# ---------------------------------------------------------------------------


def test_no_match_not_in_result(tmp_path: Path) -> None:
    """Dirs whose names contain no mapping key are left alone and excluded from result."""
    (tmp_path / "unrelated_dir").mkdir()
    (tmp_path / "another_one").mkdir()
    cfg = make_config([("old", "new")])  # neither dir matches "old"
    result = DirectoryPass(cfg).run(tmp_path)

    assert result == []
    assert (tmp_path / "unrelated_dir").is_dir()
    assert (tmp_path / "another_one").is_dir()


# ---------------------------------------------------------------------------
# Test 10 — Symlink-to-directory: skip rather than rename
# ---------------------------------------------------------------------------


def test_symlink_to_dir_is_skipped(tmp_path: Path) -> None:
    """Symlinks pointing to directories are skipped (not renamed).

    Rationale: renaming a symlink rather than its target would silently change
    the meaning of the link.  The target (if it is itself a real directory under
    root) will be handled in its own traversal entry if applicable.  Symlinks are
    out-of-scope for this pass; they are left in place.
    """
    real_dir = tmp_path / "real_old"
    real_dir.mkdir()
    link = tmp_path / "old_link"
    link.symlink_to(real_dir)

    cfg = make_config([("old", "new")])
    result = DirectoryPass(cfg).run(tmp_path)

    # The real directory should be renamed.
    assert (tmp_path / "real_new").is_dir()
    # The symlink should NOT be renamed — it still exists under its original name.
    assert link.is_symlink()
    assert not (tmp_path / "new_link").exists()
    # Only the real dir appears in the result.
    assert tmp_path / "real_new" in result
    assert link not in result
