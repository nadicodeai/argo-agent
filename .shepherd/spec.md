## Confirmed Intent

- Outcome:      A new GitHub repo `argo-agent` (initially private) — a deeply renamed fork of
                hermes-agent where every "hermes/Hermes/HERMES" string is rewritten to
                "argo/Argo/ARGO" across filenames, Python package, identifiers, docs,
                AGENTS.md, .env.example, READMEs, log strings — anywhere the LLM might surface
                it. Plus a one-command `argo update` that pulls upstream hermes-agent changes
                and re-applies the rename deterministically.

- User:         Vadim, operating a new B2B business that deploys this agent into
                customer companies under the "argo" brand. Customers see only "argo".

- Why now:      Entering the market with this product. Customers must see the "argo" brand,
                not the upstream's. The LLM-reads-filesystem problem means a runtime label
                swap is insufficient — only a deep rename works. Must continue benefiting
                from upstream hermes-agent improvements without manually re-doing the rename.

- Success:      (1) `git clone argo-agent && pip install -e . && argo <chat-command>` boots
                an end-to-end argo deployment with zero "hermes" leakage in any
                user-visible surface (chat replies, logs, error messages, help text, file
                paths the model reports). Verified by an automated "leakage scan" that runs
                argo in a real conversation and greps outputs.
                (2) `argo update` cleanly pulls latest upstream hermes-agent into the
                renamed fork in a single command, with zero hermes references reintroduced
                after the sync completes.
                (3) A real argo deployment is exercised end-to-end (boot, chat, at least
                one tool call) as part of acceptance — not just unit tests on the rename
                script.

- Constraint:   Upstream-sync simplicity is paramount — argo-agent must stay close enough to
                hermes-agent that pulling upstream is one boring command, not a merge
                ordeal. Therefore: minimize hand-edits in `main`; all transformations live
                in a deterministic `argo-rename.yaml` config + script. Allowlist of
                "must stay hermes" identifiers starts EMPTY and grows only if a specific
                integration breaks (no preemptive compat shims).

- Out of scope: - Per-deployment customization of skills/tools (v2; this iteration is purely
                  the rebrand + sync mechanism)
                - Migrating any existing hermes-agent installs to argo (greenfield only)
                - Publishing argo-agent to PyPI in this iteration (private repo, install
                  from source)
                - Upstreaming a "BRAND_NAME" config patch back to hermes-agent (could
                  simplify future syncs but is a separate workstream)
                - Trademark/IP/legal review of the "argo" name (handled separately)

## Tech Stack

Inherited from hermes-agent (this is a fork; we MUST stay aligned):

- Python `>=3.11` runtime; type-check target `3.13` (per `[tool.ty.environment]`).
- Build backend: `setuptools>=61.0` via `pyproject.toml`.
- Dependency management: exact-pinned (`==X.Y.Z`) — no ranges. Lockfile via `uv lock`.
- Test framework: `pytest==9.0.2` with `pytest-asyncio`, `pytest-timeout` (30s per test, signal method).
- Linter: `ruff==0.15.10` — only `PLW1514` (unspecified-encoding) currently enabled.
- Type checker: `ty==0.0.21` (Astral).
- Console scripts: `argo` (replaces `hermes`), `argo-agent` (replaces `hermes-agent`), `argo-acp` (replaces `hermes-acp`).
- Top-level Python package after rename: `argo_agent` (replaces `hermes_agent`); plus renamed top-level modules `argo_bootstrap`, `argo_constants`, `argo_state`, `argo_time`, `argo_logging`, `argo_cli`.

New artifacts (NOT in upstream):

- `bin/argo-sync` — Python script, executable, no shell-isms.
- `argo-rename.yaml` — declarative rename config (mappings + exceptions).
- `.argo/sync-manifest.json` — generated per sync; not hand-edited.
- `tests/test_leakage_scan.py` — static scan asserting zero "hermes" hits outside exceptions.
- `tests/test_deployment_smoke.py` — boots argo end-to-end and asserts no leakage in I/O.

## Commands

Run from repo root. All paths are POSIX.

