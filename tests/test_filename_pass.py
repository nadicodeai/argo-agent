"""Tests for argo_sync.passes.filenames — filename-rename pass.

Covers:
1. Single file rename (basename contains mapping key).
2. Nested directory tree — all eligible files renamed, parent dirs untouched.
3. Exception glob skips the file.
4. System directories (.git, .venv, .argo, __pycache__, node_modules) are skipped.
5. Bottom-up traversal: deepest files renamed before shallower ones.
6. Collision: target exists → RenameConflictError with both paths populated.
7. Mapping ordering: longer key wins (does not double-apply shorter key).
8. File with no matching mapping is not renamed and not in returned list.
9. Directories themselves are not renamed by this pass.
10. Symlinks are skipped (not renamed), documented below.

Symlink policy: FilenamePass skips symlinks.  Symlinks are neither files nor
directories in the strict sense, and atomically renaming a symlink's basename
is rarely what a rename engine wants (it would move the symlink, not the
target).  T2.4 (directory pass) also skips symlinks for the same reason.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from argo_sync.config import RenameConfig
from argo_sync.errors import RenameConflictError
from argo_sync.passes.filenames import FilenamePass

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MULTI_MAPPING_YAML = """\
mappings:
  - from: "oldlong"
    to: "NEW_LONG"
  - from: "old"
    to: "new"
exceptions: []
skip_contexts: []
"""

_EXCEPTION_YAML = """\
mappings:
  - from: "old"
    to: "new"
exceptions:
  - path: "keep/**"
    why: "Test exception."
