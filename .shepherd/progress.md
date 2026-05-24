# argo-agent — Orchestrator Progress

> Single source of truth for shepherd state. Re-read before every milestone, dispatch, or merge. Update after every action.

## Current State

- **Phase:** COMPLETE — all milestones M1-M6 done.
- **Active milestone:** M6 (Documentation and Handoff) — completed 2026-05-24.
- **Completed milestones:** M1, M2, M3, M4, M5, M6.
- **Test count (argo-platform subset):** 33 tests green (tests/test_engine.py, tests/test_config_loader.py, tests/test_full_rename_config.py, tests/test_cmd_argo_doctor.py).
- **AC verified:** AC-2 (zero hermes leakage), AC-3 (idempotency), AC-4 (static + live doctor), AC-5 (bootstrap), AC-6 (argo CLI branding).
- **Files on main:** 3669.
- **argo doctor --static:** exits 0 (no leakage detected).

## Architecture Snapshot

- **Repo type:** Independent private git repo (NOT a GitHub fork).
- **Branches:**
  - `main` — argo-renamed content; receives every upstream sync via rename engine.
  - `upstream-mirror` — clean upstream (hermes-agent) content; never renamed. Fetch-only.
  - `argo/m6-docs` — active M6 branch, being merged to main after this commit.
- **Sync model:** `argo update` performs:
  1. `git fetch upstream` — pull new upstream commits into `upstream` remote.
  2. Fast-forward `upstream-mirror` → merge into `main`.
  3. Run `RenameEngine` from `argo-rename.yaml` (three passes: content → filenames → dirs).
  4. Commit the renamed tree with the upstream SHA in the message.
- **Rename engine:** `argo_sync/` package + `bin/argo-sync` entry script + `argo-rename.yaml` declarative config. Deterministic, idempotent.
- **Exceptions in argo-rename.yaml:** `.shepherd/**` (orchestrator state), `argo-rename.yaml` (self-reference), `bin/argo-bootstrap.py` (upstream provenance comments), `tests/test_full_rename_config.py` (must contain hermes-* literals to validate the FROM keys).
- **CI:** `.github/workflows/ci.yml` — lint, type-check, argo-platform tests, stub-model smoke.

## Milestones

### M1 — Repository Bootstrap — COMPLETE
- **Outcome:** Scaffolded repo with remotes, branches, skeleton `pyproject.toml`, `bin/argo-sync` stub, `pip install -e .` working.
- **AC verified:** repo structure, remote configuration, branch model.

### M2 — Rename Engine MVP — COMPLETE
- **Outcome:** `argo_sync/` package with `RenameEngine`, `RenameConfig`, manifest writing, three-pass deterministic rename.
- **AC verified:** AC-3 (idempotency on synthetic tree), unit tests green.

### M3 — First Real Rename (Bootstrap from Upstream) — COMPLETE
- **Outcome:** `bin/argo-bootstrap.py` merged upstream-mirror into main, applied rename engine, 3669 files on main.
- **AC verified:** AC-5 (bootstrap idempotency), AC-6 (argo CLI launches argo-branded).

### M4 — argo CLI Surfaces — COMPLETE
- **Outcome:** `argo update` (upstream sync, replaces PyPI self-updater), `argo doctor --static`, `argo doctor --live`. `argo update --resume` for post-conflict continuation.
- **AC verified:** AC-4 (`argo doctor --static` exits 0, `argo doctor --live` passes AC-2).
- **Key commit:** `78fb017` (swap argo update dispatch from PyPI self-updater to argo-sync).

### M5 — Real-Deployment Smoke (KEY GATE) — COMPLETE
- **Outcome:** AC-2 (zero hermes leakage in live argo I/O) formally verified. Stub-model HTTP server for deterministic CI smoke. `.github/workflows/ci.yml` committed.
- **AC-2 verified:** `argo doctor --static` exits 0; `argo doctor --live` with stub model exits 0.
- **T5.4 (push to GitHub origin):** DEFERRED to user — see below.

