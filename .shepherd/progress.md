# argo-agent — Orchestrator Progress

> Single source of truth for shepherd state. Re-read before every milestone, dispatch, or merge. Update after every action.

## Current State

- **Phase:** 2 (Orchestration Loop).
- **Active milestone:** M4 (argo CLI Surfaces — update + doctor).
- **Completed milestones:** M1, M2, M3.
- **Test count on main:** 105 argo-platform tests (green). Upstream's renamed tests not run (need API keys).
- **AC verified so far:** AC-3 (idempotency, synthetic + real-tree), AC-5 (bootstrap), AC-6 (argo CLI launches argo-branded).
- **Files on main:** 3669.
- **Active worktrees:**
  - `/home/vadim/Code/argo-agent-wt/m4-update` — `argo/m4-update` (T4.1 + T4.4)
  - `/home/vadim/Code/argo-agent-wt/m4-doctor` — `argo/m4-doctor` (T4.2 + T4.3)
- **Worktree placement:** siblings of repo at `/home/vadim/Code/argo-agent-wt/`.

## Lessons Learned (process)

- **Worktree isolation defaults to the orchestrator's cwd.** The Agent tool's `isolation: "worktree"` creates a worktree of WHATEVER repo the orchestrator's cwd belongs to. My cwd is `/home/vadim/Code/hermes-agent`, so a naive `isolation: "worktree"` created a hermes-agent worktree, not an argo-agent one. The T2.1 agent worked around this by writing directly to argo-agent's main. **From M2 onward: pre-create worktrees in argo-agent and pass the explicit path in the implementer prompt — do NOT rely on the auto-isolation.**
- **Plan must get explicit sign-off.** I treated "pick defaults for OQs" as plan approval — wrong. The user pushed back; correct procedure restored.

## Quick Pointers

- Spec: `.shepherd/spec.md`
- Plan: `.shepherd/plan.md`
- Standards: `.shepherd/standards.md`
- Hermes upstream (read-only reference clone): `/home/vadim/Code/hermes-agent`
- Upstream remote URL: `git@github.com:NousResearch/hermes-agent.git`
- Origin remote URL: **TBD** — user provides during M5 (T5.4). Until then, placeholder.

## Architecture Snapshot

- Repo type: independent private git repo (NOT a GitHub fork).
- Branches: `main` (argo-renamed), `upstream-mirror` (clean hermes content, fetch-only).
- Sync model: `upstream` remote is read-only. `argo update` performs `fetch upstream → merge into upstream-mirror → merge upstream-mirror into main → run rename engine → commit`.
- Rename engine: `argo_sync/` package + `bin/argo-sync` entry script + `argo-rename.yaml` declarative config. Deterministic, idempotent, three ordered passes (content → filenames → directories).
- KEY GATE: AC-2 (zero "hermes" leakage in live argo I/O) gates M5 completion.

## Resolved Decisions (from spec § D-*)

- **D-1.** CI: static doctor + stub-model smoke. Live model = local pre-release only.
- **D-2.** No `UPSTREAM.md`. `.shepherd/**` is the single exception path.
- **D-3.** Hard rename `HERMES_HOME` → `ARGO_HOME`. No dual-read.
- **D-4.** Independent private repo, not a GitHub fork. `upstream` remote is fetch-only — never push.

## Milestones

### M1 — Repository Bootstrap — **PENDING**
- Tasks: T1.1 → T1.2 → T1.3 (all sequential, all S)
- Outcome: scaffolded repo with remotes, branches, skeleton pyproject + bin/argo-sync stub, `pip install -e .` works.

### M2 — Rename Engine MVP — pending
### M3 — First Real Rename (Bootstrap from Upstream) — pending
### M4 — argo CLI Surfaces — pending
### M5 — Real-Deployment Smoke (KEY GATE) — pending
### M6 — Documentation and Handoff — pending

## T5.4 Status (push to GitHub origin) — DEFERRED to user

- `origin` remote configured with placeholder URL: `file:///tmp/argo-origin.git` (per plan's autonomous-decision rule).
- First attempted push (`git push -u origin main upstream-mirror`) was BLOCKED by a global gitleaks pre-push hook reporting "730 leaks found" across the renamed upstream content (35 commits scanned, 61MB).
- These are almost certainly false positives inherited from upstream hermes-agent content (test fixtures, example keys, regex patterns that match secret formats). Argo-agent did not introduce them.
- ACTION REQUIRED FROM USER: when ready, (1) supply real private GitHub repo URL via `git remote set-url origin <url>`, (2) audit the gitleaks findings (likely allowlist the inherited test fixtures, real secrets if any need rotation), (3) push.
- This does NOT block any downstream work — AC-2 verified, CI workflow committed, M6 docs can proceed.

## Decisions Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-05-24 | Hard rename approach (deep, all identifiers) | Runtime branding swap is insufficient because the LLM reads the filesystem and reproduces "hermes" from paths/imports/errors. |
| 2026-05-24 | Two-branch model (`upstream-mirror` + `main`) | Conflicts surface in hermes-shape before rename = git tooling stays useful. |
| 2026-05-24 | Empty `exceptions:` list at bootstrap | Evidence-driven growth only — no preemptive compat shims. The doctor + customer testing surfaces real breakage. |
| 2026-05-24 | No `UPSTREAM.md` | Customer-visible files mention argo only. Single `.shepherd/**` exception is cleaner than a per-file allowlist. |
| 2026-05-24 | Independent repo, not GitHub fork | GitHub fork exposes a parent-link via the API; we don't want public upstream provenance. |
| 2026-05-24 | Read-only upstream | No PRs/pushes back to hermes-agent. Explicit "Never" boundary in spec. |
| 2026-05-24 | Hard rename `HERMES_HOME` → `ARGO_HOME` | Greenfield, no users to migrate, dual-read = clutter for zero benefit. |

## Deferred / Out-of-Scope (not for this iteration)

- Per-deployment skill/tool customization (v2).
- Publishing argo-agent to PyPI.
- Upstreaming a "BRAND_NAME config" PR to hermes-agent.
- Migrating existing hermes installs to argo (greenfield only).

## Known Limitations

- (To be filled in as discovered.)

## Next Action

Begin Phase 2: dispatch M1 tasks. T1.1 first (sequential, blocks M1 entirely).
