# Publish argo-agent docker image to GHCR

## Context

`argo-agent` is a private fork of `NousResearch/hermes-agent`. The `argo` branch is
the deployment branch, reset to each upstream release tag (currently `v2026.4.8`)
plus two layers of local modifications (honcho session rebind + rebrand). Owner:
`vadimcomanescu`.

The sibling private repo `nadicode-agent-fleet` currently clones hermes at build
time (`git clone https://github.com/NousResearch/hermes-agent ... && git checkout
${HERMES_REF}`) and applies a local patch `0001-rebind-session-per-turn.patch`.
That patch is **already merged into `argo`** (commit `f93f1dbd argo: honcho
session rebind per turn`), so once the fleet consumes a prebuilt `argo-agent`
image it can drop the patch step entirely and three heavy `RUN` layers
(apt installs, Node.js install, git clone + install.sh) collapse to a single
`FROM`.

The current `.github/workflows/docker-publish.yml` targets the upstream repo
(`NousResearch/hermes-agent`) on Docker Hub, gated behind a fork guard, and
triggers on `main` — none of which apply to the fork. This plan reworks it to
publish `ghcr.io/vadimcomanescu/argo-agent` from the `argo` branch, and
retargets the other branch-filtered workflows so CI actually runs on `argo`.

Fleet-side adoption (switching `Dockerfile` `FROM`, compose `image:`, fleet CI
auth, path adjustments `/opt/hermes-agent` → `/opt/hermes`) is **out of scope**
for this plan and will be a separate PR in `nadicode-agent-fleet`.

## Goal

On every push to `argo`, publish `ghcr.io/vadimcomanescu/argo-agent:latest` and
`ghcr.io/vadimcomanescu/argo-agent:<sha>` to GHCR (private package).

On every GitHub release created in `vadimcomanescu/argo-agent`, also publish
`ghcr.io/vadimcomanescu/argo-agent:<release-tag-name>` — e.g. creating a
release named `argo-v2026.4.8` publishes `:argo-v2026.4.8`.

**Release naming convention: `argo-v<upstream-version>`.** The prefix is
required because the plain upstream tag (`v2026.4.8`) already exists in the
repo pointing at the vanilla upstream commit, not argo's tip. Using
`argo-v2026.4.8` creates a fresh tag at argo's tip and avoids that collision.

## Changes

### 1. `.github/workflows/docker-publish.yml`

Critical file: `/home/vadim/Code/argo-agent/.github/workflows/docker-publish.yml`

Edits, in order:

**a) Triggers (lines 5, 7).** Replace `branches: [main]` → `branches: [argo]` in
both the `push:` and `pull_request:` blocks.

**b) Fork guard (lines 17–18).** Delete both lines — the comment and the `if:`.
The job must run on this fork.

**c) Job permissions.** Immediately after `build-and-push:` (line 16), at the
same indentation as `runs-on:`, add:
```yaml
    permissions:
      contents: read
      packages: write
```
This is what lets `GITHUB_TOKEN` push to GHCR.

**d) Smoke-test image tag (lines 36, 45).** Replace
`nousresearch/hermes-agent:test` → `ghcr.io/vadimcomanescu/argo-agent:test`
(both occurrences). The image is built with `load: true`, so the tag is a
local docker name only — it is never pushed anywhere. The `/opt/hermes`
entrypoint path in line 44 stays as-is (internal path is structural, per
`docs/argo-fork.md`). `hermes --help` exits 0 via argparse, so the smoke test
keeps working unchanged.

**e) Login step (lines 47–52).** Replace the entire Docker Hub login step with
a GHCR login step. The `if:` condition must keep the `|| release` branch so
release-triggered runs also authenticate:
```yaml
      - name: Log in to GHCR
        if: github.event_name == 'push' && github.ref == 'refs/heads/argo' || github.event_name == 'release'
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
```

**f) Push-image-on-branch step (lines 54–65).** Two edits in this block:
- Line 55 `if:` — `refs/heads/main` → `refs/heads/argo`.
- Lines 62–63 tags — `nousresearch/hermes-agent:latest` →
  `ghcr.io/vadimcomanescu/argo-agent:latest` and same swap for the `:${{ github.sha }}` tag.

**g) Push-image-on-release step (lines 67–79).** No `if:` edit (still fires on
`github.event_name == 'release'`, unchanged). Lines 75–77 tags — swap all three
`nousresearch/hermes-agent:*` → `ghcr.io/vadimcomanescu/argo-agent:*`
(`:latest`, `:${{ github.event.release.tag_name }}`, `:${{ github.sha }}`).

### 2. `.github/workflows/tests.yml`

