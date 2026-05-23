"""Idempotency tests for RenameEngine — AC-3 (synthetic fixtures).

T2.8: prove that running RenameEngine.apply() twice on the same tree:
  - returns an empty result on the second run,
  - leaves the filesystem byte-identical after both runs,
  - produces byte-identical manifests when now= is fixed.

The real-tree version (against an actual upstream checkout) comes in M3.

Test design
-----------
*Run 1* — Apply the rename against a fresh copy of the synthetic fixture.
  Captures ``touched_first`` (must be non-empty) and a content snapshot.

*Run 2* — Apply again on the already-renamed tree.
  Captures ``touched_second`` (must be empty) and a second content snapshot.

Content snapshot: a dict ``{relative_posix_path: sha256_hex}`` for every
file (excluding ``.argo/`` which is mutated by the manifest writer).

Byte-identical assertion: snapshot after run 1 == snapshot after run 2
for all files that are not the manifest file itself (which is intentionally
re-written on each call to apply_and_write_manifest).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from argo_sync.config import RenameConfig
from argo_sync.engine import RenameEngine

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FIXED_NOW = "2026-05-24T00:00:00+00:00"
FIXED_SHA = "deadbeef" * 5  # 40 hex chars

FIXTURE_DIR: Path = Path(__file__).parent / "fixtures" / "synthetic_upstream_tree"

_SKIP_DIRS = frozenset({".git", ".venv", "__pycache__", "node_modules"})
# The .argo/ dir holds the manifest — intentionally mutated; excluded from
# the snapshot that we use to check "all other files are unchanged".
_SNAPSHOT_SKIP_DIRS = frozenset({".git", ".venv", "__pycache__", "node_modules", ".argo"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snapshot(root: Path, *, skip_dirs: frozenset[str] = _SNAPSHOT_SKIP_DIRS) -> dict[str, str]:
    """Return ``{posix_rel_path: sha256_hex}`` for every file under *root*.

    Directories and symlinks are excluded.  Directories listed in *skip_dirs*
    are not descended into.
    """
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_dir() or path.is_symlink():
            continue
        if any(part in skip_dirs for part in path.relative_to(root).parts):
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        result[path.relative_to(root).as_posix()] = digest
    return result


@pytest.fixture()
def tree(tmp_path: Path) -> tuple[Path, RenameConfig]:
    """Copy the synthetic fixture to tmp_path and load its config."""
    root = tmp_path / "tree"
    shutil.copytree(FIXTURE_DIR, root)
    cfg = RenameConfig.load(root / "argo-rename.yaml")
    return root, cfg


# ---------------------------------------------------------------------------
# Test 1: Second apply() returns an empty list (AC-3 core assertion)
# ---------------------------------------------------------------------------


def test_second_apply_returns_empty(tree: tuple[Path, RenameConfig]) -> None:
    root, cfg = tree
    engine = RenameEngine(cfg)

    touched_first = engine.apply(root)
    assert len(touched_first) > 0, "Precondition: fresh tree must be touched"

    touched_second = engine.apply(root)
    assert touched_second == [], (
        f"Second apply() must return [] (AC-3 idempotency); got {touched_second!r}"
    )


# ---------------------------------------------------------------------------
# Test 2: File-system snapshot is byte-identical after run 1 and run 2
# ---------------------------------------------------------------------------


def test_filesystem_byte_identical_after_two_runs(
    tree: tuple[Path, RenameConfig],
) -> None:
    root, cfg = tree
    engine = RenameEngine(cfg)

    engine.apply(root)
    snapshot_after_run1 = _snapshot(root)

    engine.apply(root)
    snapshot_after_run2 = _snapshot(root)

    assert snapshot_after_run1 == snapshot_after_run2, (
        "File-system snapshots differ between run 1 and run 2.  "
        "Changed paths:\n"
        + "\n".join(
            f"  {k}: {snapshot_after_run1.get(k)!r} → {snapshot_after_run2.get(k)!r}"
            for k in sorted(
                snapshot_after_run1.keys() | snapshot_after_run2.keys()
            )
            if snapshot_after_run1.get(k) != snapshot_after_run2.get(k)
        )
    )


# ---------------------------------------------------------------------------
# Test 3: No new paths appear in the second snapshot (no phantom files)
# ---------------------------------------------------------------------------


def test_no_new_files_after_second_run(tree: tuple[Path, RenameConfig]) -> None:
    root, cfg = tree
    engine = RenameEngine(cfg)

    engine.apply(root)
    paths_after_run1 = set(_snapshot(root).keys())

    engine.apply(root)
    paths_after_run2 = set(_snapshot(root).keys())

    new_paths = paths_after_run2 - paths_after_run1
    assert not new_paths, f"Second run created unexpected files: {new_paths}"

    removed_paths = paths_after_run1 - paths_after_run2
    assert not removed_paths, f"Second run removed files: {removed_paths}"


# ---------------------------------------------------------------------------
# Test 4: apply_and_write_manifest idempotency — byte-identical manifests
#         when now= is fixed.
# ---------------------------------------------------------------------------


def test_manifest_idempotency(tree: tuple[Path, RenameConfig]) -> None:
    root, cfg = tree
    engine = RenameEngine(cfg)

    # Run 1 — renames the tree and writes manifest.
    manifest_path = engine.apply_and_write_manifest(
        root,
        upstream_sha=FIXED_SHA,
        now=FIXED_NOW,
    )
    bytes_run1 = manifest_path.read_bytes()

    # Run 2 — tree already renamed; apply() returns []; manifest rewritten.
    manifest_path2 = engine.apply_and_write_manifest(
        root,
        upstream_sha=FIXED_SHA,
        now=FIXED_NOW,
    )
    bytes_run2 = manifest_path2.read_bytes()

    assert manifest_path == manifest_path2

    # The manifest content WILL differ between the two runs because run 2
    # has an empty files_touched list.  However, the structural fields must
    # be stable.
    d1 = json.loads(bytes_run1.decode("utf-8"))
    d2 = json.loads(bytes_run2.decode("utf-8"))

    # upstream_sha and ran_at must be identical (deterministic fields).
    assert d1["upstream_sha"] == d2["upstream_sha"] == FIXED_SHA
    assert d1["ran_at"] == d2["ran_at"] == FIXED_NOW

    # Second run must have zero files_touched (engine saw nothing to change).
    assert d2["files_touched"] == [], (
        f"Second manifest must list no touched files; got {d2['files_touched']!r}"
    )

    # Running a third time (same tree, same args) must produce byte-identical
    # output to the second run — this is the "truly idempotent" assertion.
    manifest_path3 = engine.apply_and_write_manifest(
        root,
        upstream_sha=FIXED_SHA,
        now=FIXED_NOW,
    )
    bytes_run3 = manifest_path3.read_bytes()
    assert bytes_run2 == bytes_run3, (
        "Third manifest must be byte-identical to second (both see zero touches)"
    )


# ---------------------------------------------------------------------------
# Test 5: apply() result set grows no larger on a second pass
# ---------------------------------------------------------------------------


def test_touched_set_monotonically_shrinks(tree: tuple[Path, RenameConfig]) -> None:
    """Idempotency implies |touched_second| <= |touched_first|.

    In practice both should be 0 on the second run; this test is a softer
    assertion that at minimum we do not regress.
    """
    root, cfg = tree
    engine = RenameEngine(cfg)

    touched_first = set(engine.apply(root))
    touched_second = set(engine.apply(root))

    assert len(touched_second) <= len(touched_first), (
        f"Second run touched MORE files than first: {touched_second - touched_first}"
    )
    assert not touched_second, (
        f"Second run must touch zero files; touched: {touched_second!r}"
    )
