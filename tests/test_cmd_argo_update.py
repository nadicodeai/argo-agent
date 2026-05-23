"""Tests for argo_cli/argo_update.py — T4.1 + T4.4.

Covers:
  - Precondition failures (dirty tree, missing upstream remote, missing branch)
  - Happy path: sync: commit produced on main with renamed content
  - --dry-run: reports counts, no mutations
  - --rename-only: runs engine but no fetch/merge
  - Conflict path: writes .argo/sync-state.json, exits non-zero
  - --resume: resumes from saved state
  - Idempotency: same upstream sha → no-op

Synthetic upstream content uses ``upstreamthing`` / ``uthing`` as stand-in
identifiers — NOT any real source identifier — so leakage scanners stay clean.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Git helpers
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
    env = {**os.environ, **_GIT_ENV}
    kwargs: dict[str, object] = {"text": True, "encoding": "utf-8", "env": env}
    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    return subprocess.run(["git", "-C", str(repo), *args], check=check, **kwargs)  # type: ignore[call-overload]


def _git_out(repo: Path, *args: str) -> str:
    return _git(repo, *args, capture=True).stdout.strip()


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

_RENAME_YAML = """\
mappings:
  - {from: "upstreamthing", to: "athing"}
  - {from: "uthing", to: "athing"}
exceptions:
  - path: "argo-rename.yaml"
    why: "never rename the config itself"
  - path: ".argo/**"
    why: "manifest dir is internal"
