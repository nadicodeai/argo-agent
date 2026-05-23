# Implementation Plan: argo-agent

> Spec: `/home/vadim/Code/argo-agent/.shepherd/spec.md`
> Strategy: vertical-slice milestones, each ending in a reviewable working state.
> Execution: shepherd orchestrator dispatches one subagent per task (parallel where flagged) in git worktrees; architectural review after every milestone.

## Overview

Fork hermes-agent into argo-agent via a deterministic rename engine + a one-command upstream-sync workflow. Six milestones, ~30 tasks total. The "key acceptance gate" is **M5**: a live argo deployment must produce zero "hermes" leakage in any I/O the LLM can surface. Earlier milestones build toward that gate; M6 is doc polish.

## Resolved Decisions

- **D-1 — CI strategy.** Static doctor + unit + stub-model smoke run in GitHub Actions. Live-model smoke runs locally pre-release. No real API keys in CI.
- **D-2 — No `UPSTREAM.md`.** Sync docs live in `argo update --help`, `bin/argo-sync` source comments, and `.shepherd/`. Only `.shepherd/` is exempt from the leakage scan.
- **D-3 — Hard rename `HERMES_HOME` → `ARGO_HOME`.** No dual-read.
- **D-4 — Upstream is read-only.** Independent private GitHub repo (NOT a fork). `upstream` remote is fetch-only; never `git push upstream`.

## Architecture Decisions

- **Two branches.** `upstream-mirror` tracks `upstream/main` (clean hermes content); `main` is the renamed argo branch. Merges happen upstream-mirror → main, so git conflicts surface in hermes-shape before the rename pass.
- **Declarative rename config.** All transformations live in `argo-rename.yaml` (mappings + exceptions). The engine is dumb and deterministic; intelligence lives in the config.
- **Rename order.** Content within files → filename renames (bottom-up) → directory renames. This order prevents path clobbering during atomic moves.
- **Idempotency contract.** Re-running `argo update` on the same upstream sha = empty diff. Guarantees safety of accidental double-runs and makes the manifest meaningful.
- **No new runtime deps.** Engine uses stdlib + `pyyaml` (already an upstream dep). Tests use `pytest` (already there).
- **Smoke gate is non-negotiable.** AC-2 (zero hermes in live I/O) blocks milestone 5 completion. No "we'll fix it later" — the entire product premise depends on this.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Rename engine corrupts strings inside URLs / hashes / opaque tokens | High (silent breakage) | Scope rules in `argo-rename.yaml` (skip-in-context patterns); unit tests on adversarial fixtures |
| Upstream introduces new "hermes"-named external integration after a sync | High (silent leakage) | AC-2 live doctor runs on every milestone; exceptions list explicit and reviewed |
| `~/.hermes/` rename collides with users' existing dotfile dirs on dev machines | Medium | Default to `~/.argo/`; refuse to start if both exist; clear error message |
| Sync produces huge diffs per upstream pull (unstable rename) | Medium | Idempotency test in CI; manifest tracks deterministic touches; reviewer ignores rename-only hunks |
| `AGENTS.md` (53KB) contains rename-incompatible references (markdown links, anchor IDs) | Medium | M6 task verifies AGENTS.md integrity post-rename; broken-link check |
| LLM model used in smoke test costs more than expected | Low | Default smoke is recorded-stub; live model only for pre-release |
| Pyproject self-references (`hermes-agent[cron]`) break extras resolution | High | Engine handles pyproject explicitly (FR-9); idempotency test confirms |

---

## Milestone 1 — Repository Bootstrap

**Goal:** A fresh `/home/vadim/Code/argo-agent` git repo with the two remotes, the two branches, and skeleton files in place. No rename logic yet — just scaffolding the orchestrator can build on.

### T1.1 — Initialize git repo, remotes, branches
- **parallel:** false
- **inputs:** `/home/vadim/Code/argo-agent/` (empty dir with `.shepherd/`)
- **outputs:** `.git/`, two remotes (`origin` placeholder + `upstream` → NousResearch/hermes-agent), two branches (`upstream-mirror`, `main`)
- **verification:**
  - `git -C /home/vadim/Code/argo-agent remote -v` shows both remotes
  - `git -C /home/vadim/Code/argo-agent branch -a` shows both branches
  - `git -C /home/vadim/Code/argo-agent status` clean
- **est:** S

