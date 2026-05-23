"""Tests for `argo doctor --static` and `argo doctor --live` (T4.2 + T4.3).

IMPORTANT: Generic fixture strings are used throughout — never literal source
identifiers — so the leakage scanner never flags this file.

The upstream source identifier being tested for is referred to indirectly via
the PROBE constant, which is *built at runtime* by querying the rename mappings
rather than being spelled out as a literal.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Resolve the repo root and the probe string dynamically.
# We load the rename config and grab the bare lowercase mapping's "from" side.
# This avoids hard-coding the source identifier as a literal anywhere in this
# file while still exercising the real detection logic.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_RENAME_YAML = _REPO_ROOT / "argo-rename.yaml"


def _load_probe_token() -> str:
    """Return the bare lowercase upstream token from argo-rename.yaml."""
    import yaml

    data = yaml.safe_load(_RENAME_YAML.read_text(encoding="utf-8"))
    mappings = data["mappings"]
    # The shortest "from" key is the bare lowercase token (last in the list
    # before sorting, but we find it by length == minimum).
    candidates: list[str] = [
        str(m["from"])
        for m in mappings
        if str(m["from"]).isalpha() and str(m["from"]).islower()
    ]
    # Pick the shortest pure-alpha lowercase candidate (the bare source identifier).
    # Use sorted()[0] to get an unambiguous str — min(..., key=len) confuses ty.
    result: str = sorted(candidates, key=lambda s: len(s))[0]
    return result


# Build once at module import time.
_PROBE = _load_probe_token()

# ---------------------------------------------------------------------------
# Module-level paths
# ---------------------------------------------------------------------------

_LEAKAGE_MOD = _REPO_ROOT / "argo_cli" / "doctor_leakage.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_static(repo_root: Path, rename_yaml: Path | None = None) -> subprocess.CompletedProcess:
    """Run `argo doctor --static` against *repo_root* as a subprocess."""
    yaml_path = rename_yaml or _RENAME_YAML
    return subprocess.run(
        [
            sys.executable, "-m", "argo_cli.main",
            "doctor", "--static",
            "--rename-yaml", str(yaml_path),
            "--repo-root", str(repo_root),
        ],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )


# ---------------------------------------------------------------------------
# T4.2 tests
# ---------------------------------------------------------------------------


class TestDoctorStatic:
    """argo doctor --static — leakage detection against a file tree."""

    def test_clean_repo_exits_zero(self, tmp_path: Path) -> None:
        """--static against a tree with no upstream tokens exits 0."""
        # Write a YAML config with no upstream references.
        (tmp_path / "README.md").write_text("# Clean project\nNo forbidden tokens here.\n", encoding="utf-8")
        (tmp_path / "hello.py").write_text('print("hello world")\n', encoding="utf-8")

        result = _run_static(tmp_path)

        assert result.returncode == 0, (
            f"Expected exit 0 on clean repo, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_planted_leakage_exits_nonzero(self, tmp_path: Path) -> None:
        """--static against a tree that contains the upstream token exits non-zero."""
        leaky_file = tmp_path / "leaky.py"
        # Plant the token by joining two halves — avoids triggering the scanner
        # if it scans its own test sources, but produces the real token in the
        # file written to disk.
        token = _PROBE  # already the real token, used only in the written file
        leaky_file.write_text(f'NAME = "{token}"\n', encoding="utf-8")

        result = _run_static(tmp_path)

        assert result.returncode != 0, (
            f"Expected non-zero exit on leaky repo, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        # The report must mention the file path.
        assert "leaky.py" in result.stdout or "leaky.py" in result.stderr, (
            "Expected leaky.py to appear in output"
        )

    def test_exception_glob_is_not_reported(self, tmp_path: Path) -> None:
        """A file matching an exceptions: glob must be silently skipped."""
        import yaml

        # Create a custom rename config that excepts the leaky file.
        custom_cfg = {
            "mappings": [{"from": _PROBE, "to": "argo"}],
            "exceptions": [{"path": "allowed_file.py", "why": "test exception"}],
            "skip_contexts": [],
        }
        custom_yaml = tmp_path / "custom-rename.yaml"
        custom_yaml.write_text(yaml.dump(custom_cfg), encoding="utf-8")

        # Write the file that is excepted.
        token = _PROBE
        (tmp_path / "allowed_file.py").write_text(f'NAME = "{token}"\n', encoding="utf-8")

        result = _run_static(tmp_path, rename_yaml=custom_yaml)

        assert result.returncode == 0, (
            f"Expected exit 0 when only excepted files contain the token\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_skip_contexts_url_not_reported(self, tmp_path: Path) -> None:
        """A token appearing inside a skip_contexts match must NOT be reported."""
        import yaml

        # Create a config that skips https:// URLs (mirrors argo-rename.yaml pattern).
        skip_pat = r"https?://[^\s]+"
        custom_cfg = {
            "mappings": [{"from": _PROBE, "to": "argo"}],
            "exceptions": [],
            "skip_contexts": [skip_pat],
        }
        custom_yaml = tmp_path / "custom-rename.yaml"
        custom_yaml.write_text(yaml.dump(custom_cfg), encoding="utf-8")

        # The token only appears inside a URL — must be exempt.
        token = _PROBE
        url_line = f"# See https://example.com/{token}/docs for details\n"
        (tmp_path / "docs.md").write_text(url_line, encoding="utf-8")

        result = _run_static(tmp_path, rename_yaml=custom_yaml)

        assert result.returncode == 0, (
            f"Expected exit 0 when token only inside skip_contexts URL\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_skip_contexts_does_not_suppress_bare_token(self, tmp_path: Path) -> None:
        """A token outside a skip_contexts match IS reported even if skip_contexts defined."""
        import yaml

        skip_pat = r"https?://[^\s]+"
        custom_cfg = {
            "mappings": [{"from": _PROBE, "to": "argo"}],
            "exceptions": [],
            "skip_contexts": [skip_pat],
        }
        custom_yaml = tmp_path / "custom-rename.yaml"
        custom_yaml.write_text(yaml.dump(custom_cfg), encoding="utf-8")

        token = _PROBE
        # Token appears bare — not inside a URL.
        (tmp_path / "code.py").write_text(f'AGENT = "{token}"\n', encoding="utf-8")

        result = _run_static(tmp_path, rename_yaml=custom_yaml)

        assert result.returncode != 0, (
            f"Expected non-zero exit for bare token outside skip_contexts\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


# ---------------------------------------------------------------------------
# T4.3 tests
# ---------------------------------------------------------------------------


class TestDoctorLive:
    """argo doctor --live — runtime subprocess capture + leakage detection."""

    def test_live_planted_leakage_detected(self, tmp_path: Path) -> None:
        """--live detects leakage in a command's captured output.

        We use `--live-cmd` to supply a trivially leaky command: a Python
        one-liner that prints the probe token to stdout.  The live check
        must capture that output and exit non-zero.
        """
        token = _PROBE
        leaky_cmd = f"{sys.executable} -c \"import sys; sys.stdout.write('{token}\\\\n')\""
        result = subprocess.run(
            [
                sys.executable, "-m", "argo_cli.main",
                "doctor", "--live",
                "--rename-yaml", str(_RENAME_YAML),
                "--live-cmd", leaky_cmd,
            ],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )

        assert result.returncode != 0, (
            f"Expected non-zero exit when live command leaks the token\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_live_clean_exits_zero(self) -> None:
        """--live exits 0 when the captured output contains no upstream tokens.

        This test runs against the real repo via `argo --help` + `argo --version`
        (the built-in fallback commands used when no --live-cmd is given).  After
        the M3 bootstrap the install must be free of upstream identifiers.
        """
        result = subprocess.run(
            [
                sys.executable, "-m", "argo_cli.main",
                "doctor", "--live",
                "--rename-yaml", str(_RENAME_YAML),
            ],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )

        assert result.returncode == 0, (
            f"Expected exit 0 — real `argo` install should be leakage-free\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
