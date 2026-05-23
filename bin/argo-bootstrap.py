#!/usr/bin/env python3
"""argo-bootstrap.py — perform the FIRST sync from upstream-mirror into main.

This script is a one-shot tool.  After it succeeds, the normal ``argo update``
cycle takes over.  It is safe to re-run: a second invocation detects that
bootstrap has already run (manifest present + no scaffolding collisions) and
exits cleanly.

Usage
-----
    python bin/argo-bootstrap.py [--upstream-branch <branch>] [--dry-run]

Options
-------
--upstream-branch   Name of the local branch tracking upstream/main.
                    Default: ``upstream-mirror``
--dry-run           Resolve preconditions and list collision targets, then
                    exit without modifying the working tree.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap path resolution — must work before the package is importable.
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).parent.resolve()
_REPO_ROOT = _SCRIPT_DIR.parent

# Add repo root to sys.path so we can import argo_sync without installing.
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from argo_sync.config import RenameConfig  # noqa: E402  (import after sys.path patch)
from argo_sync.engine import RenameEngine  # noqa: E402
from argo_sync.errors import BootstrapError  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Files/dirs from the M1 scaffolding that WILL collide with renamed upstream
# content and therefore must be removed before the merge.
_SCAFFOLDING_COLLISIONS = [
    # upstream's cli package will be renamed to argo_cli/
    "argo_cli",
    # Standard docs / packaging — upstream brings its own
    "README.md",
    "pyproject.toml",
]

# Files we KEEP regardless — these are argo-specific with no upstream twin.
# Listing them here is documentation-only; the deletion loop only touches
# _SCAFFOLDING_COLLISIONS.
_KEEP_ALWAYS = [
    "argo_sync",
    "bin/argo-sync",
    "argo-rename.yaml",
    ".shepherd",
    ".gitignore",
    "uv.lock",
    "tests",  # argo_sync tests — no upstream equivalent
]

_MANIFEST_ALREADY_EXISTS_MARKER = Path(".argo") / "sync-manifest.json"

# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _git(*args: str, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess[str]:
    cmd = ["git", "-C", str(_REPO_ROOT), *args]
    kwargs: dict[str, object] = {
        "text": True,
        "encoding": "utf-8",
    }
    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    return subprocess.run(cmd, check=check, **kwargs)  # type: ignore[call-overload]


def _git_out(*args: str) -> str:
    """Run git and return stdout stripped."""
    result = _git(*args, capture=True)
    return result.stdout.strip()


def _branch_exists(branch: str) -> bool:
    result = _git("rev-parse", "--verify", branch, check=False, capture=True)
    return result.returncode == 0


def _working_tree_clean() -> bool:
    out = _git_out("status", "--porcelain")
    return out == ""


def _current_branch() -> str:
    return _git_out("rev-parse", "--abbrev-ref", "HEAD")


def _resolve_sha(ref: str) -> str:
    return _git_out("rev-parse", ref)


# ---------------------------------------------------------------------------
# Precondition checks
# ---------------------------------------------------------------------------


def _check_is_argo_repo(repo_root: Path) -> None:
    """Fail loudly if cwd is not an argo-agent repository."""
    missing: list[str] = []
    for marker in ["argo_sync", "argo-rename.yaml", "bin/argo-sync"]:
        if not (repo_root / marker).exists():
            missing.append(marker)
    if missing:
        raise BootstrapError(
            f"Not an argo-agent repo — missing: {', '.join(missing)}",
            step="preconditions",
        )


def _check_on_main(repo_root: Path) -> None:  # noqa: ARG001
    branch = _current_branch()
    if branch != "main":
        raise BootstrapError(
            f"Must run on branch 'main', currently on '{branch}'",
            step="preconditions",
        )


def _check_clean_tree() -> None:
    if not _working_tree_clean():
        raise BootstrapError(
            "Working tree is dirty — commit or stash changes before bootstrapping.",
            step="preconditions",
        )


def _check_upstream_branch(upstream_branch: str) -> None:
    if not _branch_exists(upstream_branch):
        raise BootstrapError(
            f"Branch '{upstream_branch}' does not exist locally.  "
            "Fetch it with: git fetch upstream && git branch "
            f"{upstream_branch} upstream/main",
            step="preconditions",
        )


# ---------------------------------------------------------------------------
# Collision detection
# ---------------------------------------------------------------------------


def _list_collision_targets(repo_root: Path) -> list[Path]:
    """Return existing paths that would collide with upstream content."""
    targets: list[Path] = []
    for name in _SCAFFOLDING_COLLISIONS:
        p = repo_root / name
        if p.exists():
            targets.append(p)
    return targets


# ---------------------------------------------------------------------------
# Core steps
# ---------------------------------------------------------------------------


def _remove_scaffolding_collisions(repo_root: Path, targets: list[Path]) -> None:
    """Delete collision targets from the working tree (not yet staged)."""
    import shutil

    for target in targets:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()


def _stage_and_commit_deletions(targets: list[Path]) -> None:
    """Stage deleted files and create the pre-merge cleanup commit."""
    if not targets:
        return  # nothing to clean up

    names = [t.name for t in targets]
    _git("add", "-A")
    _git(
        "commit",
        "-m",
        "bootstrap: clear scaffolding files that overlap upstream",
    )
    print(f"  Removed scaffolding items: {', '.join(names)}")


def _merge_upstream(upstream_branch: str) -> None:
    """Merge upstream-mirror into main with theirs strategy."""
    _git(
        "merge",
        upstream_branch,
        "--allow-unrelated-histories",
        "-X", "theirs",
        "--no-edit",
        "-m", f"bootstrap: merge from {upstream_branch}",
    )
    print(f"  Merged {upstream_branch} into main.")


def _run_rename_engine(repo_root: Path, upstream_sha: str) -> Path:
    """Load config and run the rename engine; return manifest path."""
    config_path = repo_root / "argo-rename.yaml"
    config = RenameConfig.load(config_path)
    engine = RenameEngine(config)
    manifest_path = engine.apply_and_write_manifest(repo_root, upstream_sha=upstream_sha)
    return manifest_path


def _stage_and_commit_rename(upstream_sha: str, manifest_path: Path, files_count: int) -> None:
    """Stage all post-rename changes and create the bootstrap commit."""
    _git("add", "-A")
    short_sha = upstream_sha[:12]
    _git(
        "commit",
        "-m",
        f"bootstrap: initial argo rename from upstream@{short_sha}",
    )
    print(
        f"  Rename committed: {files_count} file(s) touched. "
        f"Manifest: {manifest_path.relative_to(_REPO_ROOT)}"
    )


# ---------------------------------------------------------------------------
# Already-bootstrapped detection
# ---------------------------------------------------------------------------


def _already_bootstrapped(repo_root: Path) -> bool:
    """Return True if the bootstrap has already been performed."""
    manifest = repo_root / _MANIFEST_ALREADY_EXISTS_MARKER
    return manifest.exists()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Bootstrap argo-agent from the upstream-mirror branch.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--upstream-branch",
        default="upstream-mirror",
        metavar="BRANCH",
        help="Local branch that tracks upstream/main (default: upstream-mirror).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print precondition results and collision targets; do not modify the tree.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:  # noqa: C901
    args = _parse_args(argv)
    upstream_branch: str = args.upstream_branch
    dry_run: bool = args.dry_run

    repo_root = _REPO_ROOT
    print(f"argo-bootstrap: repo root = {repo_root}")

    # ------------------------------------------------------------------
    # Step 1 — Preconditions
    # ------------------------------------------------------------------
    print("Step 1: Checking preconditions …")
    try:
        _check_is_argo_repo(repo_root)
        _check_on_main(repo_root)
        _check_clean_tree()
        _check_upstream_branch(upstream_branch)
    except BootstrapError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
    print("  Preconditions OK.")

    # ------------------------------------------------------------------
    # Step 2 — Resolve upstream SHA
    # ------------------------------------------------------------------
    print("Step 2: Resolving upstream SHA …")
    upstream_sha = _resolve_sha(upstream_branch)
    print(f"  {upstream_branch} → {upstream_sha[:12]}")

    # ------------------------------------------------------------------
    # Step 3 — List collision targets
    # ------------------------------------------------------------------
    print("Step 3: Identifying scaffolding collisions …")
    collision_targets = _list_collision_targets(repo_root)
    if collision_targets:
        for t in collision_targets:
            print(f"  Will remove: {t.relative_to(repo_root)}")
    else:
        print("  No collisions found.")

    if dry_run:
        print("--dry-run: stopping before any modifications.")
        return

    # ------------------------------------------------------------------
    # Idempotency guard — already bootstrapped?
    # ------------------------------------------------------------------
    if _already_bootstrapped(repo_root):
        print(
            "argo-bootstrap: manifest already exists — bootstrap was already performed. "
            "Nothing to do."
        )
        return

    # Save HEAD so we can roll back on error.
    orig_head = _resolve_sha("HEAD")

    try:
        # ------------------------------------------------------------------
        # Step 4 — Remove scaffolding collisions + commit
        # ------------------------------------------------------------------
        print("Step 4: Removing scaffolding collisions …")
        _remove_scaffolding_collisions(repo_root, collision_targets)
        _stage_and_commit_deletions(collision_targets)

        # ------------------------------------------------------------------
        # Step 5 — Merge upstream-mirror
        # ------------------------------------------------------------------
        print(f"Step 5: Merging {upstream_branch} …")
        _merge_upstream(upstream_branch)

        # ------------------------------------------------------------------
        # Step 6 — Run the rename engine
        # ------------------------------------------------------------------
        print("Step 6: Running rename engine …")
        manifest_path = _run_rename_engine(repo_root, upstream_sha)
        # Count files from manifest
        import json
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        files_count = len(manifest_data.get("files_touched", []))
        print(f"  Rename engine touched {files_count} file(s).")

        # ------------------------------------------------------------------
        # Step 7 — Stage and commit rename
        # ------------------------------------------------------------------
        print("Step 7: Committing rename …")
        _stage_and_commit_rename(upstream_sha, manifest_path, files_count)

    except Exception as exc:
        print(f"\nERROR during bootstrap: {exc}", file=sys.stderr)
        print("Attempting rollback to pre-bootstrap state …", file=sys.stderr)
        try:
            _git("reset", "--hard", orig_head)
            print("Rollback successful.", file=sys.stderr)
        except Exception as rollback_exc:
            print(
                f"Rollback also failed: {rollback_exc}  "
                "Manual intervention required.",
                file=sys.stderr,
            )
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 8 — Summary
    # ------------------------------------------------------------------
    print("\nargo-bootstrap complete!")
    print(f"  Files touched : {files_count}")
    print(f"  Manifest      : {manifest_path.relative_to(repo_root)}")
    print("\nNext steps:")
    print("  1. Review the rename diff:  git show HEAD")
    print("  2. Run the test suite:       uv run pytest")
    print("  3. Verify doctor clean:      argo doctor --static")
    print(f"  4. Tag the baseline:         git tag argo-v0.0.1-bootstrap")


if __name__ == "__main__":
    main()