### T1.2 — Project skeleton (scaffolding files)
- **parallel:** false
- **inputs:** T1.1
- **outputs:** `.gitignore` (Python defaults + `.argo/sync-manifest.json` ignored or committed — decide), `README.md` (placeholder one-liner), `argo-rename.yaml` (empty `mappings:` + `exceptions:` stubs), `bin/argo-sync` (executable stub with `--help`)
- **verification:**
  - `python bin/argo-sync --help` exits 0
  - All files committed to `main` as "scaffolding"
- **est:** S

### T1.3 — Initial pyproject.toml + dev install path
- **parallel:** false
- **inputs:** T1.2, `/home/vadim/Code/hermes-agent/pyproject.toml` (for tech-stack alignment)
- **outputs:** Minimal `pyproject.toml` with `name = "argo-agent"`, Python ≥3.11, `[project.scripts] argo = "argo_cli.main:main"` (stub), dev extras `[pytest, ruff, ty]`, empty `argo_cli/main.py` with a 5-line `def main(): print("argo")` stub
- **verification:**
  - `pip install -e '.[dev]'` succeeds in a fresh venv
  - `argo` runs and prints "argo"
- **est:** S

### Checkpoint M1
- [ ] T1.1–T1.3 committed
- [ ] Repo lints clean (`ruff check .` is no-op on near-empty tree)
- [ ] Architectural review: scaffolding-only; reviewer confirms structure matches spec § "Project Structure"

---

## Milestone 2 — Rename Engine MVP

**Goal:** A working `argo_sync` Python package that takes a tree of files and an `argo-rename.yaml`, applies the rename deterministically and idempotently, and emits a manifest. Tested on synthetic fixtures only — no real hermes content yet.

T2.1 sets contracts; T2.2–T2.5 implement passes in parallel; T2.6–T2.8 wire and verify.

### T2.1 — Engine package skeleton + config loader
- **parallel:** false
- **inputs:** T1.3, spec FR-3
- **outputs:**
  - `argo_sync/__init__.py`
  - `argo_sync/config.py` — `RenameConfig` dataclass loading `argo-rename.yaml` (mappings: `Dict[str, str]`, exceptions: `List[str]` of literals + glob paths)
  - `argo_sync/engine.py` — `RenameEngine` shell class (interfaces only, methods raise NotImplementedError)
  - `tests/test_config_loader.py` — fixture YAML + loader assertions
- **verification:** `pytest tests/test_config_loader.py` green
- **est:** S

### T2.2 — Content-rename pass
- **parallel:** true (siblings: T2.3, T2.4, T2.5)
- **inputs:** T2.1
- **outputs:**
  - `argo_sync/passes/content.py` — walks files, applies `str.replace` for every mapping in order longest-key-first (prevents partial overlap), skips binary files, skips paths matching `exceptions:` globs
  - `tests/test_content_pass.py` — fixtures: plain `.py`, `.md`, `.yaml`, a fake binary, a file in exceptions
- **verification:** `pytest tests/test_content_pass.py` green
- **est:** M

### T2.3 — Filename-rename pass
- **parallel:** true
- **inputs:** T2.1
- **outputs:**
  - `argo_sync/passes/filenames.py` — walks tree bottom-up, renames files whose basename contains a mapping key, using `Path.rename` (atomic on same filesystem). Skips exceptions globs.
  - `tests/test_filename_pass.py` — fixtures with `hermes_state.py` → `argo_state.py`, nested dirs, name collision detection (raises if target exists)
- **verification:** `pytest tests/test_filename_pass.py` green
- **est:** M

### T2.4 — Directory-rename pass
- **parallel:** true
- **inputs:** T2.1
- **outputs:**
  - `argo_sync/passes/directories.py` — walks tree bottom-up, renames dirs whose name contains a mapping key, atomic rename. MUST run after T2.2/T2.3 in the orchestrator. Detects collisions.
  - `tests/test_directory_pass.py` — `hermes_cli/` → `argo_cli/`, including nested fixtures
- **verification:** `pytest tests/test_directory_pass.py` green
- **est:** M

### T2.5 — Sync manifest writer
- **parallel:** true
- **inputs:** T2.1
- **outputs:**
  - `argo_sync/manifest.py` — writes `.argo/sync-manifest.json` with `{upstream_sha, files_touched, exceptions_used, ran_at}`. Deterministic ordering (sorted paths).
  - `tests/test_manifest.py` — round-trip + sort stability
