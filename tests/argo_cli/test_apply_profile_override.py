"""Regression tests for _apply_profile_override ARGO_HOME guard (issue #22502).

When ARGO_HOME is set to the argo root (e.g. systemd hardcodes
ARGO_HOME=/root/.argo), _apply_profile_override must still read
active_profile and update ARGO_HOME to the profile directory.

When ARGO_HOME is already a profile directory (.../profiles/<name>),
_apply_profile_override must trust it and return without re-reading
active_profile (child-process inheritance contract).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


def _run_apply_profile_override(
    tmp_path, monkeypatch, *, argo_home: str | None, active_profile: str | None,
    argv: list[str] | None = None,
):
    """Run _apply_profile_override in isolation.

    Returns the value of os.environ["ARGO_HOME"] after the call,
    or None if unset.
    """
    argo_root = tmp_path / ".argo"
    argo_root.mkdir(parents=True, exist_ok=True)

    if active_profile is not None:
        (argo_root / "active_profile").write_text(active_profile)

    if active_profile and active_profile != "default":
        (argo_root / "profiles" / active_profile).mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    if argo_home is not None:
        monkeypatch.setenv("ARGO_HOME", argo_home)
    else:
        monkeypatch.delenv("ARGO_HOME", raising=False)

    monkeypatch.setattr(sys, "argv", argv or ["argo", "gateway", "start"])

    from argo_cli.main import _apply_profile_override
    _apply_profile_override()

    return os.environ.get("ARGO_HOME")


class TestApplyProfileOverrideArgoHomeGuard:
    """Regression guard for issue #22502.

    Verifies that ARGO_HOME pointing to the argo root does NOT suppress
    the active_profile check, while ARGO_HOME already pointing to a
    profile directory IS trusted as-is.
    """

    def test_argo_home_at_root_with_active_profile_is_redirected(
        self, tmp_path, monkeypatch
    ):
        """ARGO_HOME=/root/.argo + active_profile=coder must redirect
        ARGO_HOME to .../profiles/coder.

        Bug scenario from #22502: systemd sets ARGO_HOME to the argo root
        and the user switches to a profile via `argo profile use`.
        Before the fix, the guard returned early and active_profile was ignored.
        """
        argo_root = tmp_path / ".argo"
        argo_root.mkdir(parents=True, exist_ok=True)

        result = _run_apply_profile_override(
            tmp_path,
            monkeypatch,
            argo_home=str(argo_root),
            active_profile="coder",
        )

        assert result is not None, "ARGO_HOME must be set after profile redirect"
        assert "profiles" in result, (
            f"Expected ARGO_HOME to point into profiles/ dir, got: {result!r}"
        )
        assert result.endswith("coder"), (
            f"Expected ARGO_HOME to end with 'coder', got: {result!r}"
        )

    def test_argo_home_already_profile_dir_is_trusted(self, tmp_path, monkeypatch):
        """ARGO_HOME=.../profiles/coder must not be overridden even when
        active_profile says something different.

        Preserves the child-process inheritance contract: a subprocess spawned
        with ARGO_HOME already set to a specific profile must stay in that
        profile.
        """
        argo_root = tmp_path / ".argo"
        profile_dir = argo_root / "profiles" / "coder"
        profile_dir.mkdir(parents=True, exist_ok=True)

        (argo_root / "active_profile").write_text("other")

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("ARGO_HOME", str(profile_dir))
        monkeypatch.setattr(sys, "argv", ["argo", "gateway", "start"])

        from argo_cli.main import _apply_profile_override
        _apply_profile_override()

        assert os.environ.get("ARGO_HOME") == str(profile_dir), (
            "ARGO_HOME must remain unchanged when already pointing to a profile dir"
        )

    def test_argo_home_unset_reads_active_profile(self, tmp_path, monkeypatch):
        """Classic case: ARGO_HOME unset + active_profile=coder must set
        ARGO_HOME to the profile directory (existing behaviour must not regress).
        """
        result = _run_apply_profile_override(
            tmp_path,
            monkeypatch,
            argo_home=None,
            active_profile="coder",
        )

        assert result is not None
        assert "coder" in result

    def test_argo_home_unset_default_profile_no_redirect(self, tmp_path, monkeypatch):
        """active_profile=default must not redirect ARGO_HOME."""
        argo_root = tmp_path / ".argo"
        argo_root.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("ARGO_HOME", raising=False)
        monkeypatch.setattr(sys, "argv", ["argo", "gateway", "start"])
        (argo_root / "active_profile").write_text("default")

        from argo_cli.main import _apply_profile_override
        _apply_profile_override()

        assert os.environ.get("ARGO_HOME") is None