Critical file: `/home/vadim/Code/argo-agent/.github/workflows/tests.yml`

Replace `branches: [main]` → `branches: [argo]` in both the `push:` and
`pull_request:` blocks. This fork does not maintain `main`, so there is no
reason to keep it in the filter.

### 3. `.github/workflows/nix.yml`

Critical file: `/home/vadim/Code/argo-agent/.github/workflows/nix.yml`

Replace `branches: [main]` → `branches: [argo]` in the `push:` trigger. The
`pull_request:` trigger has no branch filter and needs no change.

### 4. Out of scope (deliberate)

- `deploy-site.yml` — docs site publishing, not relevant to image publish.
  Fork guard stays; branch filter unchanged.
- `Dockerfile` and `docker/entrypoint.sh` — internal `/opt/hermes` paths are
  intentional per `docs/argo-fork.md` ("Structural: Docker, CI ... upstream-tracked,
  conflict-prone if changed"). No changes.
- `pyproject.toml` version — CalVer `v2026.4.8` lives only as a git tag / GitHub
  release name; not stored in any file. No bump needed.
- Fleet-side migration — separate PR in `nadicode-agent-fleet`.

## Post-merge manual step (one-time, in the GitHub UI)

After the first successful publish, the GHCR package will exist as **private**
(because `argo-agent` is a private repo). One click makes it pullable by the
fleet's CI, no secrets or tokens needed:

1. Open https://github.com/users/vadimcomanescu/packages/container/argo-agent/settings
2. Scroll to **Manage Actions access** → **Add repository** → add
   `vadimcomanescu/nadicode-agent-fleet` with role **Read**.

That's the entire setup. After this click, when `nadicode-agent-fleet`'s CI
runs `docker pull ghcr.io/vadimcomanescu/argo-agent:...`, its built-in
`GITHUB_TOKEN` is already sufficient — no PAT, no repo secret, no extra config.

Keep the package **private**. Making it public is irreversible and the image
contains the full fork source. There is no "internal" tier for personal
accounts — only private or public.

(Local workstation `docker pull` and any fleet-side Dockerfile/compose changes
are deferred to the fleet-side PR; they are not needed for this plan to be
considered done.)

## Notes before execution

- **Commit the workflow edits directly to `argo`.** The first push will trigger
  the rewritten `docker-publish.yml` live. If the YAML is malformed it fails
  loudly in the Actions tab — nothing is published, just a failed run to fix.
- **`tests.yml` may fail on its first `argo` run.** The argo branch has
  fork-specific commits (rebrand, honcho patch) that have never been validated
  against the upstream test suite. If it fails, that is a separate triage, not
  a blocker for `docker-publish` — the two workflows are independent.

## Verification

1. Push the changes and watch the runs:
   ```
   git push origin argo
   gh run list --limit 5
   gh run watch <docker-publish-run-id>
   ```
   Expect three workflows to queue on the push: `docker-publish.yml`,
   `tests.yml`, `nix.yml`. The docker-publish run should no longer skip (no
   more fork-guard), the smoke test should pass, and the push step should
   succeed with the new GHCR tags.

2. Verify the package exists:
   ```
   gh api user/packages/container/argo-agent
   ```
   Expect: 200 OK with `"visibility": "private"`. If 404, the push step failed
   silently or `permissions: packages: write` is missing from the job.

3. Perform the one-time access grant in the GitHub UI (above) so the fleet can
   later pull it.

4. Create the first versioned release to exercise the release-trigger path.
   Use the `argo-v` prefix to avoid colliding with the existing upstream
   `v2026.4.8` git tag. This is a real release — the tag and release object
   persist:
   ```
   gh release create argo-v2026.4.8 --target argo \
     --title "argo v2026.4.8" \
     --notes "Tracks upstream hermes-agent v2026.4.8"
   gh run list --limit 3
   gh run watch <release-run-id>
   ```
   Expect: release-triggered workflow publishes `:argo-v2026.4.8`, `:latest`,
   and `:<sha>`. Confirm via `gh api user/packages/container/argo-agent/versions`.

5. (Optional) Verify the published image actually contains the argo-specific
   changes, not vanilla upstream:
   ```
   docker pull ghcr.io/vadimcomanescu/argo-agent:argo-v2026.4.8
   docker run --rm ghcr.io/vadimcomanescu/argo-agent:argo-v2026.4.8 \
     sh -c 'grep -l "honcho" /opt/hermes -r | head -5'
   ```
   Expect: grep hits from the honcho-session-rebind patch. If it returns
   nothing, the release was built from the wrong commit and the `argo-v`
   prefix collision check failed.
