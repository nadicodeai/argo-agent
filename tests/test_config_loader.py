"""Tests for argo_sync.config.RenameConfig loader."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from argo_sync.errors import ConfigError
from argo_sync.config import RenameConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
SEED_CONFIG = REPO_ROOT / "argo-rename.yaml"


def _write_yaml(tmp_path: Path, data: object, filename: str = "rename.yaml") -> Path:
    p = tmp_path / filename
    p.write_text(yaml.dump(data), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 1. Loads the repo's argo-rename.yaml successfully
# ---------------------------------------------------------------------------


def test_load_seed_config() -> None:
    cfg = RenameConfig.load(SEED_CONFIG)
    # T3.1 populated mappings: expect at least the 17 required entries.
    assert len(cfg.mappings) >= 17
    # Three exceptions: .shepherd/**, argo-rename.yaml, bin/argo-bootstrap.py
    assert len(cfg.exceptions) == 3
    # Three skip_context patterns (URL, sha40, sha64)
    assert len(cfg.skip_contexts) == 3


# ---------------------------------------------------------------------------
# 2. Sorts mappings longest-first
# ---------------------------------------------------------------------------


def test_mappings_sorted_longest_first(tmp_path: Path) -> None:
    data = {
        "mappings": [
            {"from": "short", "to": "S"},
            {"from": "MiddleKey", "to": "MK"},
            {"from": "longest-key", "to": "LK"},
        ],
        "exceptions": [],
        "skip_contexts": [],
    }
    cfg = RenameConfig.load(_write_yaml(tmp_path, data))
    froms = [m[0] for m in cfg.mappings]
    # longest-key=11, MiddleKey=9, short=5 → longest first
    assert froms == ["longest-key", "MiddleKey", "short"]


# ---------------------------------------------------------------------------
# 3. Raises ConfigError on malformed YAML
# ---------------------------------------------------------------------------


def test_malformed_yaml_raises_config_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("{unclosed: [", encoding="utf-8")
    with pytest.raises(ConfigError):
        RenameConfig.load(bad)


# ---------------------------------------------------------------------------
# 4. Raises ConfigError on empty `from`
# ---------------------------------------------------------------------------


def test_empty_from_raises_config_error(tmp_path: Path) -> None:
    data = {
        "mappings": [{"from": "", "to": "anything"}],
        "exceptions": [],
        "skip_contexts": [],
    }
    with pytest.raises(ConfigError, match="empty"):
        RenameConfig.load(_write_yaml(tmp_path, data))


# ---------------------------------------------------------------------------
# 5. matches_exception — positive case
# ---------------------------------------------------------------------------


def test_matches_exception_shepherd(tmp_path: Path) -> None:
    cfg = RenameConfig.load(SEED_CONFIG)
    assert cfg.matches_exception(".shepherd/spec.md") is True


# ---------------------------------------------------------------------------
# 6. matches_exception — negative case
# ---------------------------------------------------------------------------


def test_matches_exception_readme_false(tmp_path: Path) -> None:
    cfg = RenameConfig.load(SEED_CONFIG)
    assert cfg.matches_exception("README.md") is False


# ---------------------------------------------------------------------------
# 7. ExceptionRule fields
# ---------------------------------------------------------------------------


def test_exception_rule_fields() -> None:
    cfg = RenameConfig.load(SEED_CONFIG)
    rule = cfg.exceptions[0]
    assert rule.path == ".shepherd/**"
    assert "Orchestrator" in rule.why


# ---------------------------------------------------------------------------
# 8. skip_contexts loaded correctly
# ---------------------------------------------------------------------------


def test_skip_contexts_loaded(tmp_path: Path) -> None:
    data = {
        "mappings": [],
        "exceptions": [],
        "skip_contexts": [r"https?://[^\s]*", r"\b[0-9a-f]{20,}\b"],
    }
    cfg = RenameConfig.load(_write_yaml(tmp_path, data))
    assert len(cfg.skip_contexts) == 2
    assert cfg.skip_contexts[0] == r"https?://[^\s]*"


# ---------------------------------------------------------------------------
# 9. Missing required top-level keys raises ConfigError
# ---------------------------------------------------------------------------


def test_missing_mappings_key_raises(tmp_path: Path) -> None:
    data = {"exceptions": [], "skip_contexts": []}
    with pytest.raises(ConfigError, match="mappings"):
        RenameConfig.load(_write_yaml(tmp_path, data))


# ---------------------------------------------------------------------------
# 10. RenameConfig is immutable (frozen dataclass)
# ---------------------------------------------------------------------------


def test_rename_config_is_frozen() -> None:
    cfg = RenameConfig.load(SEED_CONFIG)
    with pytest.raises((AttributeError, TypeError)):
        cfg.mappings = ()  # type: ignore[misc]