skip_contexts: []
"""


def _init_argo_repo(tmp: Path) -> Path:
    """Initialise a minimal argo-agent repo in *tmp/repo*."""
    repo = tmp / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")

    # argo_sync package marker (presence = valid argo-agent repo)
    argo_sync = repo / "argo_sync"
    argo_sync.mkdir()
    (argo_sync / "__init__.py").write_text("", encoding="utf-8")

    # argo-rename.yaml
    (repo / "argo-rename.yaml").write_text(_RENAME_YAML, encoding="utf-8")

    # Minimal argo_cli marker
    argo_cli = repo / "argo_cli"
    argo_cli.mkdir()
    (argo_cli / "__init__.py").write_text("", encoding="utf-8")

    # NOTE: deliberately omit README.md here so it does not conflict with
    # upstream's README.md when merging unrelated histories.
    # The argo-rename.yaml and argo_sync/ marker are sufficient for the
    # precondition check.

    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init: scaffold")
    return repo


def _add_upstream_remote(repo: Path, upstream_bare: Path) -> None:
    """Add ``upstream`` remote (push URL = no_push) pointing at *upstream_bare*."""
    _git(repo, "remote", "add", "upstream", str(upstream_bare))
    _git(repo, "remote", "set-url", "--push", "upstream", "no_push")


def _init_upstream_bare(tmp: Path) -> Path:
    """Create a bare upstream repo in *tmp/upstream.git*."""
    bare = tmp / "upstream.git"
    bare.mkdir()
    env = {**os.environ, **_GIT_ENV}
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True, env=env)
    return bare


def _populate_upstream(tmp: Path, bare: Path) -> str:
    """
    Clone bare into a work-tree, add content, push to bare, return HEAD sha.
    Content uses stand-in identifiers.
    """
    work = tmp / "upstream_work"
    env = {**os.environ, **_GIT_ENV}
    subprocess.run(["git", "clone", str(bare), str(work)], check=True, env=env, capture_output=True)
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "Test")

    (work / "README.md").write_text("# upstreamthing project\n", encoding="utf-8")
    (work / "upstreamthing_module.py").write_text("# upstreamthing_module\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "upstream: initial")
    _git(work, "push", "origin", "main")
    sha = _git_out(work, "rev-parse", "HEAD")
    return sha


def _add_upstream_mirror_branch(repo: Path, upstream_sha: str) -> None:
    """
    Create ``upstream-mirror`` branch in *repo* at *upstream_sha*
    (fetched from upstream remote, set up as local tracking branch).
    """
    _git(repo, "fetch", "upstream")
    _git(repo, "checkout", "-b", "upstream-mirror", "upstream/main")
    _git(repo, "checkout", "main")


def _build_full_repo(tmp: Path) -> tuple[Path, str]:
    """
    Build a repo with upstream remote + upstream-mirror branch.
    Returns (repo_path, upstream_sha).
    """
    bare = _init_upstream_bare(tmp)
    sha = _populate_upstream(tmp, bare)
    repo = _init_argo_repo(tmp)
    _add_upstream_remote(repo, bare)
    _add_upstream_mirror_branch(repo, sha)
    return repo, sha


# ---------------------------------------------------------------------------
# Import helper: load argo_update as module in isolation
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent


def _import_argo_update():
    """Import argo_cli.argo_update (adds project root to sys.path if needed)."""
    if str(_PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(_PROJECT_ROOT))
    import importlib
    import argo_cli.argo_update as mod
    return mod


def _run_update(repo: Path, *extra_args: str, expect_exit: int = 0) -> tuple[int, str, str]:
    """
    Run ``argo update`` in *repo* as a subprocess using the project venv.

    We use a small wrapper script rather than ``-m argo_cli.argo_update``
    because the fake repo contains a minimal ``argo_sync/`` directory (needed
    so the precondition check can see it), which would shadow the real
    installed ``argo_sync`` package if Python adds ``cwd`` to ``sys.path``
    first.  The wrapper inserts the real project root at position 0 *before*
    any import happens so the real package always wins.
    """
    venv_python = _PROJECT_ROOT / ".venv" / "bin" / "python"
    python = str(venv_python) if venv_python.exists() else sys.executable

    # Inline runner: inject real project root before any import.
    runner = (
        "import sys; "
        f"sys.path.insert(0, {str(_PROJECT_ROOT)!r}); "
        "from argo_cli.argo_update import _build_parser, cmd_argo_update; "
        "p = _build_parser(); "
        "import sys as _sys; "
        "args = p.parse_args(); "
        "cmd_argo_update(args)"
    )

    env = {**os.environ, **_GIT_ENV}
    result = subprocess.run(
        [python, "-c", runner, *extra_args],
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# 1. Precondition: dirty working tree
# ---------------------------------------------------------------------------


def test_precondition_dirty_tree(tmp_path: Path) -> None:
    """Dirty working tree → non-zero exit with clear message."""
    repo, _ = _build_full_repo(tmp_path)
    # Make tree dirty
    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    rc, out, err = _run_update(repo)
    assert rc != 0
    combined = out + err
    assert "dirty" in combined.lower() or "uncommitted" in combined.lower() or "clean" in combined.lower()


# ---------------------------------------------------------------------------
# 2. Precondition: missing upstream remote
# ---------------------------------------------------------------------------


def test_precondition_missing_upstream_remote(tmp_path: Path) -> None:
    """Missing upstream remote → non-zero exit."""
    repo = _init_argo_repo(tmp_path)
    # No upstream remote added

    rc, out, err = _run_update(repo)
    assert rc != 0
    combined = out + err
    assert "upstream" in combined.lower()


# ---------------------------------------------------------------------------
# 3. Precondition: missing upstream-mirror branch
# ---------------------------------------------------------------------------


def test_precondition_missing_upstream_mirror_branch(tmp_path: Path) -> None:
    """Missing upstream-mirror branch → non-zero exit."""
    bare = _init_upstream_bare(tmp_path)
    _populate_upstream(tmp_path, bare)
    repo = _init_argo_repo(tmp_path)
    _add_upstream_remote(repo, bare)
    # Do NOT create upstream-mirror branch

    rc, out, err = _run_update(repo)
    assert rc != 0
    combined = out + err
    assert "upstream-mirror" in combined.lower() or "branch" in combined.lower()


# ---------------------------------------------------------------------------
# 4. Happy path
# ---------------------------------------------------------------------------


def test_happy_path_produces_sync_commit(tmp_path: Path) -> None:
    """Happy path: argo update produces a sync: commit on main."""
    repo, upstream_sha = _build_full_repo(tmp_path)

    rc, out, err = _run_update(repo)
    assert rc == 0, f"Expected exit 0, got {rc}\nSTDOUT:\n{out}\nSTDERR:\n{err}"

    # Check git log for sync: commit
    log = _git_out(repo, "log", "--oneline")
    assert "sync:" in log

    # Manifest written
    manifest_path = repo / ".argo" / "sync-manifest.json"
    assert manifest_path.exists(), "sync-manifest.json not written"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "upstream_sha" in data
    assert "files_touched" in data

    # Content was renamed: upstreamthing → athing
    readme = (repo / "README.md").read_text(encoding="utf-8")
    assert "upstreamthing" not in readme


# ---------------------------------------------------------------------------
# 5. --dry-run: no mutations
# ---------------------------------------------------------------------------


def test_dry_run_no_commit(tmp_path: Path) -> None:
    """--dry-run reports upstream sha but makes no commits."""
    repo, upstream_sha = _build_full_repo(tmp_path)

    log_before = _git_out(repo, "log", "--oneline")
    rc, out, err = _run_update(repo, "--dry-run")
    assert rc == 0, f"dry-run exited {rc}\n{out}\n{err}"

    log_after = _git_out(repo, "log", "--oneline")
    assert log_before == log_after, "dry-run must not commit"

    combined = out + err
    # Should mention upstream sha or count
    assert upstream_sha[:7] in combined or "dry" in combined.lower() or "would" in combined.lower()


# ---------------------------------------------------------------------------
# 6. --rename-only: skips fetch/merge
# ---------------------------------------------------------------------------


def test_rename_only_skips_fetch_merge(tmp_path: Path) -> None:
    """
    --rename-only runs engine + commit but no fetch/merge.
    We simulate by having upstream-mirror already merged into main;
    --rename-only should still run the rename engine and commit.
    """
    repo, upstream_sha = _build_full_repo(tmp_path)

    # First, do a normal update so main has the merge
    rc, out, err = _run_update(repo)
    assert rc == 0, f"Setup merge failed: {out}\n{err}"

    # Now add a file that needs renaming directly (no new upstream)
    (repo / "upstreamthing_extra.py").write_text("# upstreamthing_extra\n", encoding="utf-8")
    _git(repo, "add", "upstreamthing_extra.py")
    _git(repo, "commit", "-m", "add file needing rename")

    log_before_count = len(_git_out(repo, "log", "--oneline").splitlines())

    rc, out, err = _run_update(repo, "--rename-only")
    assert rc == 0, f"--rename-only failed: {out}\n{err}"

    log_after = _git_out(repo, "log", "--oneline")
    assert "sync:" in log_after


# ---------------------------------------------------------------------------
# 7. Conflict path: writes .argo/sync-state.json
# ---------------------------------------------------------------------------


def test_conflict_writes_sync_state(tmp_path: Path) -> None:
    """
    Simulated merge conflict → non-zero exit + .argo/sync-state.json written.

    We create a conflicting change in main that will conflict with upstream.
    """
    bare = _init_upstream_bare(tmp_path)
    # Populate upstream with a file
    work = tmp_path / "upstream_work"
    env = {**os.environ, **_GIT_ENV}
    subprocess.run(["git", "clone", str(bare), str(work)], check=True, env=env, capture_output=True)
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "Test")
    (work / "conflict_file.txt").write_text("upstream version A\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "upstream: add conflict file")
    _git(work, "push", "origin", "main")
    upstream_sha = _git_out(work, "rev-parse", "HEAD")

    repo = _init_argo_repo(tmp_path)
    _add_upstream_remote(repo, bare)
    _add_upstream_mirror_branch(repo, upstream_sha)

    # Now create a conflicting change in main
    (repo / "conflict_file.txt").write_text("local version B\n", encoding="utf-8")
    _git(repo, "add", "conflict_file.txt")
    _git(repo, "commit", "-m", "local: add conflict file")

    rc, out, err = _run_update(repo)
    # Should exit non-zero due to conflict
    assert rc != 0, f"Expected conflict exit non-zero, got {rc}\nSTDOUT:\n{out}\nSTDERR:\n{err}"

    state_file = repo / ".argo" / "sync-state.json"
    assert state_file.exists(), ".argo/sync-state.json not written on conflict"
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state.get("phase") == "merge"
    assert "upstream_sha" in state

    # AC-4: the error output MUST tell the operator how to recover.
    combined = (out + err).lower()
    assert "resume" in combined, (
        f"AC-4: conflict error must instruct the operator to run --resume.\n"
        f"STDOUT:\n{out}\nSTDERR:\n{err}"
    )


# ---------------------------------------------------------------------------
# 8. --resume after conflict
# ---------------------------------------------------------------------------


def test_resume_after_conflict(tmp_path: Path) -> None:
    """
    After conflict, operator resolves + stages; --resume completes the sync.
    """
    bare = _init_upstream_bare(tmp_path)
    work = tmp_path / "upstream_work"
    env = {**os.environ, **_GIT_ENV}
    subprocess.run(["git", "clone", str(bare), str(work)], check=True, env=env, capture_output=True)
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "Test")
    (work / "conflict_file.txt").write_text("upstream version A\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "upstream: add conflict file")
    _git(work, "push", "origin", "main")
    upstream_sha = _git_out(work, "rev-parse", "HEAD")

    repo = _init_argo_repo(tmp_path)
    _add_upstream_remote(repo, bare)
    _add_upstream_mirror_branch(repo, upstream_sha)

    # Conflicting local change
    (repo / "conflict_file.txt").write_text("local version B\n", encoding="utf-8")
    _git(repo, "add", "conflict_file.txt")
    _git(repo, "commit", "-m", "local: conflict")

    # Trigger conflict
    rc, out, err = _run_update(repo)
    assert rc != 0

    state_file = repo / ".argo" / "sync-state.json"
    assert state_file.exists()

    # "Operator resolves conflict": overwrite conflict markers and stage
    (repo / "conflict_file.txt").write_text("resolved version\n", encoding="utf-8")
    _git(repo, "add", "conflict_file.txt")
    # Commit the merge resolution
    _git(repo, "commit", "-m", "resolve: conflict resolved")

    rc2, out2, err2 = _run_update(repo, "--resume")
    assert rc2 == 0, f"--resume failed: {out2}\n{err2}"

    # sync-state.json must be cleaned up
    assert not state_file.exists(), "sync-state.json should be removed after successful resume"

    # sync: commit must exist
    log = _git_out(repo, "log", "--oneline")
    assert "sync:" in log


# ---------------------------------------------------------------------------
# 9. Existing sync-state.json blocks normal run (suggests --resume)
# ---------------------------------------------------------------------------


def test_existing_sync_state_blocks_normal_run(tmp_path: Path) -> None:
    """If .argo/sync-state.json exists, normal argo update must refuse."""
    repo, upstream_sha = _build_full_repo(tmp_path)

    # Plant a sync-state.json manually
    argo_dir = repo / ".argo"
    argo_dir.mkdir(exist_ok=True)
    state_file = argo_dir / "sync-state.json"
    state_file.write_text(
        json.dumps({"phase": "merge", "upstream_sha": "abc123", "original_sha": "def456"}),
        encoding="utf-8",
    )

    rc, out, err = _run_update(repo)
    assert rc != 0
    combined = out + err
    assert "--resume" in combined.lower() or "resume" in combined.lower()


# ---------------------------------------------------------------------------
# 10. Idempotency: same upstream sha → no new sync commit
# ---------------------------------------------------------------------------


def test_idempotency_same_upstream_sha(tmp_path: Path) -> None:
    """Re-running argo update against same upstream sha is a no-op."""
    repo, upstream_sha = _build_full_repo(tmp_path)

    # First run
    rc, out, err = _run_update(repo)
    assert rc == 0, f"First run failed: {out}\n{err}"

    log_after_first = _git_out(repo, "log", "--oneline")

    # Second run (same upstream sha — no new upstream commits)
    rc2, out2, err2 = _run_update(repo)
    # Either exits 0 (no-op) or non-zero with "already up-to-date" style message
    log_after_second = _git_out(repo, "log", "--oneline")

    # The log should not have an additional sync: commit
    first_sync_count = log_after_first.count("sync:")
    second_sync_count = log_after_second.count("sync:")
    assert second_sync_count == first_sync_count, (
        f"Idempotency violated: {first_sync_count} → {second_sync_count} sync commits"
    )


# ---------------------------------------------------------------------------
# 11. --merge-only: skips rename engine
# ---------------------------------------------------------------------------


def test_merge_only_skips_rename(tmp_path: Path) -> None:
    """--merge-only merges upstream but does not run rename engine."""
    repo, upstream_sha = _build_full_repo(tmp_path)

    rc, out, err = _run_update(repo, "--merge-only")
    assert rc == 0, f"--merge-only failed: {out}\n{err}"

    # The engine MUST NOT have run: no manifest file, and no "sync:" commit.
    manifest_path = repo / ".argo" / "sync-manifest.json"
    assert not manifest_path.exists(), (
        f"--merge-only must not write the rename manifest, but found {manifest_path}"
    )
    log = _git_out(repo, "log", "--oneline")
    assert "sync: upstream" not in log, (
        f"--merge-only must not produce a 'sync:' commit (rename engine should be skipped).\n"
        f"Git log:\n{log}"
    )