skip_contexts: []
"""


def _config_single(tmp_path: Path, frm: str = "old", to: str = "new") -> RenameConfig:
    yaml_text = (
        "mappings:\n"
        f"  - from: \"{frm}\"\n"
        f"    to: \"{to}\"\n"
        "exceptions: []\n"
        "skip_contexts: []\n"
    )
    cfg_file = tmp_path / "_cfg.yaml"
    cfg_file.write_text(yaml_text, encoding="utf-8")
    return RenameConfig.load(cfg_file)


def _config_multi(tmp_path: Path) -> RenameConfig:
    cfg_file = tmp_path / "_cfg_multi.yaml"
    cfg_file.write_text(_MULTI_MAPPING_YAML, encoding="utf-8")
    return RenameConfig.load(cfg_file)


def _config_exception(tmp_path: Path) -> RenameConfig:
    cfg_file = tmp_path / "_cfg_exc.yaml"
    cfg_file.write_text(_EXCEPTION_YAML, encoding="utf-8")
    return RenameConfig.load(cfg_file)


# ---------------------------------------------------------------------------
# Test 1 — Single file rename
# ---------------------------------------------------------------------------


def test_single_file_renamed(tmp_path: Path) -> None:
    """A single file whose basename contains the mapping key is renamed."""
    root = tmp_path / "root"
    root.mkdir()

    source = root / "old_state.py"
    source.write_text("# placeholder", encoding="utf-8")

    cfg = _config_single(tmp_path)
    result = FilenamePass(cfg).run(root)

    expected = root / "new_state.py"
    assert expected.exists(), "target file must exist after rename"
    assert not source.exists(), "source file must no longer exist after rename"
    assert result == [expected], "returned list must contain the new path"


# ---------------------------------------------------------------------------
# Test 2 — Nested tree, all eligible files renamed, parent dirs untouched
# ---------------------------------------------------------------------------


def test_nested_tree_renamed(tmp_path: Path) -> None:
    """Multiple files in a nested tree are all renamed; parent dirs are not."""
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)

    (root / "old_alpha.py").write_text("a", encoding="utf-8")
    (root / "sub" / "old_beta.md").write_text("b", encoding="utf-8")
    (root / "sub" / "unchanged.txt").write_text("c", encoding="utf-8")

    cfg = _config_single(tmp_path)
    result = FilenamePass(cfg).run(root)

    assert (root / "new_alpha.py").exists()
    assert (root / "sub" / "new_beta.md").exists()
    assert (root / "sub" / "unchanged.txt").exists()

    # Parent directory name must NOT be changed by this pass
    assert (root / "sub").is_dir(), "directory 'sub' must survive untouched"

    new_paths = {p for p in result}
    assert root / "new_alpha.py" in new_paths
    assert root / "sub" / "new_beta.md" in new_paths
    # unchanged.txt must not appear
    assert not any("unchanged" in str(p) for p in result)


# ---------------------------------------------------------------------------
# Test 3 — Exception glob skips the file
# ---------------------------------------------------------------------------


def test_exception_glob_skips_file(tmp_path: Path) -> None:
    """A file whose relative path matches an exception glob is not renamed."""
    root = tmp_path / "root"
    keep_dir = root / "keep"
    keep_dir.mkdir(parents=True)

    protected = keep_dir / "old_config.py"
    protected.write_text("x", encoding="utf-8")

    cfg = _config_exception(tmp_path)
    result = FilenamePass(cfg).run(root)

    # File must still exist at original path
    assert protected.exists(), "exception-matched file must not be renamed"
    assert result == [], "no files should have been renamed"


# ---------------------------------------------------------------------------
# Test 4 — System directories are skipped
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "skip_dir",
    [".git", ".venv", ".argo", "__pycache__", "node_modules"],
)
def test_system_directories_skipped(tmp_path: Path, skip_dir: str) -> None:
    """Files inside system directories are not renamed."""
    root = tmp_path / "root"
    sys_dir = root / skip_dir
    sys_dir.mkdir(parents=True)

    inside = sys_dir / "old_thing.py"
    inside.write_text("y", encoding="utf-8")

    cfg = _config_single(tmp_path)
    result = FilenamePass(cfg).run(root)

    assert inside.exists(), f"file inside {skip_dir!r} must not be renamed"
    assert result == []


# ---------------------------------------------------------------------------
# Test 5 — Bottom-up traversal: deepest files renamed first
# ---------------------------------------------------------------------------


def test_bottom_up_order(tmp_path: Path) -> None:
    """Deepest files are renamed before shallower ones.

    Strategy: record rename events via a custom traversal — we verify the
    final state matches bottom-up expectations.  We use a three-level nest
    so there is a clear deep vs. shallow distinction.

    Because FilenamePass performs atomic renames, we assert the order
    indirectly: if bottom-up order is wrong, a directory rename in T2.4
    running concurrently would invalidate paths.  For this pass, we verify
    the invariant by checking that all files are renamed correctly even in
    deep nests (which would break with top-down if a parent dir were renamed
    mid-walk — T2.4 concern, but the invariant matters here too).
    """
    root = tmp_path / "root"
    deep = root / "level1" / "level2"
    deep.mkdir(parents=True)

    # Place files at different depths
    shallow = root / "old_shallow.py"
    mid = root / "level1" / "old_mid.py"
    deep_file = deep / "old_deep.py"

    for f in (shallow, mid, deep_file):
        f.write_text("z", encoding="utf-8")

    cfg = _config_single(tmp_path)
    result = FilenamePass(cfg).run(root)

    # All files must be renamed
    assert (root / "new_shallow.py").exists()
    assert (root / "level1" / "new_mid.py").exists()
    assert (deep / "new_deep.py").exists()
    assert len(result) == 3

    # Verify bottom-up invariant: deep file appears before shallow in result
    result_strs = [str(p) for p in result]
    deep_idx = next(i for i, s in enumerate(result_strs) if "new_deep" in s)
    shallow_idx = next(i for i, s in enumerate(result_strs) if "new_shallow" in s)
    assert deep_idx < shallow_idx, (
        "bottom-up: deeper file must appear earlier in result than shallower one"
    )


# ---------------------------------------------------------------------------
# Test 6 — Collision raises RenameConflictError
# ---------------------------------------------------------------------------


def test_collision_raises_conflict_error(tmp_path: Path) -> None:
    """If the target path already exists, RenameConflictError is raised."""
    root = tmp_path / "root"
    root.mkdir()

    source = root / "old_item.py"
    source.write_text("source", encoding="utf-8")

    # Pre-create the target
    collision = root / "new_item.py"
    collision.write_text("existing", encoding="utf-8")

    cfg = _config_single(tmp_path)
    with pytest.raises(RenameConflictError) as exc_info:
        FilenamePass(cfg).run(root)

    err = exc_info.value
    assert err.source == source, "source path must be recorded on the error"
    assert err.target == collision, "target path must be recorded on the error"


# ---------------------------------------------------------------------------
# Test 7 — Mapping ordering: longer key wins, does not double-apply shorter
# ---------------------------------------------------------------------------


def test_longer_mapping_wins(tmp_path: Path) -> None:
    """A file 'oldlong_name.py' should become 'NEW_LONG_name.py'.

    Mappings: oldlong → NEW_LONG, old → new (longer applied first).
    The shorter mapping must NOT re-apply to the already-replaced portion.
    """
    root = tmp_path / "root"
    root.mkdir()

    source = root / "oldlong_name.py"
    source.write_text("content", encoding="utf-8")

    cfg = _config_multi(tmp_path)
    result = FilenamePass(cfg).run(root)

    expected = root / "NEW_LONG_name.py"
    assert expected.exists(), "longer mapping must win: 'oldlong' → 'NEW_LONG'"
    assert not (root / "new_long_name.py").exists(), "shorter mapping must not fire"
    assert not (root / "NEW_LONnew_name.py").exists(), "double-apply must not happen"
    assert result == [expected]


# ---------------------------------------------------------------------------
# Test 8 — No matching mapping → not renamed, not in returned list
# ---------------------------------------------------------------------------


def test_no_matching_mapping(tmp_path: Path) -> None:
    """A file whose basename contains no mapping key is left untouched."""
    root = tmp_path / "root"
    root.mkdir()

    untouched = root / "something_else.py"
    untouched.write_text("x", encoding="utf-8")

    cfg = _config_single(tmp_path)
    result = FilenamePass(cfg).run(root)

    assert untouched.exists(), "file with no match must not be renamed"
    assert result == [], "returned list must be empty when no renames occur"


# ---------------------------------------------------------------------------
# Test 9 — Directories are NOT renamed by this pass
# ---------------------------------------------------------------------------


def test_directories_not_renamed(tmp_path: Path) -> None:
    """Directories with a mapping key in their name are left alone by this pass.

    Only the FILE inside the directory should be renamed.
    """
    root = tmp_path / "root"
    old_dir = root / "old_subdir"
    old_dir.mkdir(parents=True)

    inside_file = old_dir / "old_module.py"
    inside_file.write_text("m", encoding="utf-8")

    cfg = _config_single(tmp_path)
    result = FilenamePass(cfg).run(root)

    # Directory must still exist under its original name
    assert old_dir.exists(), "directory must NOT be renamed by the filename pass"
    assert old_dir.is_dir()

    # The file inside must have been renamed
    assert (old_dir / "new_module.py").exists()
    assert not inside_file.exists()
    assert result == [old_dir / "new_module.py"]


# ---------------------------------------------------------------------------
# Test 10 — Symlinks are skipped
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not hasattr(os, "symlink"),
    reason="symlinks not available on this platform",
)
def test_symlinks_skipped(tmp_path: Path) -> None:
    """Symlinks are skipped by FilenamePass (not renamed).

    Rationale: renaming the symlink itself moves the pointer, not the target.
    The rename engine operates on the working tree as real files; symlinks are
    an edge case that could silently redirect writes.  Skipping is the safe
    choice.  T2.4 (directory pass) follows the same policy.
    """
    root = tmp_path / "root"
    real_dir = tmp_path / "real_dir"
    real_dir.mkdir(parents=True)
    root.mkdir()

    # Real file that acts as symlink target
    real_file = real_dir / "target.py"
    real_file.write_text("real content", encoding="utf-8")

    # Symlink inside root whose name contains the mapping key
    link = root / "old_link.py"
    link.symlink_to(real_file)

    cfg = _config_single(tmp_path)
    result = FilenamePass(cfg).run(root)

    # Symlink must survive under original name
    assert link.exists() or link.is_symlink(), "symlink must not be renamed"
    assert not (root / "new_link.py").exists(), "symlink must not produce a renamed version"
    assert result == [], "symlinks must not appear in returned list"
