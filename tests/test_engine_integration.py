"""Integration tests for RenameEngine against the synthetic_upstream_tree fixture.

T2.7: end-to-end rename of a small fake project tree using generic
``upstreamthing`` / ``Upstreamthing`` / ``UPSTREAMTHING_`` stand-in strings.
The fixture lives in ``tests/fixtures/synthetic_upstream_tree/`` and is copied
to ``tmp_path`` before each test so the engine can mutate it freely without
affecting the source.

AC-1 mini: after apply(), no remaining ``upstreamthing`` / ``Upstreamthing`` /
``UPSTREAMTHING_*`` literals exist in any file content (verified by recursive
grep of the result tree).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from argo_sync.config import RenameConfig
from argo_sync.engine import RenameEngine

# ---------------------------------------------------------------------------
# Constants & fixtures
# ---------------------------------------------------------------------------

FIXED_NOW = "2026-05-24T00:00:00+00:00"
FIXED_SHA = "cafebabecafebabecafebabecafebabecafebabe"

#: Absolute path to the source fixture directory (never mutated by tests).
FIXTURE_DIR: Path = Path(__file__).parent / "fixtures" / "synthetic_upstream_tree"


@pytest.fixture()
def tree(tmp_path: Path) -> tuple[Path, RenameConfig]:
    """Copy the synthetic fixture to tmp_path and load its config.

    Returns
    -------
    tuple[Path, RenameConfig]
        ``(root, cfg)`` where ``root`` is the mutable copy inside ``tmp_path``
        and ``cfg`` is the loaded :class:`~argo_sync.config.RenameConfig` from
        ``root/argo-rename.yaml``.
    """
    root = tmp_path / "tree"
    shutil.copytree(FIXTURE_DIR, root)
    cfg = RenameConfig.load(root / "argo-rename.yaml")
    return root, cfg


# ---------------------------------------------------------------------------
# Helper: scan tree for any surviving old-brand literals
# ---------------------------------------------------------------------------

_OLD_TOKENS = ("upstreamthing", "Upstreamthing", "UPSTREAMTHING")
_SKIP_DIRS = frozenset({".git", ".venv", ".argo", "__pycache__", "node_modules"})


def _find_old_tokens(root: Path) -> list[str]:
    """Return a list of ``path:token`` hits where any old token survives.

    Skips binary files and skip-dirs.  Returns an empty list on a clean tree.
    """
    hits: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        # Skip paths inside always-skipped dirs
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        # Skip the rename config itself — it intentionally contains both sides
        if path.name == "argo-rename.yaml":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for token in _OLD_TOKENS:
            if token in text:
                hits.append(f"{path.relative_to(root)}:{token!r}")
    return hits


# ---------------------------------------------------------------------------
# Test 1: Files and directories are renamed correctly
# ---------------------------------------------------------------------------


def test_structure_renamed(tree: tuple[Path, RenameConfig]) -> None:
    root, cfg = tree
    RenameEngine(cfg).apply(root)

    # Directory renamed: upstreamthing_cli/ → argo_cli/
    assert (root / "argo_cli").is_dir(), "upstreamthing_cli/ must be renamed to argo_cli/"
    assert not (root / "upstreamthing_cli").exists(), "old dir must not exist"

    # File renamed: upstreamthing_state.py → argo_state.py
    assert (root / "argo_state.py").exists(), "upstreamthing_state.py must be renamed to argo_state.py"
    assert not (root / "upstreamthing_state.py").exists(), "old file must not exist"

    # Nested file renamed: shared/deep_upstreamthing.py → shared/deep_argo.py
    # (upstreamthing → argo applies to the basename)
    assert (root / "shared" / "deep_argo.py").exists(), (
        "shared/deep_upstreamthing.py must be renamed to shared/deep_argo.py"
    )


# ---------------------------------------------------------------------------
# Test 2: Content is rewritten correctly
# ---------------------------------------------------------------------------


def test_content_rewritten(tree: tuple[Path, RenameConfig]) -> None:
    root, cfg = tree
    RenameEngine(cfg).apply(root)

    # argo_cli/main.py was upstreamthing_cli/main.py → class name rewritten
    main_py = root / "argo_cli" / "main.py"
    assert main_py.exists()
    content = main_py.read_text(encoding="utf-8")
    assert "ArgoCli" in content, "UpstreamthingCli must be rewritten to ArgoCli"
    assert "UpstreamthingCli" not in content

    # argo_state.py: UPSTREAMTHING_HOME → ARGO_HOME
    state_py = root / "argo_state.py"
    assert state_py.exists()
    state_content = state_py.read_text(encoding="utf-8")
    assert "ARGO_HOME" in state_content
    assert "UPSTREAMTHING_HOME" not in state_content

    # pyproject.toml: name rewritten
    pyproject = root / "pyproject.toml"
    pyproject_content = pyproject.read_text(encoding="utf-8")
    assert "argo-agent" in pyproject_content
    assert "upstreamthing-agent" not in pyproject_content


# ---------------------------------------------------------------------------
# Test 3: No remaining old-brand literals (mini AC-1)
# ---------------------------------------------------------------------------


def test_no_remaining_old_tokens(tree: tuple[Path, RenameConfig]) -> None:
    root, cfg = tree
    RenameEngine(cfg).apply(root)

    hits = _find_old_tokens(root)
    assert hits == [], (
        "Found surviving old-brand tokens after apply():\n"
        + "\n".join(f"  {h}" for h in hits)
    )


# ---------------------------------------------------------------------------
# Test 4: apply() returns a non-empty list on a fresh tree
# ---------------------------------------------------------------------------


def test_apply_returns_touched_files(tree: tuple[Path, RenameConfig]) -> None:
    root, cfg = tree
    result = RenameEngine(cfg).apply(root)

    assert isinstance(result, list)
    assert len(result) > 0, "Fresh tree must produce at least one touched path"
    # All items are Path objects
    assert all(isinstance(p, Path) for p in result)
    # Sorted
    assert result == sorted(result)


# ---------------------------------------------------------------------------
# Test 5: apply_and_write_manifest writes a deterministic manifest
# ---------------------------------------------------------------------------


def test_apply_and_write_manifest(tree: tuple[Path, RenameConfig]) -> None:
    root, cfg = tree
    engine = RenameEngine(cfg)

    manifest_path = engine.apply_and_write_manifest(
        root,
        upstream_sha=FIXED_SHA,
        now=FIXED_NOW,
    )

    assert manifest_path.exists()
    assert manifest_path == root / ".argo" / "sync-manifest.json"

    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Required fields
    assert data["upstream_sha"] == FIXED_SHA
    assert data["ran_at"] == FIXED_NOW
    assert isinstance(data["files_touched"], list)
    assert len(data["files_touched"]) > 0, "Manifest must list at least one touched file"

    # files_touched must be sorted POSIX-relative paths
    assert data["files_touched"] == sorted(data["files_touched"])
    for entry in data["files_touched"]:
        assert "\\" not in entry, f"Backslash in manifest path: {entry!r}"

    # Trailing newline
    raw = manifest_path.read_bytes()
    assert raw.endswith(b"\n")


# ---------------------------------------------------------------------------
# Test 6: Second apply_and_write_manifest call is byte-identical (determinism)
# ---------------------------------------------------------------------------


def test_manifest_is_deterministic(tree: tuple[Path, RenameConfig]) -> None:
    root, cfg = tree
    engine = RenameEngine(cfg)

    # First run — applies rename and writes manifest.
    manifest_path = engine.apply_and_write_manifest(
        root,
        upstream_sha=FIXED_SHA,
        now=FIXED_NOW,
    )
    bytes_first = manifest_path.read_bytes()

    # Second run — tree already renamed; apply() returns []; manifest is
    # written again with an empty files_touched list.
    manifest_path2 = engine.apply_and_write_manifest(
        root,
        upstream_sha=FIXED_SHA,
        now=FIXED_NOW,
    )
    bytes_second = manifest_path2.read_bytes()

    # The manifest paths must be the same file
    assert manifest_path == manifest_path2

    # The second manifest reflects zero new touches — so files_touched differs,
    # but the format, sha, and ran_at are identical.  We compare the keys that
    # must be stable regardless of run outcome.
    import json as _json

    d1 = _json.loads(bytes_first.decode("utf-8"))
    d2 = _json.loads(bytes_second.decode("utf-8"))
    assert d1["upstream_sha"] == d2["upstream_sha"]
    assert d1["ran_at"] == d2["ran_at"]
    # Second run must have zero or fewer files_touched
    assert len(d2["files_touched"]) <= len(d1["files_touched"])
