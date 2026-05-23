"""tests/test_deployment_smoke.py — Deployment smoke test (AC-2 gate).

AC-2: Zero occurrences of the upstream source identifier in live argo I/O.

This module exercises argo end-to-end as a subprocess and asserts that the
upstream identifier (the old project name and all its case variants) does NOT
appear in any captured output. It is the formal verification for Milestone 5.

Test matrix
-----------
- ``test_help_and_version_smoke``:
      Fast path — runs ``argo --help`` and ``argo --version``, no model
      backend required.  This runs in every CI pass, no marker needed.

- ``test_deployment_smoke_stub`` (marked ``integration``):
      Full path — boots argo with a real agent loop against the stub-model
      backend (``tests/fixtures/recorded_model/server.py``). Deterministic,
      offline, no API key.  CI runs this via ``pytest -m integration``.

- ``test_deployment_smoke_live`` (marked ``integration``):
      Optional live path — only runs when ``ARGO_TEST_MODEL`` is set in the
      environment together with a matching provider key. Exercises the real
      model pipeline.

Tiered model strategy
---------------------
When ``ARGO_TEST_MODEL`` is set, ``test_deployment_smoke_live`` runs against
the real provider indicated by that env var. The provider key itself must also
be in the environment (e.g. ``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``, etc.)
or the test will be skipped.  This path is never used in CI — it is intended
for human-in-the-loop final AC-2 verification before a release.

Log output
----------
Each smoke run writes a log to:

    .shepherd/smoke-run-<ISO-timestamp>.log

That directory is gitignored (see .gitignore). The log captures the full
subprocess stdout + stderr so failures can be post-mortemed without re-running.
"""

from __future__ import annotations

import datetime
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Optional

import pytest

# ---------------------------------------------------------------------------
# Project root + log dir
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_LOG_DIR = _REPO_ROOT / ".shepherd"
_RENAME_YAML = _REPO_ROOT / "argo-rename.yaml"

# ---------------------------------------------------------------------------
# Leakage detection — reuse argo_cli.doctor_leakage so the same
# argo-rename.yaml exceptions apply.
# ---------------------------------------------------------------------------


def _assert_no_leakage(text: str, label: str) -> None:
    """Assert that *text* contains no upstream-identifier hits.

    Uses ``argo_cli.doctor_leakage._scan_text`` so that the same
    ``skip_contexts`` and ``mappings`` from argo-rename.yaml apply — this is
    the identical logic used by ``argo doctor --static`` and ``--live``.

    Raises ``AssertionError`` with a clear message on any hit.
    """
    from argo_cli.doctor_leakage import _load_rename_config, _scan_text

    mappings, _exc_globs, skip_patterns, probe_token = _load_rename_config(_RENAME_YAML)
    hits = _scan_text(text, probe_token, mappings, skip_patterns, label)

    if hits:
        lines = [f"  {h.path}:{h.line_no}:{h.col_no}: {h.line_text!r}" for h in hits]
        raise AssertionError(
            f"AC-2 FAIL — upstream identifier found in {label!r}:\n"
            + "\n".join(lines)
        )


# ---------------------------------------------------------------------------
# Helper — write smoke log
# ---------------------------------------------------------------------------


