#!/usr/bin/env bash

set -euo pipefail

usage() {
    cat <<'EOF'
Usage: bash scripts/sync_argo_fork.sh [--no-push-main] [--push-argo]

Sync policy for the argo fork:
- `main` is fast-forwarded to `upstream/main` and pushed to `origin/main`
- `argo` merges the latest upstream release tag, then re-runs `rebrand.sh`

Pushing `main` is the standard procedure and runs by default.
Use `--no-push-main` to skip it (local-only dry run).
Use `--push-argo` to also push `argo` to `origin`.
EOF
}

push_main=1
push_argo=0

while [ $# -gt 0 ]; do
    case "$1" in
        --no-push-main)
            push_main=0
            ;;
        --push-argo)
            push_argo=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "unknown argument: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
    shift
done

repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "working tree must be clean before syncing" >&2
    exit 1
fi

original_branch=$(git branch --show-current)

cleanup() {
    if [ -n "${original_branch:-}" ]; then
        git checkout "$original_branch" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT

echo "Fetching upstream main and tags"
git fetch upstream main --tags

latest_tag=$(git tag -l 'v*' --sort=-v:refname | head -1)
if [ -z "$latest_tag" ]; then
    echo "no upstream release tags found" >&2
    exit 1
fi

echo "Latest upstream release tag: $latest_tag"

echo "Syncing main to upstream/main"
git update-ref refs/heads/main refs/remotes/upstream/main

echo "Switching to argo worktree for pushes and tag merge"
git checkout argo >/dev/null 2>&1
git pull origin argo --ff-only

if [ "$push_main" -eq 1 ]; then
    git push origin main
fi

echo "Syncing argo from $latest_tag"

if git merge-base --is-ancestor "$latest_tag" argo; then
    echo "argo already contains $latest_tag"
else
    git merge "$latest_tag" --no-edit
    bash rebrand.sh

    if ! git diff --quiet || ! git diff --cached --quiet; then
        git add -A
        git commit --amend --no-edit
    fi

    if [ "$push_argo" -eq 1 ]; then
        git push origin argo
    fi
fi

echo "Sync complete"