### M6 — Documentation and Handoff — COMPLETE
- **T6.1 README polish:** Single hermes hit (`hermesclaw` in third-party community project URL) is justified — no change. `argo update` description updated to reflect upstream-sync semantics (not PyPI self-update).
- **T6.2 AGENTS.md audit:** Zero hermes hits. No internal anchor links (no broken anchors). All source file cross-references verified to exist on disk (run_agent.py, model_tools.py, toolsets.py, cli.py, argo_cli/main.py, argo_cli/commands.py, etc.).
- **T6.3 Inline sync docs:** `bin/argo-sync` docstring fully expanded with 4-step workflow and conflict-resolution path. `argo update --help` expanded with numbered steps and conflict-resolution guidance. `argo-rename.yaml` exceptions verified (3 required + 1 justified extra).
- **T6.4 Progress.md:** This file — final handoff state.

## Operator Checklist — Customer Install

```bash
# Fresh customer install:
git clone <argo-agent-url> /opt/argo
cd /opt/argo
uv venv .venv --python 3.13
uv pip install -e '.[all]' --python .venv/bin/python
argo --help

# Periodic upstream sync:
argo update

# On merge conflict during sync:
# 1. Resolve conflicts manually
# 2. git add <resolved-files>
# 3. argo update --resume

# Health check:
argo doctor --static
argo doctor --live --live-cmd "argo -z 'list files'"
```

## T5.4 Status — Push to GitHub Origin — DEFERRED to User

- `origin` remote configured with placeholder URL: `file:///tmp/argo-origin.git`.
- First attempted push was BLOCKED by a global gitleaks pre-push hook reporting "730 leaks found" across the renamed upstream content (35 commits scanned, 61MB). These are almost certainly false positives inherited from upstream hermes-agent content (test fixtures, example keys, regex patterns that match secret formats).
- **ACTION REQUIRED FROM USER:**
  1. Supply real private GitHub repo URL: `git remote set-url origin <url>`
  2. Audit gitleaks findings (likely allowlist inherited test fixtures; rotate any real secrets found)
  3. Push: `git push -u origin main upstream-mirror`

## Known Limitations & Deferred Items

- **T5.4 push:** Deferred to user — gitleaks false-positive audit required first (see above).
- **argo-rename.yaml exceptions:** 4 entries instead of the 3 in the seed spec. The 4th (`tests/test_full_rename_config.py`) is legitimately justified — the test validates that hermes-* FROM keys exist in the mappings, so it must contain hermes-* string literals.
- **Gitleaks audit:** The 730 reported "leaks" in upstream content are suspected false positives but have not been individually audited. Real secrets, if any, must be rotated before publishing.
- **argo doctor --live with real model:** CI uses stub model for deterministic runs. Operators must test with a real provider before production.
- **Upstream URL:** The `upstream` remote points to `git@github.com:NousResearch/hermes-agent.git`. Read-only by design — no PRs or pushes back.
- **PyPI publishing:** Out of scope for this iteration (per spec § Deferred).
- **Per-deployment skill/tool customization:** v2 (per spec § Deferred).
- **Migrating existing hermes installs:** Out of scope — greenfield only.

## Quick Pointers

- Spec: `.shepherd/spec.md`
- Plan: `.shepherd/plan.md`
- Standards: `.shepherd/standards.md`
- Upstream remote URL: `git@github.com:NousResearch/hermes-agent.git`
- Origin remote URL: TBD (user supplies real URL — see T5.4 above).

## Decisions Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-05-24 | Hard rename approach (deep, all identifiers) | Runtime branding swap is insufficient — LLM reads the filesystem and reproduces "hermes" from paths/imports/errors. |
| 2026-05-24 | Two-branch model (`upstream-mirror` + `main`) | Conflicts surface in hermes-shape before rename = git tooling stays useful. |
| 2026-05-24 | Empty `exceptions:` list at bootstrap | Evidence-driven growth only — no preemptive compat shims. |
| 2026-05-24 | No `UPSTREAM.md` | Customer-visible files mention argo only. Single `.shepherd/**` exception is cleaner than a per-file allowlist. |
| 2026-05-24 | Independent repo, not GitHub fork | GitHub fork exposes a parent-link via the API; upstream provenance must stay private. |
| 2026-05-24 | Read-only upstream | No PRs/pushes back to hermes-agent. Explicit "Never" boundary in spec. |
| 2026-05-24 | Hard rename `HERMES_HOME` → `ARGO_HOME` | Greenfield, no users to migrate, dual-read = clutter for zero benefit. |
| 2026-05-24 | `tests/test_full_rename_config.py` exception | Test validates FROM keys by searching for hermes-* literals — must be excluded from rename engine. |
