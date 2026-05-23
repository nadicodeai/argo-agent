"""Tests for argo_sync.engine.RenameEngine.

T2.6: engine orchestrator — content → filenames → directories.

The ordering test (test_apply_ordering_matters) sets up a tree where:
- A directory is named ``upstreamthing_cli/``
- That directory contains a file named ``upstreamthing_main.py``
- That file contains the text ``UPSTREAMTHING_HOME``

With mappings:
  upstreamthing_cli → argo_cli
  upstreamthing_main → argo_main   (file-level)
  UPSTREAMTHING_HOME → ARGO_HOME   (content-level)

Correct order (content → filenames → dirs):
  1. ContentPass rewrites ``UPSTREAMTHING_HOME`` inside the file while the
     directory is still named ``upstreamthing_cli/``.  The file itself is
     still named ``upstreamthing_main.py``.
  2. FilenamePass renames ``upstreamthing_main.py`` → ``argo_main.py`` (still
     inside ``upstreamthing_cli/``).
  3. DirectoryPass renames ``upstreamthing_cli/`` → ``argo_cli/``.

Wrong order (dirs first):
  Renaming the directory first invalidates the path used by ContentPass,
  so the content rewrite would walk the now-gone ``upstreamthing_cli/`` path
  and miss the file entirely (or os.walk on a fresh snapshot would find
  ``argo_cli/`` but still see ``upstreamthing_main.py`` without the POSIX
  content rewrite having run against it).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

from argo_sync.config import RenameConfig
from argo_sync.engine import RenameEngine
from argo_sync.manifest import ManifestWriter, SyncManifest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXED_NOW = "2026-05-24T00:00:00+00:00"
FIXED_SHA = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"


def _write_config(cfg_dir: Path, mappings: list[tuple[str, str]]) -> RenameConfig:
    data = {
        "mappings": [{"from": f, "to": t} for f, t in mappings],
        "exceptions": [],
        "skip_contexts": [],
    }
    cfg_file = cfg_dir / "argo-rename.yaml"
    cfg_file.write_text(yaml.dump(data), encoding="utf-8")
    return RenameConfig.load(cfg_file)


# ---------------------------------------------------------------------------
# Test: apply() with a trivial tree returns a sorted, deduplicated list[Path]
# ---------------------------------------------------------------------------


def test_apply_returns_sorted_list(tmp_path: Path) -> None:
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    root = tmp_path / "root"
    root.mkdir()

    # One file whose content changes, one whose name changes.
    (root / "alpha.txt").write_text("upstreamthing text", encoding="utf-8")
    (root / "upstreamthing_file.txt").write_text("no match content", encoding="utf-8")

    cfg = _write_config(
        cfg_dir,
        [("upstreamthing_file", "argo_file"), ("upstreamthing", "argo")],
    )

    result = RenameEngine(cfg).apply(root)

    assert isinstance(result, list)
    # All items are Path objects
    assert all(isinstance(p, Path) for p in result)
    # Sorted
    assert result == sorted(result)
    # No duplicates
    assert len(result) == len(set(result))


# ---------------------------------------------------------------------------
# Test: apply() — ordering matters (content → filenames → directories)
# ---------------------------------------------------------------------------


def test_apply_ordering_matters(tmp_path: Path) -> None:
    """Wrong pass order would fail: directory renamed before content walk."""
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    root = tmp_path / "root"
    pkg_dir = root / "upstreamthing_cli"
    pkg_dir.mkdir(parents=True)

    # File inside the directory that needs: content rewrite + filename rename
    src_file = pkg_dir / "upstreamthing_main.py"
    src_file.write_text(
        'UPSTREAMTHING_HOME = "~/.upstreamthing"\n',
        encoding="utf-8",
    )

    # Mappings — note "upstreamthing_cli" must be longest-from and is handled
    # by the config loader, but we list them in logical order for clarity.
    cfg = _write_config(
        cfg_dir,
        [
            ("UPSTREAMTHING_HOME", "ARGO_HOME"),
            ("upstreamthing_cli", "argo_cli"),
            ("upstreamthing_main", "argo_main"),
            ("upstreamthing", "argo"),
        ],
    )

    RenameEngine(cfg).apply(root)

    # After correct ordering:
    # 1. Content pass: file inside upstreamthing_cli/ rewrites UPSTREAMTHING_HOME
    # 2. Filename pass: upstreamthing_main.py → argo_main.py
    # 3. Directory pass: upstreamthing_cli/ → argo_cli/

    expected_file = root / "argo_cli" / "argo_main.py"
    assert expected_file.exists(), "File must exist at renamed path"
    content = expected_file.read_text(encoding="utf-8")
    assert "ARGO_HOME" in content, "Content rewrite must have run"
    assert "UPSTREAMTHING_HOME" not in content, "Old token must be gone"

    # Original dir/file must not exist
    assert not (root / "upstreamthing_cli").exists()


# ---------------------------------------------------------------------------
# Test: apply() returns all three categories of touched paths
# ---------------------------------------------------------------------------


def test_apply_collects_all_pass_results(tmp_path: Path) -> None:
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    root = tmp_path / "root"
    pkg_dir = root / "upstreamthing_pkg"
    pkg_dir.mkdir(parents=True)

    # Content-only change (no name change)
    f_content = root / "readme.txt"
    f_content.write_text("upstreamthing description", encoding="utf-8")

    # Filename-only change (no content match, no directory match)
    f_name = root / "upstreamthing_module.txt"
    f_name.write_text("no match here", encoding="utf-8")

    # File inside directory (directory will be renamed)
    f_in_dir = pkg_dir / "inner.txt"
    f_in_dir.write_text("nothing to rewrite", encoding="utf-8")

    cfg = _write_config(
        cfg_dir,
        [("upstreamthing_pkg", "argo_pkg"), ("upstreamthing_module", "argo_module"), ("upstreamthing", "argo")],
    )

    result = RenameEngine(cfg).apply(root)
    posix_paths = {Path(p).as_posix() for p in result}

    # Content-touched file (readme.txt) must appear
    assert any("readme.txt" in str(p) for p in result), "content-touched file missing"

    # Renamed file must appear (new name)
    assert any("argo_module.txt" in str(p) for p in result), "filename-renamed file missing"

    # Renamed directory must appear
    assert any("argo_pkg" in str(p) for p in result), "renamed directory missing"


# ---------------------------------------------------------------------------
# Test: apply_and_write_manifest writes .argo/sync-manifest.json
# ---------------------------------------------------------------------------


def test_apply_and_write_manifest(tmp_path: Path) -> None:
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    root = tmp_path / "root"
    root.mkdir()

    (root / "upstreamthing.txt").write_text("upstreamthing content", encoding="utf-8")

    cfg = _write_config(cfg_dir, [("upstreamthing", "argo")])

    engine = RenameEngine(cfg)
    manifest_path = engine.apply_and_write_manifest(
        root,
        upstream_sha=FIXED_SHA,
        now=FIXED_NOW,
    )

    assert manifest_path.exists()
    assert manifest_path.name == "sync-manifest.json"

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["upstream_sha"] == FIXED_SHA
    assert data["ran_at"] == FIXED_NOW
    assert isinstance(data["files_touched"], list)


# ---------------------------------------------------------------------------
# Test: apply() on an already-renamed tree returns []
# ---------------------------------------------------------------------------


def test_apply_idempotent_on_clean_tree(tmp_path: Path) -> None:
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    root = tmp_path / "root"
    root.mkdir()

    (root / "argo.txt").write_text("argo content", encoding="utf-8")

    cfg = _write_config(cfg_dir, [("upstreamthing", "argo")])

    result = RenameEngine(cfg).apply(root)
    assert result == [], "Already-renamed tree must produce empty result"
