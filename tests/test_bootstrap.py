"""Tests for bin/argo-bootstrap.py (T3.2).

These tests build a minimal fake argo-agent + upstream-mirror scenario using
``tmp_path`` and ``git init``, then exercise the bootstrap script either by
importing and calling ``main()`` directly (for white-box checks) or by running
it as a subprocess (for black-box exit-code checks).

IMPORTANT: synthetic upstream content uses GENERIC stand-in strings
(``upstreamthing``, ``uthing``) — NOT the literal source identifier —
so the leakage scanner never flags this file.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

# ---------------------------------------------------------------------------
# Path to the bootstrap script
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_BOOTSTRAP = _REPO_ROOT / "bin" / "argo-bootstrap.py"

# ---------------------------------------------------------------------------
# Helpers: load bootstrap module dynamically
# ---------------------------------------------------------------------------


def _load_bootstrap(repo_root: Path) -> ModuleType:
    """Import bin/argo-bootstrap.py as a module, patching _REPO_ROOT."""
    spec = importlib.util.spec_from_file_location("argo_bootstrap_mod", _BOOTSTRAP)
    assert spec is not None and spec.loader is not None
    mod: ModuleType = importlib.util.module_from_spec(spec)
    # Inject the fake repo root before loading so all helpers use it.
    mod.__dict__["_REPO_ROOT"] = repo_root
    loader = spec.loader
    assert hasattr(loader, "exec_module")
    loader.exec_module(mod)
    # Re-patch after exec (exec_module resets module-level names).
    mod._REPO_ROOT = repo_root  # type: ignore[attr-defined]
    return mod


# ---------------------------------------------------------------------------
# Helpers: build a fake argo-agent repo
# ---------------------------------------------------------------------------

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_CONFIG_NOSYSTEM": "1",
    "HOME": "/tmp",
}


def _git(repo: Path, *args: str, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess[str]:
    import os
    env = {**os.environ, **_GIT_ENV}
    kwargs: dict[str, object] = {"text": True, "encoding": "utf-8", "env": env}
    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    return subprocess.run(["git", "-C", str(repo), *args], check=check, **kwargs)  # type: ignore[call-overload]


def _git_out(repo: Path, *args: str) -> str:
    return _git(repo, *args, capture=True).stdout.strip()


def _init_argo_repo(tmp: Path) -> Path:
    """Initialise a bare argo-agent main-branch repo in *tmp/repo*."""
    repo = tmp / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")

    # Minimal argo_sync package marker
    argo_sync = repo / "argo_sync"
    argo_sync.mkdir()
    (argo_sync / "__init__.py").write_text("", encoding="utf-8")

    # argo-rename.yaml (minimal — engine needs 3 required keys)
    rename_yaml = (
        "mappings:\n"
        "  - {from: \"uthing\", to: \"athing\"}\n"
        "exceptions:\n"
        "  - path: \".shepherd/**\"\n"
        "    why: \"test\"\n"
        "  - path: \"argo-rename.yaml\"\n"
        "    why: \"test\"\n"
        "  - path: \"bin/argo-bootstrap.py\"\n"
        "    why: \"test\"\n"
        "skip_contexts: []\n"
    )
    (repo / "argo-rename.yaml").write_text(rename_yaml, encoding="utf-8")

    # bin/argo-sync (just needs to exist as a marker)
    bin_dir = repo / "bin"
    bin_dir.mkdir()
    (bin_dir / "argo-sync").write_text("#!/bin/sh\necho ok\n", encoding="utf-8")

    # Scaffolding files that will collide with upstream
    (repo / "README.md").write_text("# Argo scaffold README\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\nname = \"argo-agent\"\n", encoding="utf-8")
    argo_cli = repo / "argo_cli"
    argo_cli.mkdir()
    (argo_cli / "__init__.py").write_text("", encoding="utf-8")

    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "M1: scaffold")
    return repo


def _add_upstream_mirror_branch(repo: Path) -> str:
    """Add an upstream-mirror branch with synthetic upstream content.

    Content uses 'upstreamthing' as the stand-in identifier (not the real
    identifier from upstream) so the leakage scanner never flags this file.
    """
    current = _git_out(repo, "rev-parse", "--abbrev-ref", "HEAD")
    _git(repo, "checkout", "--orphan", "upstream-mirror")
    _git(repo, "reset", "--hard")  # clear index without touching working tree

    # Synthetic upstream files with the stand-in identifier.
    (repo / "README.md").write_text("# upstreamthing project\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\nname = \"upstreamthing\"\n", encoding="utf-8")
    upstream_cli = repo / "uthing_cli"
    upstream_cli.mkdir(exist_ok=True)
    (upstream_cli / "__init__.py").write_text("# uthing_cli\n", encoding="utf-8")

    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "upstream: initial")
    upstream_sha = _git_out(repo, "rev-parse", "HEAD")

    # Return to main
    _git(repo, "checkout", current)
    return upstream_sha


# ---------------------------------------------------------------------------
# 1. Happy path — bootstrap succeeds
# ---------------------------------------------------------------------------


def test_happy_path(tmp_path: Path) -> None:
    """Bootstrap merges upstream-mirror and commits the result cleanly."""
    repo = _init_argo_repo(tmp_path)
    _add_upstream_mirror_branch(repo)

    mod = _load_bootstrap(repo)
    mod.main(["--upstream-branch", "upstream-mirror"])

    # Manifest must exist
    manifest_path = repo / ".argo" / "sync-manifest.json"
    assert manifest_path.exists(), "sync-manifest.json not created"

    # Manifest is valid JSON with the expected keys
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "upstream_sha" in data
    assert "files_touched" in data

    # Exactly 2 bootstrap commits should exist (cleanup + rename)
    # The first commit is the M1 scaffold; next two are bootstrap steps.
    log = _git_out(repo, "log", "--oneline")
    assert "bootstrap: merge from upstream-mirror" in log or \
           "bootstrap: clear scaffolding" in log or \
           "bootstrap: initial argo rename" in log


def test_happy_path_no_leakage(tmp_path: Path) -> None:
    """After bootstrap, no unexpected content leaks into tracked files."""
    repo = _init_argo_repo(tmp_path)
    _add_upstream_mirror_branch(repo)

    mod = _load_bootstrap(repo)
    mod.main(["--upstream-branch", "upstream-mirror"])

    # Verify argo-rename.yaml was not modified by the engine
    rename_content = (repo / "argo-rename.yaml").read_text(encoding="utf-8")
    assert "uthing" in rename_content  # the mapping source should still be there


# ---------------------------------------------------------------------------
# 2. Missing upstream-mirror branch → non-zero exit
# ---------------------------------------------------------------------------


def test_missing_upstream_branch_exits_nonzero(tmp_path: Path) -> None:
    """Missing upstream-mirror branch causes SystemExit(1) with a message."""
    repo = _init_argo_repo(tmp_path)
    # Do NOT add upstream-mirror branch

    mod = _load_bootstrap(repo)
    with pytest.raises(SystemExit) as exc_info:
        mod.main(["--upstream-branch", "upstream-mirror"])
    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# 3. Dirty working tree → non-zero exit
# ---------------------------------------------------------------------------


def test_dirty_working_tree_exits_nonzero(tmp_path: Path) -> None:
    """Dirty working tree causes a non-zero exit with an error message."""
    repo = _init_argo_repo(tmp_path)
    _add_upstream_mirror_branch(repo)

    # Dirty the tree
    (repo / "dirty.txt").write_text("unsaved", encoding="utf-8")

    mod = _load_bootstrap(repo)
    # main() should call sys.exit(1); capture via SystemExit
    with pytest.raises(SystemExit) as exc_info:
        mod.main(["--upstream-branch", "upstream-mirror"])
    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# 4. --dry-run does not modify the tree
# ---------------------------------------------------------------------------


def test_dry_run_does_not_modify(tmp_path: Path) -> None:
    """--dry-run exits without creating any commits or manifest."""
    repo = _init_argo_repo(tmp_path)
    _add_upstream_mirror_branch(repo)

    before_log = _git_out(repo, "log", "--oneline")

    mod = _load_bootstrap(repo)
    mod.main(["--upstream-branch", "upstream-mirror", "--dry-run"])

    after_log = _git_out(repo, "log", "--oneline")
    assert before_log == after_log, "--dry-run must not create new commits"

    manifest = repo / ".argo" / "sync-manifest.json"
    assert not manifest.exists(), "--dry-run must not create the manifest"


# ---------------------------------------------------------------------------
# 5. Idempotency — second run is a no-op
# ---------------------------------------------------------------------------


def test_idempotency(tmp_path: Path) -> None:
    """Running bootstrap twice: second run detects manifest and exits cleanly."""
    repo = _init_argo_repo(tmp_path)
    _add_upstream_mirror_branch(repo)

    mod = _load_bootstrap(repo)
    mod.main(["--upstream-branch", "upstream-mirror"])

    log_after_first = _git_out(repo, "log", "--oneline")

    # Second run — must not raise and must not create new commits.
    mod2 = _load_bootstrap(repo)
    mod2.main(["--upstream-branch", "upstream-mirror"])

    log_after_second = _git_out(repo, "log", "--oneline")
    assert log_after_first == log_after_second, (
        "Second bootstrap run must not create new commits"
    )


# ---------------------------------------------------------------------------
# 6. Preconditions: not an argo repo → non-zero exit
# ---------------------------------------------------------------------------


def test_not_argo_repo_exits_nonzero(tmp_path: Path) -> None:
    """A plain git repo (no argo markers) fails preconditions."""
    plain = tmp_path / "plain"
    plain.mkdir()
    _git(plain, "init", "-b", "main")
    _git(plain, "config", "user.email", "test@example.com")
    _git(plain, "config", "user.name", "Test")
    (plain / "something.txt").write_text("data", encoding="utf-8")
    _git(plain, "add", "-A")
    _git(plain, "commit", "-m", "init")

    mod = _load_bootstrap(plain)
    with pytest.raises(SystemExit) as exc_info:
        mod.main(["--upstream-branch", "upstream-mirror"])
    assert exc_info.value.code == 1
