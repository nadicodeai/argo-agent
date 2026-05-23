# argo-agent Standards

Inherited from upstream hermes-agent (this is a fork — divergence in conventions costs us on every sync). All defaults below match the upstream `pyproject.toml` and ruff/ty/pytest configuration; deviate only with a written justification.

## Python

- Runtime: **`>=3.11`** (`[project.requires-python]`).
- Type-check target: **`3.13`** (`[tool.ty.environment]`).
- Always `from __future__ import annotations` in new modules unless you have a specific reason not to.
- Type hints on every public function and class attribute. `ty check` is part of CI.

## Dependencies

- **Exact pins only** (`==X.Y.Z`). No ranges, no `~=`, no `>=` upper-unbounded. Rationale documented in upstream pyproject.toml header.
- Regenerate `uv.lock` (`uv lock`) after every dependency change. CI runs `uv lock --check`.
- Add to `[project.dependencies]` only if every argo session needs the package. Provider-specific / backend-specific deps go in `[project.optional-dependencies]` and resolve at first use via `tools/lazy_deps.py` (inherited from upstream).
- No new runtime dependencies in this iteration. The rename engine uses stdlib + `pyyaml` (already present).

## Linting & Formatting

- **`ruff==0.15.10`** with the same single rule upstream enforces: `PLW1514` (unspecified-encoding).
  - Every `open() / read_text() / write_text() / Path.open()` MUST pass `encoding="utf-8"` explicitly. Upstream rationale (Windows cp1252 silent corruption) still applies.
- `ruff format .` is the formatter. Don't argue with it.
- Per-file ignores match upstream: tests can use bare `open()`; skills/plugins are user-authored.

## Type Checker

- **`ty==0.0.21`** (Astral).
- `[tool.ty.rules]` matches upstream: `unknown-argument = "warn"`, `redundant-cast = "ignore"`.
- Don't add new strict rules without a separate review — drift here makes upstream sync noisy.

## Tests

- **`pytest==9.0.2`** with `pytest-asyncio==1.3.0`, `pytest-timeout==2.4.0`.
- Layout: `tests/` mirrors source tree. `tests/fixtures/` for static fixture trees. `tests/test_*.py` for test modules.
- Markers (inherited): `integration` (external services required), `real_concurrent_gate` (opts out of an autouse stub).
- Default per-test timeout: **30 s, signal method** (`addopts = "-m 'not integration' --timeout=30 --timeout-method=signal"`).
- Slow / external-service tests MUST be marked `integration` so CI skips them by default.
- New rename-engine tests live under `tests/` and run by default (no marker).
- Coverage expectations: rename engine (`argo_sync/`) → high coverage (every pass + idempotency + edge cases). CLI commands → smoke + happy-path. Integration tests → AC-1 through AC-8 each have a dedicated test.

## File I/O

- Always `encoding="utf-8"` (PLW1514). Repeating because it bites.
- JSON files: deterministic key order (`json.dumps(..., sort_keys=True, indent=2)`) for any file we commit. Manifest is the canonical example.
- YAML files: `ruamel.yaml` for round-trip-preserving edits, `pyyaml` for simple loads. Match the upstream style.

## Naming

- Modules: `lower_snake_case`. After the rename, no module name contains `hermes`.
- Classes: `UpperCamelCase`. After the rename, no class name contains `Hermes`.
- Constants: `UPPER_SNAKE_CASE`. After the rename, no constant prefix contains `HERMES`.
- Env vars: `ARGO_*`. After the rename, no env var starts with `HERMES_`.
- CLI subcommands: `kebab-case` (e.g. `argo update`, `argo doctor`).
- File paths in code: forward slashes, `pathlib.Path` not raw strings.

## Errors

- Never `raise Exception("...")`. Raise a specific subclass with context:

  ```python
  class RenameConflictError(RuntimeError):
      def __init__(self, source: Path, target: Path):
          super().__init__(f"rename conflict: {source} → {target} (target exists)")
          self.source = source
          self.target = target
  ```

- Domain errors live in `argo_sync/errors.py`.
- CLI surfaces user-facing errors with `rich` (already an upstream dep) — color, traceback only with `--debug`.

## Git Discipline

- Commits on `main`: imperative subject ≤72 chars. Body explains the *why* when non-obvious.
- Sync commits use a fixed format: `sync: upstream <short-sha> (<N files renamed>)`. Mechanical — produced by `argo update` itself.
- Bootstrap commit (one-time): `bootstrap: initial argo rename from hermes-agent@<sha>`.
- Never force-push `main` or `upstream-mirror`.
- Never `git push upstream` (read-only remote).
- Branch names: feature branches off `main`, named `argo/<topic>` (e.g. `argo/rename-engine`).

## Architecture Boundaries

- `argo_sync/` (the rename engine) MUST NOT import from `argo_cli/` or any other argo package. It's a standalone library; the CLI imports the engine, not the reverse.
- `bin/argo-sync` is a thin script: argparse + delegate to `argo_sync`. No business logic.
- `bin/argo-bootstrap.py` is single-use (one-time setup). Doesn't need to be installable as a CLI.
- The rename engine NEVER reaches into argo's own source tree to rename itself. It's run by the developer on a fresh hermes clone — never on a working argo-agent.

## Documentation

- Module docstrings on every public module.
- One-line summaries on public functions; richer docstrings only when the why is non-obvious.
- No `TODO:` left in committed code without a tracking issue / progress.md entry.
- README is argo-branded after M6. No README mention of hermes.

## Performance

- `argo update` budget: under 2 minutes on a typical upstream delta (≤200 files). If a sync exceeds this in practice, profile the rename engine before adding deps.
- Rename engine traversal: `pathlib.Path.rglob` is fine; avoid spawning subprocesses per file.

## Security

- No secrets in code or fixtures.
- `.env` files always in `.gitignore`.
- Model API keys come from env vars at runtime; never persisted to disk by argo itself.
- `exceptions:` entries in `argo-rename.yaml` MUST have a one-line justification comment. Reviewer rejects unjustified entries.