| Purpose | Command |
|---|---|
| Install dev | `uv sync --all-extras` (or `pip install -e '.[dev]'`) |
| Run argo CLI | `argo` |
| Update from upstream | `argo update` |
| Run leakage scan (static) | `argo doctor --static` |
| Run leakage scan (live) | `argo doctor --live` |
| Test suite | `pytest -m 'not integration'` |
| Integration tests | `pytest -m integration` |
| Type-check | `ty check` |
| Lint | `ruff check .` |
| Format | `ruff format .` |
| One-time bootstrap | `python bin/argo-bootstrap.py <hermes-checkout>` |
| Manual rename pass | `python bin/argo-sync --rename-only` |
| Manual upstream merge | `python bin/argo-sync --merge-only` |

## Project Structure

```
argo-agent/
├── .argo/
│   └── sync-manifest.json          # Generated per sync; last upstream sha, file touch log.
├── .shepherd/                      # Orchestrator state (this spec + plan + progress).
├── bin/
│   ├── argo-sync                   # Rename + sync engine (entry script).
│   └── argo-bootstrap.py           # One-time: hermes checkout → argo-agent.
├── argo-rename.yaml                # Declarative rename mappings + exceptions.
├── argo_agent/                     # Renamed Python package (was hermes_agent).
├── argo_cli/                       # CLI module (was hermes_cli) — hosts `argo update`,
│                                   # `argo doctor`, and all original CLI surfaces.
├── argo_constants.py               # Was hermes_constants.py.
├── argo_state.py                   # Was hermes_state.py.
├── argo_time.py                    # Was hermes_time.py.
├── argo_logging.py                 # Was hermes_logging.py.
├── argo_bootstrap.py               # Was hermes_bootstrap.py.
├── acp_adapter/, acp_registry/     # Unchanged dir names; contents rewritten.
├── agent/, tools/, gateway/, …     # Unchanged dir names; contents rewritten.
├── tests/
│   ├── test_leakage_scan.py        # Static repo grep, asserts zero hermes hits.
│   ├── test_deployment_smoke.py    # Boots argo + chats + greps I/O.
│   └── (everything else inherited from upstream, renamed)
├── pyproject.toml                  # name = "argo-agent"; all self-refs renamed.
└── README.md                       # Argo branding; one-line note on upstream provenance.
```

## Code Style

Python: PEP 8 baseline, ruff-formatted. Real example of the rename engine's core:

```python
# bin/argo-sync entry point — pure-Python, no shell-isms.
from pathlib import Path
import json
import sys
from dataclasses import dataclass

from argo_sync.config import RenameConfig          # loads argo-rename.yaml
from argo_sync.engine import RenameEngine          # idempotent, ordered passes
from argo_sync.git_ops import (
    fetch_upstream,
    merge_upstream_mirror,
    merge_into_main,
    commit_sync,
)

@dataclass(frozen=True)
class SyncResult:
    upstream_sha: str
    files_touched: tuple[Path, ...]
    diff_empty: bool        # True on repeat runs against the same upstream sha


def run_sync(repo: Path, *, write_manifest: bool = True) -> SyncResult:
    cfg = RenameConfig.load(repo / "argo-rename.yaml")
    upstream_sha = fetch_upstream(repo)
    merge_upstream_mirror(repo, upstream_sha)
    merge_into_main(repo)                          # surfaces conflicts in hermes shape
    engine = RenameEngine(cfg)
    touched = engine.apply(repo)
    if write_manifest:
        manifest = repo / ".argo" / "sync-manifest.json"
        manifest.parent.mkdir(exist_ok=True)
        manifest.write_text(
            json.dumps(
                {"upstream_sha": upstream_sha, "files_touched": sorted(map(str, touched))},
                indent=2,
            ),
            encoding="utf-8",
        )
    commit_sync(repo, upstream_sha)
    return SyncResult(upstream_sha, tuple(touched), diff_empty=not touched)
```

Conventions:

