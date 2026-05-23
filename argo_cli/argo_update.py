"""argo update — upstream sync command (T4.1 + T4.4).

Replaces the former PyPI self-updater with argo-sync:
  fetch upstream → merge upstream-mirror → run RenameEngine → commit.

Entry points
------------
- ``cmd_argo_update(args)``  — argparse handler wired in ``argo_cli/main.py``
- ``__main__``               — ``python -m argo_cli.argo_update [flags]``

All domain errors are typed subclasses of :class:`argo_sync.errors.ArgoSyncError`
or ``UpstreamSyncError`` defined here.  Never ``raise Exception(...)``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from argo_sync.config import RenameConfig
from argo_sync.engine import RenameEngine
from argo_sync.errors import ArgoSyncError, UpstreamMergeConflict

# ---------------------------------------------------------------------------
# Typed errors
# ---------------------------------------------------------------------------


class UpstreamSyncError(ArgoSyncError):
    """Raised when a precondition or sync step fails in ``argo update``.

    Attributes
    ----------
    step:
        Short label for the stage that failed (e.g. ``"preconditions"``,
        ``"fetch"``, ``"merge"``).
    """

    def __init__(self, message: str, *, step: str = "sync") -> None:
        super().__init__(f"[{step}] {message}")
        self.step = step


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SYNC_STATE_REL = Path(".argo") / "sync-state.json"
_RENAME_YAML = "argo-rename.yaml"
_DEFAULT_UPSTREAM_BRANCH = "upstream-mirror"
_DEFAULT_TARGET_BRANCH = "main"

# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, object] = {
        "text": True,
        "encoding": "utf-8",
        "cwd": str(repo),
    }
    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    return subprocess.run(["git", *args], check=check, **kwargs)  # type: ignore[call-overload]


def _git_out(repo: Path, *args: str) -> str:
    return _git(repo, *args, capture=True).stdout.strip()


def _current_branch(repo: Path) -> str:
    return _git_out(repo, "rev-parse", "--abbrev-ref", "HEAD")


def _is_clean(repo: Path) -> bool:
    status = _git_out(repo, "status", "--porcelain")
    return status == ""


def _branch_exists_locally(repo: Path, branch: str) -> bool:
    result = _git(repo, "branch", "--list", branch, capture=True, check=False)
    return bool(result.stdout.strip())


def _remote_exists(repo: Path, remote: str) -> bool:
    result = _git(repo, "remote", "get-url", remote, capture=True, check=False)
    return result.returncode == 0


def _remote_push_url(repo: Path, remote: str) -> str:
    result = _git(repo, "remote", "get-url", "--push", remote, capture=True, check=False)
    return result.stdout.strip()


def _rev_parse(repo: Path, ref: str) -> str:
    return _git_out(repo, "rev-parse", ref)


def _short_sha(sha: str, length: int = 8) -> str:
    return sha[:length]


# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------


def _check_preconditions(repo: Path, upstream_branch: str, dry_run: bool = False) -> None:
    """Raise :class:`UpstreamSyncError` if any precondition fails."""

    # 1. Is this an argo-agent repo?
    if not (repo / "argo_sync").is_dir() or not (repo / _RENAME_YAML).is_file():
        raise UpstreamSyncError(
            "cwd does not look like an argo-agent repo "
            "(missing argo_sync/ or argo-rename.yaml)",
            step="preconditions",
        )

    # 2. Working tree must be clean (skip for dry-run? No — always enforce)
    if not _is_clean(repo):
        raise UpstreamSyncError(
            "working tree has uncommitted changes; commit or stash them first",
            step="preconditions",
        )

    # 3. upstream remote configured
    if not _remote_exists(repo, "upstream"):
        raise UpstreamSyncError(
            "'upstream' remote not configured; add it with:\n"
            "  git remote add upstream <URL>\n"
            "  git remote set-url --push upstream no_push",
            step="preconditions",
        )

    # 4. Warn if push URL != no_push
    push_url = _remote_push_url(repo, "upstream")
    if push_url and push_url != "no_push":
        print(
            f"WARNING: upstream push URL is '{push_url}' (expected 'no_push'). "
            "Proceeding, but set it to 'no_push' to prevent accidental pushes.",
            file=sys.stderr,
        )

    # 5. upstream-mirror branch must exist locally
    if not _branch_exists_locally(repo, upstream_branch):
        raise UpstreamSyncError(
            f"branch '{upstream_branch}' not found locally; "
            "run 'argo update' after setting up the upstream mirror branch",
            step="preconditions",
        )


# ---------------------------------------------------------------------------
# Sync state (conflict persistence)
# ---------------------------------------------------------------------------


def _write_sync_state(repo: Path, phase: str, upstream_sha: str, original_sha: str) -> None:
    state_dir = repo / ".argo"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / "sync-state.json"
    state: dict[str, str] = {
        "phase": phase,
        "upstream_sha": upstream_sha,
        "original_sha": original_sha,
    }
    state_file.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _read_sync_state(repo: Path) -> dict[str, str] | None:
    state_file = repo / _SYNC_STATE_REL
    if not state_file.exists():
        return None
    return json.loads(state_file.read_text(encoding="utf-8"))


def _delete_sync_state(repo: Path) -> None:
    state_file = repo / _SYNC_STATE_REL
    if state_file.exists():
        state_file.unlink()


# ---------------------------------------------------------------------------
# Core sync steps
# ---------------------------------------------------------------------------


def _fetch_upstream(repo: Path) -> str:
    """git fetch upstream; return upstream/main HEAD sha."""
    print("→ Fetching upstream...")
    _git(repo, "fetch", "upstream")
    return _git_out(repo, "rev-parse", "upstream/main")


def _update_upstream_mirror(repo: Path, upstream_branch: str) -> str:
    """
    Update local upstream-mirror from upstream/main (ff-only).
    Returns the new HEAD sha of upstream-mirror.
    """
    print(f"→ Updating '{upstream_branch}' from upstream/main...")
    current = _current_branch(repo)

    _git(repo, "checkout", upstream_branch)
    result = _git(repo, "merge", "--ff-only", "upstream/main", capture=True, check=False)
    if result.returncode != 0:
        _git(repo, "checkout", current)
        raise UpstreamSyncError(
            f"cannot fast-forward '{upstream_branch}' to upstream/main "
            "(non-linear history; resolve manually and re-run):\n"
            + result.stderr,
            step="update-mirror",
        )

    sha = _git_out(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", current)
    return sha


def _has_common_ancestor(repo: Path, ref1: str, ref2: str) -> bool:
    """Return True if *ref1* and *ref2* share a common ancestor commit."""
    result = _git(repo, "merge-base", "--is-ancestor", ref1, ref2, capture=True, check=False)
    if result.returncode == 0:
        return True
    result2 = _git(repo, "merge-base", ref1, ref2, capture=True, check=False)
    return result2.returncode == 0


def _merge_mirror_into_main(
    repo: Path,
    upstream_branch: str,
    target_branch: str,
    upstream_sha: str,
    original_sha: str,
) -> None:
    """
    Merge *upstream_branch* into *target_branch*.
    On conflict, persist sync-state.json and raise UpstreamMergeConflict.
    Allows unrelated histories (needed when argo-agent was bootstrapped
    from upstream on a fresh orphan branch).
    """
    print(f"→ Merging '{upstream_branch}' into '{target_branch}'...")
    # Use --allow-unrelated-histories because the argo-agent repo may have
    # been bootstrapped from a clean state with no common ancestor to upstream.
    result = _git(
        repo,
        "merge",
        "--allow-unrelated-histories",
        upstream_branch,
        capture=True,
        check=False,
    )
    if result.returncode != 0:
        # Detect conflict markers
        conflicting = _git_out(repo, "diff", "--name-only", "--diff-filter=U")
        files = [f for f in conflicting.splitlines() if f]
        _write_sync_state(repo, "merge", upstream_sha, original_sha)
        print(
            f"\n✗ Merge conflict in {len(files)} file(s):\n"
            + "\n".join(f"  {f}" for f in files),
            file=sys.stderr,
        )
        print(
            "\nResolve conflicts, stage the files, then run:\n"
            "  argo update --resume",
            file=sys.stderr,
        )
        raise UpstreamMergeConflict(files)


def _run_rename_engine(repo: Path, upstream_sha: str) -> int:
    """Run RenameEngine.apply_and_write_manifest; return count of files touched."""
    print("→ Running rename engine...")
    cfg = RenameConfig.load(repo / _RENAME_YAML)
    engine = RenameEngine(cfg)
    manifest_path = engine.apply_and_write_manifest(repo, upstream_sha=upstream_sha)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    n = len(data.get("files_touched", []))
    print(f"  Renamed/touched {n} file(s).")
    return n


def _commit_sync(repo: Path, upstream_sha: str, n_files: int) -> None:
    """git add -A and commit with canonical sync: message."""
    _git(repo, "add", "-A")

    # Check if there's anything to commit
    status = _git_out(repo, "status", "--porcelain")
    if not status:
        print(f"  Nothing to commit (rename was a no-op for {_short_sha(upstream_sha)}).")
        return

    msg = f"sync: upstream {_short_sha(upstream_sha)} ({n_files} files renamed)"
    _git(repo, "commit", "-m", msg)
    print(f"✓ Committed: {msg}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_update(
    repo: Path,
    *,
    upstream_branch: str = _DEFAULT_UPSTREAM_BRANCH,
    target_branch: str = _DEFAULT_TARGET_BRANCH,
    rename_only: bool = False,
    merge_only: bool = False,
    dry_run: bool = False,
    resume: bool = False,
) -> None:
    """
    Execute ``argo update`` logic.

    Parameters
    ----------
    repo:
        Path to the argo-agent repository root.
    upstream_branch:
        Local branch tracking upstream content (default: ``upstream-mirror``).
    target_branch:
        Branch to merge into and commit on (default: ``main``).
    rename_only:
        Skip fetch + merge; run only rename engine + commit.
    merge_only:
        Skip rename engine + commit; only update mirror + merge.
    dry_run:
        Report what would happen; make no mutations.
    resume:
        Resume a previously interrupted merge (reads .argo/sync-state.json).
    """
    # ------------------------------------------------------------------
    # --resume path
    # ------------------------------------------------------------------
    if resume:
        state = _read_sync_state(repo)
        if state is None:
            raise UpstreamSyncError(
                ".argo/sync-state.json not found; nothing to resume",
                step="resume",
            )
        if state.get("phase") != "merge":
            raise UpstreamSyncError(
                f"unknown phase '{state.get('phase')}' in sync-state.json; "
                "cannot auto-resume",
                step="resume",
            )

        upstream_sha: str = state["upstream_sha"]
        print(f"→ Resuming sync from upstream {_short_sha(upstream_sha)} (phase: merge)...")
        print("  Assuming merge conflicts have been resolved and staged.")

        # Check we are still on target_branch
        branch = _current_branch(repo)
        if branch != target_branch:
            raise UpstreamSyncError(
                f"expected to be on '{target_branch}' for resume, but HEAD is '{branch}'",
                step="resume",
            )

        # Commit the resolved merge (user must have staged resolution)
        # Check if there's an in-progress merge to commit
        merge_head = repo / ".git" / "MERGE_HEAD"
        if merge_head.exists():
            _git(repo, "commit", "--no-edit")

        # Run rename engine + commit
        n_files = _run_rename_engine(repo, upstream_sha)
        _commit_sync(repo, upstream_sha, n_files)

        # Clean up state
        _delete_sync_state(repo)
        print("✓ Resume complete. Sync-state cleared.")
        return

    # ------------------------------------------------------------------
    # Guard: sync-state.json present (prior conflict not resolved)
    # ------------------------------------------------------------------
    if _read_sync_state(repo) is not None:
        raise UpstreamSyncError(
            ".argo/sync-state.json exists from a prior interrupted sync.\n"
            "Resolve conflicts, then run:\n"
            "  argo update --resume\n"
            "Or delete .argo/sync-state.json to discard the interrupted sync.",
            step="preconditions",
        )

    # ------------------------------------------------------------------
    # Preconditions
    # ------------------------------------------------------------------
    if not rename_only:
        _check_preconditions(repo, upstream_branch, dry_run=dry_run)

        # Must be on target branch
        branch = _current_branch(repo)
        if branch != target_branch:
            raise UpstreamSyncError(
                f"expected to be on '{target_branch}', but HEAD is '{branch}'; "
                f"switch with: git checkout {target_branch}",
                step="preconditions",
            )

    # ------------------------------------------------------------------
    # dry-run: report and exit
    # ------------------------------------------------------------------
    if dry_run:
        print("→ dry-run mode — no mutations will be made")
        # Fetch to know the upstream sha (read-only: fetch does not modify HEAD)
        upstream_sha = _fetch_upstream(repo)
        print(f"  Upstream sha: {upstream_sha}")
        # Report rename mapping count (running the engine fully would mutate)
        cfg = RenameConfig.load(repo / _RENAME_YAML)
        print(f"  Rename mappings: {len(cfg.mappings)}")
        print("  (use without --dry-run to apply)")
        return

    # ------------------------------------------------------------------
    # Save original sha for rollback info
    # ------------------------------------------------------------------
    if not rename_only:
        original_sha = _rev_parse(repo, "HEAD")

    # ------------------------------------------------------------------
    # Step 1-5: Fetch + update upstream-mirror
    # ------------------------------------------------------------------
    if not rename_only:
        _fetch_upstream(repo)
        upstream_sha = _update_upstream_mirror(repo, upstream_branch)

        # Idempotency: if upstream sha is already an ancestor of HEAD, nothing to do.
        # git merge-base --is-ancestor exits 0 when ref1 is ancestor of ref2.
        result = _git(
            repo,
            "merge-base",
            "--is-ancestor",
            upstream_sha,
            "HEAD",
            capture=True,
            check=False,
        )
        if result.returncode == 0:
            print(f"✓ Already up-to-date with upstream {_short_sha(upstream_sha)}.")
            return

    else:
        # rename-only: use HEAD of upstream-mirror as upstream_sha
        if _branch_exists_locally(repo, upstream_branch):
            upstream_sha = _rev_parse(repo, upstream_branch)
        else:
            # Fallback: use a placeholder sha
            upstream_sha = _rev_parse(repo, "HEAD")

    # ------------------------------------------------------------------
    # Step 6: Merge upstream-mirror into main
    # ------------------------------------------------------------------
    if not rename_only:
        _merge_mirror_into_main(
            repo,
            upstream_branch,
            target_branch,
            upstream_sha,
            original_sha,
        )

    # ------------------------------------------------------------------
    # Steps 7-8: Rename engine + commit
    # ------------------------------------------------------------------
    if not merge_only:
        n_files = _run_rename_engine(repo, upstream_sha)
        _commit_sync(repo, upstream_sha, n_files)
    else:
        print("→ --merge-only: skipping rename engine.")


# ---------------------------------------------------------------------------
# argparse handler (wired from argo_cli/main.py)
# ---------------------------------------------------------------------------


def cmd_argo_update(args: argparse.Namespace) -> None:
    """Argparse handler for ``argo update`` (argo-sync replacement)."""
    repo = Path.cwd()
    try:
        run_update(
            repo,
            upstream_branch=getattr(args, "upstream_branch", _DEFAULT_UPSTREAM_BRANCH),
            rename_only=getattr(args, "rename_only", False),
            merge_only=getattr(args, "merge_only", False),
            dry_run=getattr(args, "dry_run", False),
            resume=getattr(args, "resume", False),
        )
    except UpstreamMergeConflict as exc:
        # Already printed instructions; just exit non-zero
        sys.exit(1)
    except ArgoSyncError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# __main__ — python -m argo_cli.argo_update
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="argo update",
        description=(
            "Fetch upstream-mirror, merge into main, run rename engine, commit.\n"
            "Replaces the former PyPI self-updater with argo-sync."
        ),
    )
    p.add_argument(
        "--upstream-branch",
        default=_DEFAULT_UPSTREAM_BRANCH,
        metavar="BRANCH",
        help=f"Local branch tracking upstream content (default: {_DEFAULT_UPSTREAM_BRANCH})",
    )
    p.add_argument(
        "--rename-only",
        action="store_true",
        default=False,
        help="Skip fetch + merge; run only rename engine + commit.",
    )
    p.add_argument(
        "--merge-only",
        action="store_true",
        default=False,
        help="Skip rename engine + commit; only fetch + update mirror + merge.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Report what would happen; make no mutations.",
    )
    p.add_argument(
        "--resume",
        action="store_true",
        default=False,
        help="Resume a previously interrupted merge from .argo/sync-state.json.",
    )
    return p


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()
    cmd_argo_update(args)