- **verification:** `pytest tests/test_manifest.py` green
- **est:** S

### T2.6 — Engine orchestrator (wire passes in order)
- **parallel:** false
- **inputs:** T2.2–T2.5 merged
- **outputs:**
  - `argo_sync/engine.py` — `RenameEngine.apply(root: Path) -> list[Path]` that runs `content → filenames → directories` and returns touched paths. Calls manifest writer.
- **verification:** `pytest tests/` green (all milestone-2 tests)
- **est:** S

### T2.7 — Synthetic fixture integration test
- **parallel:** false
- **inputs:** T2.6
- **outputs:**
  - `tests/fixtures/synthetic_hermes_tree/` — a small fake project mirroring hermes-shape (a `hermes_*.py` file, a `Hermes` class, a `HERMES_` env reference, a `~/.hermes/` path string, a nested `hermes_cli/` dir)
  - `tests/test_engine_integration.py` — runs the full engine on the fixture and asserts the post-state matches expected file tree + content
- **verification:** `pytest tests/test_engine_integration.py` green
- **est:** M

### T2.8 — Idempotency test (AC-3)
- **parallel:** false
- **inputs:** T2.7
- **outputs:**
  - `tests/test_idempotency.py` — runs engine on synthetic fixture, captures result; runs engine again on the result; asserts diff is empty and `files_touched` on second run is `[]`
- **verification:** `pytest tests/test_idempotency.py` green
- **est:** S

### Checkpoint M2
- [ ] `pytest -m 'not integration'` all green
- [ ] AC-3 (idempotency) passes on synthetic fixtures
- [ ] Architectural review: rename engine is pure, deterministic, has no git/CLI surface yet — exactly what we want

---

## Milestone 3 — First Real Rename (Bootstrap from Upstream)

**Goal:** Run the engine against a real hermes-agent checkout. The output is the initial `main` branch of argo-agent with everything renamed, installable, and `argo --help` returns argo branding.