- Always pass `encoding="utf-8"` to `open()/read_text()/write_text()` — ruff PLW1514 enforces this and the upstream rationale (Windows cp1252 corruption) still applies to us.
- Type hints on every public function. `ty check` is part of CI.
- Pure functions where possible; side effects in `git_ops`/`engine.apply` only.
- Errors carry context — never `raise Exception("bad")`; raise `RenameConflictError` / `UpstreamMergeConflict` with the path and line.

## Functional Requirements

FR-1. **bin/argo-sync — idempotent rename pass.** Re-running against an unchanged working tree produces zero diffs.

FR-2. **bin/argo-sync — ordered transformations.** Rename order = (a) content within files, (b) file renames, (c) directory renames, processed bottom-up so parents rename after children. Prevents clobbering.

FR-3. **bin/argo-sync — declarative config.** All mappings live in `argo-rename.yaml`. Mappings include case variants (`hermes`, `Hermes`, `HERMES`), identifier joiners (`hermes_`, `hermes-`), composite tokens (`HermesAgent` → `ArgoAgent`, `hermes-agent` → `argo-agent`), and path prefixes (`~/.hermes` → `~/.argo`). Plus an `exceptions:` list of literal substrings or glob paths that MUST keep "hermes" (initially empty).

FR-4. **bin/argo-sync — sync manifest.** After a successful sync, writes `.argo/sync-manifest.json` containing `{upstream_sha, files_touched, exceptions_used, ran_at}`. Git-committed alongside the merge.

FR-5. **argo update — single command.** Invokes the full workflow: `git fetch upstream` → checkout `upstream-mirror` → `git merge upstream/main` → checkout `main` → `git merge upstream-mirror` → run rename engine → `git commit -m "sync: <upstream-sha>"`. Exits non-zero on any unresolved conflict and prints next-step instructions.

FR-6. **argo doctor --static.** Greps the entire working tree for case-insensitive `hermes` and reports any hit not covered by the exceptions list. Exit 0 on clean, non-zero otherwise. CI runs this on every commit.

FR-7. **argo doctor --live.** Spawns argo as a subprocess, sends a scripted prompt that exercises one tool call, captures stdout/stderr/logs, then greps the captured I/O for case-insensitive `hermes`. Exit 0 on clean.

FR-8. **bin/argo-bootstrap.py — one-time.** Given a fresh hermes-agent checkout path, produces an initial argo-agent: sets up the two remotes, creates `upstream-mirror` from current upstream HEAD, creates `main` from `upstream-mirror`, runs the rename engine on `main`, commits as "bootstrap: initial argo rename from hermes-agent@<sha>".

FR-9. **pyproject.toml rewrites.** The rename engine rewrites self-references (`hermes-agent[cron]` → `argo-agent[cron]`), `[project.scripts]` entries, `py-modules`, package globs in `[tool.setuptools.packages.find]`, and `[tool.setuptools.package-data]` keys.

FR-10. **No new runtime dependencies.** The rename engine uses stdlib + `pyyaml` (already an upstream dep). Tests use `pytest` (already there).

## Behavioral Acceptance Criteria (Given/When/Then)

**AC-1 (rename completeness)** — Given a fresh upstream commit on hermes-agent, when I run `argo update`, then the working tree contains the new upstream changes with all hermes strings rewritten to argo and zero hermes references remain outside the explicit `exceptions:` list.

**AC-2 (deployment leakage — KEY GATE)** — Given an installed argo-agent, when I run `argo` and exchange one message that triggers a tool call, then no string `hermes` (case-insensitive) appears in stdout, stderr, log files, or temp file names produced during the session.

**AC-3 (idempotency)** — Given the same upstream sha, when I run `argo update` twice in a row, then the second run produces an empty diff and exits 0.

**AC-4 (merge conflict surface)** — Given an upstream merge conflict during sync, when `argo update` runs, then it surfaces the conflict in hermes-shape (i.e., before the rename pass) on the `upstream-mirror` branch, leaves the tree in a recoverable state, exits non-zero, and prints "resolve conflicts on upstream-mirror, then run `argo update --resume`."