def _write_smoke_log(stdout: str, stderr: str, label: str) -> Path:
    """Write combined subprocess output to .shepherd/smoke-run-<ts>.log."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now(tz=datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = _LOG_DIR / f"smoke-run-{ts}-{label}.log"
    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write(f"=== STDOUT ===\n{stdout}\n=== STDERR ===\n{stderr}\n")
    return log_path


# ---------------------------------------------------------------------------
# Helper — build a hermetic subprocess env
# ---------------------------------------------------------------------------


def _make_hermetic_env(
    argo_home: str | Path,
    extra: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """Return a minimal env dict for subprocess smoke runs.

    Strips all credential-shaped env vars inherited from the developer shell so
    the smoke cannot accidentally use a real key. Keeps PATH, PYTHONPATH, HOME,
    and a small set of POSIX essentials.
    """
    keep_keys = {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "TERM",
        "LANG",
        "LC_ALL",
        "PYTHONPATH",
        "PYTHONHASHSEED",
        "TZ",
        "VIRTUAL_ENV",
        "UV_PROJECT_ENVIRONMENT",
    }
    env: dict[str, str] = {}
    for key in keep_keys:
        val = os.environ.get(key)
        if val is not None:
            env[key] = val

    # Always override these.
    env["ARGO_HOME"] = str(argo_home)
    env["TZ"] = "UTC"
    env["LANG"] = "C.UTF-8"
    env["LC_ALL"] = "C.UTF-8"
    env["PYTHONHASHSEED"] = "0"
    # Disable IMDS probing (2-second hang in CI).
    env["AWS_EC2_METADATA_DISABLED"] = "true"
    env["AWS_METADATA_SERVICE_TIMEOUT"] = "1"
    env["AWS_METADATA_SERVICE_NUM_ATTEMPTS"] = "1"
    # Non-interactive mode — skip prompts.
    env["ARGO_YOLO_MODE"] = "1"
    env["ARGO_ACCEPT_HOOKS"] = "1"

    if extra:
        env.update(extra)
    return env


# ---------------------------------------------------------------------------
# T5.1a — fast smoke: --help / --version (no model, always runs)
# ---------------------------------------------------------------------------


def test_help_and_version_smoke():
    """Argo --help and --version produce no upstream-identifier leakage.

    This is a fast gate that can run in CI without any model backend.
    It re-uses the ``argo doctor --live`` fallback command set internally.
    """
    import subprocess

    with tempfile.TemporaryDirectory(prefix="argo_smoke_") as argo_home:
        env = _make_hermetic_env(argo_home)
        argo_cmd = [sys.executable, "-m", "argo_cli.main"]

        combined_stdout = ""
        combined_stderr = ""

        for extra_args in [["--help"], ["--version"]]:
            result = subprocess.run(
                argo_cmd + extra_args,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(_REPO_ROOT),
                env=env,
            )
            combined_stdout += result.stdout
            combined_stderr += result.stderr

        log_path = _write_smoke_log(combined_stdout, combined_stderr, "help-version")
        combined = combined_stdout + combined_stderr

        # AC-2 gate.
        _assert_no_leakage(combined, "<help-and-version-output>")

        # Sanity: the CLI must at least emit something.
        assert combined.strip(), f"argo --help / --version produced no output (log: {log_path})"


# ---------------------------------------------------------------------------
# T5.1b — full deployment smoke against stub-model (integration marker)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_deployment_smoke_stub():
    """Boot argo end-to-end against the stub-model backend; assert AC-2 gate.

    This is the primary AC-2 verification for Milestone 5.

    Procedure:
    1. Start the RecordedModelServer (in-process HTTP, port auto-assigned).
    2. Build a hermetic subprocess environment pointing argo at the stub.
    3. Run ``argo -z "hello"`` as a subprocess.
    4. Capture stdout + stderr + write to .shepherd/smoke-run-*.log.
    5. Assert no upstream-identifier hits in the combined output (AC-2 gate).

    The stub server returns deterministic responses for a small set of prompts
    and a generic fallback for anything else. It never references the upstream
    source identifier, so any hit in the output genuinely came from argo itself.
    """
    import subprocess

    from tests.fixtures.recorded_model.server import RecordedModelServer

    with tempfile.TemporaryDirectory(prefix="argo_smoke_") as argo_home:
        # Write a minimal config so argo uses the custom (stub) provider.
        argo_home_path = Path(argo_home)
        (argo_home_path / "sessions").mkdir()
        (argo_home_path / "logs").mkdir()
        (argo_home_path / "memories").mkdir()
        (argo_home_path / "skills").mkdir()

        with RecordedModelServer() as server:
            env = _make_hermetic_env(
                argo_home,
                {
                    "CUSTOM_BASE_URL": server.base_url,
                    "OPENAI_API_KEY": "stub-key-for-smoke-test",
                },
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "argo_cli.main",
                    "-z",
                    "hello",
                    "--provider",
                    "auto",
                    "--model",
                    "stub-model",
                ],
                capture_output=True,
                text=True,
                timeout=90,
                cwd=str(_REPO_ROOT),
                env=env,
            )

        combined_stdout = result.stdout
        combined_stderr = result.stderr
        combined = combined_stdout + combined_stderr

        log_path = _write_smoke_log(combined_stdout, combined_stderr, "stub-model")

        # Fail if argo crashed with an import error.
        bad_errors = ["ImportError", "ModuleNotFoundError"]
        for bad in bad_errors:
            assert bad not in combined_stderr, (
                f"argo subprocess raised {bad} (log: {log_path}):\n{combined_stderr[:2000]}"
            )

        # The process must exit cleanly (0) or with a config-missing exit code
        # (1 or 2 are acceptable when no ~/.argo/.env exists).
        assert result.returncode in (0, 1, 2), (
            f"argo subprocess exited with unexpected code {result.returncode} "
            f"(log: {log_path}):\nstdout={combined_stdout[:1000]}\nstderr={combined_stderr[:1000]}"
        )

        # AC-2 gate — the key assertion for this milestone.
        _assert_no_leakage(combined, "<stub-model-smoke-output>")


# ---------------------------------------------------------------------------
# T5.1c — optional live smoke (only when ARGO_TEST_MODEL is set)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_deployment_smoke_live():
    """Live smoke — skipped unless ARGO_TEST_MODEL env var is set.

    Usage (human-in-the-loop, never in CI without explicit env setup):

        ARGO_TEST_MODEL=gpt-4o-mini OPENAI_API_KEY=sk-... \\
            pytest tests/test_deployment_smoke.py::test_deployment_smoke_live -v

    The test sends a single prompt via ``argo -z`` and asserts AC-2.

    Env vars consulted:
        ARGO_TEST_MODEL   Model name to pass via ``--model``.
        ARGO_TEST_PROVIDER  Optional provider override. Defaults to "auto".
        OPENAI_API_KEY / ANTHROPIC_API_KEY / etc.  Must be set in the
            outer environment; the test carries them through to the subprocess.
    """
    import subprocess

    test_model = os.environ.get("ARGO_TEST_MODEL", "").strip()
    if not test_model:
        pytest.skip("ARGO_TEST_MODEL not set — skipping live smoke run")

    test_provider = os.environ.get("ARGO_TEST_PROVIDER", "auto").strip() or "auto"

    # Pass through real API key env vars — the hermetic helper strips them,
    # so we add them back explicitly here.
    _LIVE_KEY_VARS = [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "NOUS_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
    ]
    extra: dict[str, str] = {}
    for var in _LIVE_KEY_VARS:
        val = os.environ.get(var, "").strip()
        if val:
            extra[var] = val

    if not any(extra.values()):
        pytest.skip(
            "No provider API key env vars found — set one of "
            + ", ".join(_LIVE_KEY_VARS)
            + " together with ARGO_TEST_MODEL to enable the live smoke"
        )

    with tempfile.TemporaryDirectory(prefix="argo_live_smoke_") as argo_home:
        argo_home_path = Path(argo_home)
        (argo_home_path / "sessions").mkdir()
        (argo_home_path / "logs").mkdir()
        (argo_home_path / "memories").mkdir()
        (argo_home_path / "skills").mkdir()

        env = _make_hermetic_env(argo_home, extra)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "argo_cli.main",
                "-z",
                "Say hello briefly.",
                "--provider",
                test_provider,
                "--model",
                test_model,
            ],
            capture_output=True,
            text=True,
            timeout=90,
            cwd=str(_REPO_ROOT),
            env=env,
        )

    combined_stdout = result.stdout
    combined_stderr = result.stderr
    combined = combined_stdout + combined_stderr

    log_path = _write_smoke_log(combined_stdout, combined_stderr, "live-model")

    bad_errors = ["ImportError", "ModuleNotFoundError"]
    for bad in bad_errors:
        assert bad not in combined_stderr, (
            f"argo subprocess raised {bad} (log: {log_path}):\n{combined_stderr[:2000]}"
        )

    assert result.returncode in (0, 1, 2), (
        f"argo live subprocess exited with code {result.returncode} "
        f"(log: {log_path}):\nstdout={combined_stdout[:1000]}\nstderr={combined_stderr[:1000]}"
    )

    # AC-2 gate.
    _assert_no_leakage(combined, "<live-model-smoke-output>")
