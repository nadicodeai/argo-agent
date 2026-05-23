"""Tests for get_argo_home() profile-mode fallback warning.

Regression test for https://github.com/NousResearch/argo-agent/issues/18594.

When ARGO_HOME is unset but an active_profile file indicates a non-default
profile is active, get_argo_home() should:
  1. STILL return ~/.argo (raising would brick 30+ module-level callers)
  2. Emit a loud one-shot warning to stderr so operators can diagnose
     cross-profile data contamination after the fact.

The warning goes to stderr directly (not through logging) because this
function is called at module-import time from 30+ sites, often before the
logging subsystem has been configured.
"""

from pathlib import Path

import pytest


@pytest.fixture
def fresh_constants(monkeypatch, tmp_path):
    """Import argo_constants fresh and reset the one-shot warn flag."""
    import importlib
    import argo_constants
    importlib.reload(argo_constants)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("ARGO_HOME", raising=False)
    return argo_constants


class TestGetArgoHomeProfileWarning:
    def test_classic_mode_no_active_profile_no_warning(
        self, fresh_constants, tmp_path, capsys
    ):
        """Classic mode: no active_profile file → silent, returns ~/.argo."""
        result = fresh_constants.get_argo_home()
        assert result == tmp_path / ".argo"
        assert "ARGO_HOME fallback" not in capsys.readouterr().err

    def test_default_active_profile_no_warning(
        self, fresh_constants, tmp_path, capsys
    ):
        """active_profile=default → still no warning, returns ~/.argo."""
        argo_dir = tmp_path / ".argo"
        argo_dir.mkdir()
        (argo_dir / "active_profile").write_text("default\n")
        result = fresh_constants.get_argo_home()
        assert result == tmp_path / ".argo"
        assert "ARGO_HOME fallback" not in capsys.readouterr().err

    def test_named_profile_unset_home_warns_once(
        self, fresh_constants, tmp_path, capsys
    ):
        """active_profile=coder + ARGO_HOME unset → warn loudly, still return fallback."""
        argo_dir = tmp_path / ".argo"
        argo_dir.mkdir()
        (argo_dir / "active_profile").write_text("coder\n")

        result = fresh_constants.get_argo_home()

        # 1. Still returns the fallback — no import-time crash
        assert result == tmp_path / ".argo"
        # 2. Stderr got the warning exactly once
        err = capsys.readouterr().err
        assert err.count("ARGO_HOME fallback") == 1
        assert "'coder'" in err
        assert "#18594" in err

        # 3. One-shot: second and third calls don't re-warn
        fresh_constants.get_argo_home()
        fresh_constants.get_argo_home()
        err2 = capsys.readouterr().err
        assert "ARGO_HOME fallback" not in err2

    def test_argo_home_set_suppresses_warning(
        self, fresh_constants, tmp_path, capsys, monkeypatch
    ):
        """Even if active_profile is 'coder', setting ARGO_HOME suppresses warning."""
        profile_dir = tmp_path / ".argo" / "profiles" / "coder"
        profile_dir.mkdir(parents=True)
        (tmp_path / ".argo" / "active_profile").write_text("coder\n")
        monkeypatch.setenv("ARGO_HOME", str(profile_dir))

        result = fresh_constants.get_argo_home()

        assert result == profile_dir
        assert "ARGO_HOME fallback" not in capsys.readouterr().err

    def test_unreadable_active_profile_no_crash(
        self, fresh_constants, tmp_path, capsys
    ):
        """active_profile that can't be decoded → fall through silently."""
        argo_dir = tmp_path / ".argo"
        argo_dir.mkdir()
        # Write bytes that aren't valid utf-8
        (argo_dir / "active_profile").write_bytes(b"\xff\xfe\x00\x00")

        result = fresh_constants.get_argo_home()

        assert result == tmp_path / ".argo"
        # Shouldn't crash; shouldn't warn either (can't tell what profile was intended)
        assert "ARGO_HOME fallback" not in capsys.readouterr().err

    def test_empty_active_profile_no_warning(
        self, fresh_constants, tmp_path, capsys
    ):
        """Empty active_profile file → treated as default, no warning."""
        argo_dir = tmp_path / ".argo"
        argo_dir.mkdir()
        (argo_dir / "active_profile").write_text("")

        result = fresh_constants.get_argo_home()

        assert result == tmp_path / ".argo"
        assert "ARGO_HOME fallback" not in capsys.readouterr().err