**AC-5 (bootstrap)** — Given a fresh hermes-agent clone at path `P`, when I run `python bin/argo-bootstrap.py P`, then the resulting `argo-agent` repo is `pip install -e .`-installable, `argo --help` works, and `argo doctor --static` exits 0.

**AC-6 (real install boots)** — Given the bootstrapped repo and a venv, when I run `pip install -e '.[dev]'` then `argo`, then the CLI launches without ImportError and the help banner contains "argo" and not "hermes".

**AC-7 (smoke chat)** — Given a configured model (cheapest available — e.g. an OpenAI-compatible local stub or a real cheap model), when I run the scripted smoke test, then argo completes a one-turn conversation, invokes at least one tool, and `argo doctor --live` exits 0 on the captured I/O.

**AC-8 (CI-runnable subset)** — Given GitHub Actions, when the workflow runs, then `pytest -m 'not integration'`, `ruff check`, `ty check`, and `argo doctor --static` all pass. (The live smoke is run locally; CI gets static-only.)

## Non-Functional Requirements

- NFR-1. `argo update` completes in under 2 minutes on a typical upstream delta (≤200 changed files).
- NFR-2. `bin/argo-sync` is pure Python (no shell pipelines). Runs on Linux + macOS.
- NFR-3. Repo size: argo-agent should not grow more than +1% over upstream hermes-agent after rename (the rename should not duplicate content).
- NFR-4. Rename engine is deterministic: identical inputs always produce identical outputs; file ordering is stable.

## Resolved Decisions (formerly Open Questions)

- **D-1. CI strategy.** GitHub Actions runs `pytest -m 'not integration'`, `ruff check`, `ty check`, `argo doctor --static`, and the stub-model integration smoke. Live-model smoke runs locally pre-release via a checklist. Rationale: API keys in CI cost money + add security surface + introduce flakiness; the deterministic case is fully covered by static + stub.
- **D-2. No `UPSTREAM.md`.** No customer-visible file describes the upstream relationship. Sync mechanism is documented inline in `argo update --help` output and in `bin/argo-sync` source comments. The ONLY directory exempt from the leakage scan is `.shepherd/` (orchestrator memory — by definition contains the word "hermes" while the project is in progress). This is a single narrow exception.
- **D-3. Hard rename `HERMES_HOME` → `ARGO_HOME`.** No dual-read, no warning shim. Greenfield deployments only, no legacy env vars to honor.

## Upstream Relationship (explicit non-goals)

- argo-agent is an **independent private GitHub repo**, not a GitHub fork. GitHub forks expose a public parent-link via the GitHub API; we don't want that.
- The `upstream` git remote is **read-only**. We `git fetch upstream` and `git merge` locally. We never `git push upstream`, never open PRs upstream, never propose changes to NousResearch/hermes-agent. Any contribution back to hermes-agent (e.g., a "BRAND_NAME config" PR) is an explicit separate workstream out of scope here.

## Boundaries

- **Always:**
  - Run `argo doctor --static` before any commit that touched repo contents.
  - Treat `argo-rename.yaml` as load-bearing — every change to it MUST pass `argo doctor --static`.
  - Pass `encoding="utf-8"` on every file I/O (PLW1514).
  - Keep the `exceptions:` list explicit and reviewed — never add an entry without a one-line justification comment.
- **Ask first:**
  - Adding any new top-level Python dependency.
  - Hand-editing files on `main` that weren't produced by the rename engine (creates sync drift).
  - Changing the rename ordering (content → files → dirs) — has correctness implications.
  - Submitting a "BRAND_NAME config" PR upstream (separate workstream, deferred).
- **Never:**
  - Commit secrets or `.env` files.
  - Add an `exceptions:` entry "just in case" — entries must be evidence-driven (some integration broke).
  - Force-push `main` or `upstream-mirror` without explicit user approval.
  - Skip the rename idempotency check after a sync.
  - **Push to `upstream`** under any circumstance. `upstream` is read-only. No `git push upstream`, no PRs against NousResearch/hermes-agent. Argo development never modifies the upstream project.
  - Make argo-agent a GitHub fork of hermes-agent (use an independent private repo + `upstream` remote instead).