### T3.1 — Author argo-rename.yaml (full mapping set)
- **parallel:** false
- **inputs:** explorer findings (network IDs, env vars, file paths, CLI binaries, package names, ACP IDs from spec § Technical Context), `/home/vadim/Code/hermes-agent/` (for grep cross-check)
- **outputs:**
  - `argo-rename.yaml` populated:
    - Content mappings (in longest-first order):
      - `HermesAgent` → `ArgoAgent`
      - `hermes-agent` → `argo-agent`
      - `hermes_agent` → `argo_agent`
      - `hermes_cli` → `argo_cli`
      - `hermes_bootstrap` → `argo_bootstrap`
      - `hermes_constants` → `argo_constants`
      - `hermes_state` → `argo_state`
      - `hermes_time` → `argo_time`
      - `hermes_logging` → `argo_logging`
      - `HERMES_HOME` → `ARGO_HOME`
      - `HERMES_` → `ARGO_` (catch-all for remaining HERMES_*)
      - `~/.hermes` → `~/.argo`
      - `.hermes/` → `.argo/`
      - `Hermes` → `Argo`
      - `HERMES` → `ARGO`
      - `hermes` → `argo`
    - `exceptions:` (initially empty)
    - `skip_contexts:` (don't rename inside `https?://[^\s]*hermes` URLs, inside `[0-9a-f]{20,}` hash-like tokens, inside fenced commit-sha lines)
- **verification:** `pytest tests/test_rename_yaml_parses.py` + a sanity check that each mapping appears in the synthetic fixture's expected-after state
- **est:** M

### T3.2 — `bin/argo-bootstrap.py` implementation
- **parallel:** false
- **inputs:** T2.6, T3.1
- **outputs:**
  - `bin/argo-bootstrap.py` — takes a path to a fresh hermes-agent clone, copies its content into `argo-agent/`, sets the two remotes, creates `upstream-mirror` from upstream HEAD, creates `main` from `upstream-mirror`, runs the engine on `main`, commits as `bootstrap: initial argo rename from hermes-agent@<sha>`
  - `tests/test_bootstrap.py` — runs against a fixture mini-hermes-tree, asserts post-state
- **verification:** `pytest tests/test_bootstrap.py` green
- **est:** M

### T3.3 — Execute bootstrap against real upstream
- **parallel:** false
- **inputs:** T3.2 (the actual `/home/vadim/Code/hermes-agent` clone)
- **outputs:**
  - `main` branch of `/home/vadim/Code/argo-agent` populated with renamed hermes content (one commit, the "bootstrap" commit)
  - `.argo/sync-manifest.json` recording the upstream sha at bootstrap time
- **verification:**
  - `git -C /home/vadim/Code/argo-agent log --oneline main` shows the bootstrap commit
  - `grep -ri 'hermes' .` (excluding `.git`, `argo-rename.yaml`, `exceptions` files) returns zero hits
- **est:** S (heavy compute, light judgment)

### T3.4 — Install + smoke check (AC-5, AC-6)
- **parallel:** false
- **inputs:** T3.3
- **outputs:** No new files; verifies the bootstrap is installable
- **verification:**
  - `pip install -e '.[dev]'` succeeds in a fresh venv
  - `argo --help` exits 0, output contains "argo", does NOT contain "hermes"
  - `argo-agent --help` and `argo-acp --help` similarly clean
- **est:** S

### T3.5 — Pyproject self-reference cleanup verification
- **parallel:** true (with T3.4)
- **inputs:** T3.3
- **outputs:** No new files; confirms FR-9 succeeded
- **verification:**
  - `grep -E 'hermes' pyproject.toml` returns zero hits
  - `pip install -e '.[all]'` resolves all extras (no broken self-refs)
- **est:** S

### Checkpoint M3
- [ ] T3.1–T3.5 done
- [ ] `argo --help` works, `argo doctor --static` (which we'll build in M4) would pass right now
- [ ] AC-5, AC-6 satisfied
- [ ] Architectural review: confirm rename completeness against a checklist; identify any "hermes" hits and either fix engine or add to exceptions with justification

---

## Milestone 4 — argo CLI Surfaces (`argo update`, `argo doctor`)

**Goal:** The user-facing commands that drive day-2 operations. `argo update` is the upstream sync; `argo doctor` is the leakage check (static + live modes). Both must work end-to-end against a simulated upstream change.

### T4.1 — `argo update` subcommand
- **parallel:** true (siblings: T4.2, T4.3, T4.4)
- **inputs:** T3.4, `argo_sync` package
- **outputs:**
  - `argo_cli/commands/update.py` — `argo update` orchestrates: `git fetch upstream` → checkout `upstream-mirror` → `git merge upstream/main` → checkout `main` → `git merge upstream-mirror` → run `argo_sync.engine.RenameEngine.apply()` → `git commit -m "sync: <upstream-sha>"`. On any unresolved conflict: exit non-zero with next-step message.
  - Registered in `argo_cli/main.py` subparsers
- **verification:** unit tests in `tests/test_cmd_update.py` with mocked git ops; deferred integration in T4.5
- **est:** M

### T4.2 — `argo doctor --static` subcommand
- **parallel:** true
- **inputs:** T3.4
- **outputs:**
  - `argo_cli/commands/doctor.py` (the static branch) — case-insensitive grep over the working tree, honoring `argo-rename.yaml`'s `exceptions:` (literal and glob path matches). Exit 0 on zero hits, non-zero with a per-file/line report otherwise.
  - `tests/test_cmd_doctor_static.py` — fixtures with planted hits + exceptions
- **verification:** `argo doctor --static` against the bootstrapped repo exits 0; deliberately injecting a "hermes" string and re-running exits non-zero
- **est:** M

### T4.3 — `argo doctor --live` subcommand
- **parallel:** true
- **inputs:** T3.4
- **outputs:**
  - `argo_cli/commands/doctor.py` (the live branch) — spawns argo as a subprocess with a scripted prompt (configurable), captures stdout/stderr, the temp directory, and any log files argo wrote during the run, then runs the same case-insensitive grep + exceptions filter
  - Default scripted prompt = a tiny one-turn conversation that triggers one tool call (deterministic stub tool acceptable for fast iteration; real model wiring lands in M5)
  - `tests/test_cmd_doctor_live.py` — mocked subprocess with planted leakage
- **verification:** unit + integration tests green
- **est:** M

### T4.4 — `argo update --resume` for conflict resolution
- **parallel:** true
- **inputs:** T4.1 (interfaces only)
- **outputs:**
  - Resume path in `argo_cli/commands/update.py` that re-enters the workflow after the operator manually resolved git conflicts on `upstream-mirror`
  - Clear messaging tied to AC-4
- **verification:** unit tests with simulated mid-flow state in `.argo/sync-state.json`
- **est:** S

### T4.5 — Integration test: real upstream commit cycle (AC-1)
- **parallel:** false (depends on T4.1)
- **inputs:** T4.1, sandbox copy of hermes-agent with an injected synthetic commit
- **outputs:**
  - `tests/test_update_integration.py` — sandboxed argo-agent + sandboxed upstream-with-new-commit, runs `argo update`, asserts (a) new content present, (b) all hermes references renamed in the new content, (c) commit message format
- **verification:** `pytest -m integration tests/test_update_integration.py` green
- **est:** M

### T4.6 — Integration test: merge conflict surface (AC-4)
- **parallel:** false (depends on T4.5)
- **inputs:** T4.5, T4.4
- **outputs:**
  - `tests/test_update_conflict.py` — induces an upstream merge conflict (modify the same line on both sides), runs `argo update`, asserts non-zero exit + recoverable tree + presence of resume instructions in stderr
- **verification:** test green; manual confirmation that `argo update --resume` completes after a `git add` of the resolution
- **est:** S

### Checkpoint M4
- [ ] AC-1, AC-3 (re-verified), AC-4 pass
- [ ] `argo doctor --static` is the gate that runs in CI from now on
- [ ] Architectural review: subagent inspects the CLI surface for missing error paths, confirms `argo update` is a single boring command in the happy path

---

## Milestone 5 — Real-Deployment Smoke (KEY GATE)

**Goal:** Prove AC-2 against a live argo. This is the entire premise of the project — if argo leaks "hermes" in a real conversation, the rebrand is broken. Also: push to GitHub origin, wire CI.

### T5.1 — `tests/test_deployment_smoke.py`
- **parallel:** true (siblings: T5.2, T5.3)
- **inputs:** T4.3
- **outputs:**
  - `tests/test_deployment_smoke.py` — boots argo end-to-end (separate process), exchanges a scripted prompt that triggers one tool call, captures all I/O, asserts zero case-insensitive "hermes" hits in stdout/stderr/log files/temp filenames
  - Marked `integration` (slow, needs a model)
- **verification:** local run green
- **est:** M

### T5.2 — Smoke-test model backend selection (resolves OQ-1)
- **parallel:** true
- **inputs:** spec § OQ-1
- **outputs:**
  - Recorded-stub backend at `tests/fixtures/recorded_model/` (deterministic, no API key needed — for CI)
  - Documentation in `tests/README.md` explaining how to swap in a real model for pre-release runs
- **verification:** smoke test runs against the stub in CI in <30s
- **est:** S

### T5.3 — CI workflow (AC-8)
- **parallel:** true
- **inputs:** none (parallel-safe — touches `.github/`)
- **outputs:**
  - `.github/workflows/ci.yml` — runs `pytest -m 'not integration'`, `ruff check`, `ty check`, `argo doctor --static`. The integration-marked smoke runs in a separate job with the recorded-stub backend.
- **verification:** workflow green on a PR against `main`
- **est:** S

### T5.4 — Push to GitHub origin
- **parallel:** false (depends on T5.1–T5.3, needs user-provided URL)
- **inputs:** user-provided private GitHub repo URL (placeholder: `git@github.com:vadim984/argo-agent.git`)
- **outputs:**
  - `origin` remote updated from placeholder to real URL
  - First push of `main` + `upstream-mirror` to origin
- **verification:** branches visible on GitHub, CI triggers on push
- **est:** S
- **autonomous-decision:** if origin URL is missing at this milestone, log to progress.md and proceed with a placeholder remote `file:///tmp/argo-origin.git`. User can re-point `origin` later without affecting any other workflow.

### T5.5 — Live smoke run + AC-2 verification (THE GATE)
- **parallel:** false (depends on T5.4)
- **inputs:** T5.1–T5.4
- **outputs:**
  - Run output captured at `.shepherd/smoke-run-<date>.log` (gitignored)
  - Report appended to `progress.md`: "AC-2 result on YYYY-MM-DD: PASS/FAIL, hits=N"
- **verification:**
  - `pytest -m integration tests/test_deployment_smoke.py` green
  - Manual review of one captured transcript: contains "argo", does not contain "hermes" (case-insensitive)
- **est:** M
- **failure-policy:** if AC-2 fails, do NOT advance to M6. Add findings to `argo-rename.yaml` (either as new mappings or as evidence-driven `exceptions:`), re-run from T4.1, re-test. Per shepherd protocol, after 3 failed iterations make a best-judgment call, log the deferred items, and report — but the bias is to fix, not defer.

### Checkpoint M5
- [ ] AC-2, AC-7, AC-8 PASS
- [ ] GitHub origin set and CI green
- [ ] Architectural review: cross-cutting reviewer audits the entire diff for leakage paths missed by the doctor (e.g., emoji glyphs containing "hermes", base64-encoded asset blobs, vendored docs)

---

## Milestone 6 — Documentation and Handoff

**Goal:** Argo-branded docs, upstream-provenance note, finalized progress.md. The repo is ready to ship to a customer or to start the M5-V2 customization work.

### T6.1 — README.md polish
- **parallel:** true (siblings: T6.2, T6.3)
- **inputs:** T5.5
- **outputs:**
  - `README.md` rewritten for argo branding (was a renamed copy of hermes's README; this pass ensures the prose flows and the install instructions match argo, not "renamed hermes")
- **verification:** read-through; `argo doctor --static` still passes (no new hermes leakage); contains an install snippet that matches what M3 verified works
- **est:** S

### T6.2 — AGENTS.md verification (53KB upstream file)
- **parallel:** true
- **inputs:** T5.5
- **outputs:**
  - Pass over `AGENTS.md` confirming rename hit all internal anchors, markdown links, code blocks, and embedded paths. Fix any broken cross-references the rename engine produced.
- **verification:**
  - Markdown link checker (light script) reports zero broken internal links
  - Spot-check 5 sections for readability
- **est:** M

### T6.3 — Inline sync documentation
- **parallel:** true
- **inputs:** spec § D-2
- **outputs:**
  - Expanded docstring + `--help` output for `argo update` (covers: what it does, how `upstream-mirror`/`main` interact, what to do on conflict, where `.argo/sync-manifest.json` lives)
  - Expanded module docstring in `bin/argo-sync` covering the same ground
  - `.shepherd/` confirmed as the single entry in `argo-rename.yaml` `exceptions:` (path glob: `.shepherd/**`)
- **verification:** `argo update --help` reads as customer-facing operator docs; `argo doctor --static` passes with the `.shepherd/**` exception applied
- **est:** S

### T6.4 — Final `progress.md` + architecture summary
- **parallel:** false (depends on T6.1–T6.3)
- **inputs:** entire `.shepherd/` history
- **outputs:**
  - `.shepherd/progress.md` updated with final architecture state, milestone-by-milestone summary, any deferred items, known limitations, and a "how to run argo update for a customer install" checklist
- **verification:** content reflects current truth; no contradictions with the code
- **est:** S

### Checkpoint M6 (final)
- [ ] All AC-1..AC-8 PASS
- [ ] Cross-cutting reviewer signs off
- [ ] No worktrees remain (`git worktree list` shows main only)
- [ ] `argo doctor --static`, `pytest -m 'not integration'`, `ruff check`, `ty check` all green on `main`
- [ ] `progress.md` reflects final state

---

## Acceptance-Criteria → Task Map

| Spec AC | Verified by |
|---|---|
| AC-1 (rename completeness after upstream commit) | T4.5 |
| **AC-2 (zero hermes in live I/O — KEY GATE)** | **T5.5** |
| AC-3 (idempotency) | T2.8 (synthetic) + re-verified at M4 checkpoint |
| AC-4 (merge conflict surface) | T4.6 |
| AC-5 (bootstrap works) | T3.4 |
| AC-6 (argo CLI launches with argo branding) | T3.4 |
| AC-7 (smoke chat with one tool call) | T5.5 |
| AC-8 (CI green) | T5.3 + T5.5 |

## Parallelization Map

| Milestone | Parallel-eligible tasks | Sequential tail |
|---|---|---|
| M1 | none (scaffolding is small + serial) | T1.1 → T1.2 → T1.3 |
| M2 | T2.2, T2.3, T2.4, T2.5 (after T2.1) | T2.1 → [4-way] → T2.6 → T2.7 → T2.8 |
| M3 | T3.4, T3.5 (after T3.3) | T3.1 → T3.2 → T3.3 → [2-way] |
| M4 | T4.1, T4.2, T4.3, T4.4 | [4-way] → T4.5 → T4.6 |
| M5 | T5.1, T5.2, T5.3 | [3-way] → T5.4 → T5.5 |
| M6 | T6.1, T6.2, T6.3 | [3-way] → T6.4 |

Max parallel fanout = 4 (M2 and M4). Within shepherd's max-5 budget.
