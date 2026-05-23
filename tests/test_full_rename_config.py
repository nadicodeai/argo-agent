"""Validation tests for the full argo-rename.yaml configuration (T3.1).

Asserts structural correctness, required identifier coverage, and ordering
constraints for the production rename config.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from argo_sync.config import RenameConfig

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_CONFIG_PATH = _REPO_ROOT / "argo-rename.yaml"


@pytest.fixture(scope="module")
def config() -> RenameConfig:
    return RenameConfig.load(_CONFIG_PATH)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_config_loads_without_error(config: RenameConfig) -> None:
    """argo-rename.yaml must load cleanly."""
    assert config is not None


def test_mappings_count_ge_15(config: RenameConfig) -> None:
    """At least 15 mapping entries must be present."""
    assert len(config.mappings) >= 15, (
        f"Expected >= 15 mappings, got {len(config.mappings)}"
    )


def test_mappings_sorted_longest_first(config: RenameConfig) -> None:
    """Mappings must be sorted by descending length of the 'from' key."""
    lengths = [len(from_) for from_, _ in config.mappings]
    assert lengths == sorted(lengths, reverse=True), (
        "Mappings are not sorted longest-from-first: "
        + str([(f, len(f)) for f, _ in config.mappings])
    )


def test_required_identifiers_present(config: RenameConfig) -> None:
    """All required 'from' identifiers must be in the mappings."""
    from_keys = {from_ for from_, _ in config.mappings}
    required = {
        "ArgoAgent",
        "argo-agent",
        "argo_agent",
        "argo_cli",
        "argo_bootstrap",
        "argo_constants",
        "argo_state",
        "argo_time",
        "argo_logging",
        "argo_tools_mcp_server",
        "ARGO_HOME",
        "ARGO_",
        "~/.argo",
        ".argo/",
        "Argo",
        "ARGO",
        "argo",
    }
    missing = required - from_keys
    assert not missing, f"Missing required 'from' keys: {sorted(missing)}"


def test_required_to_values_correct(config: RenameConfig) -> None:
    """Key mappings must have the correct 'to' values."""
    mapping_dict = dict(config.mappings)
    expected = {
        "ArgoAgent": "ArgoAgent",
        "argo-agent": "argo-agent",
        "argo_agent": "argo_agent",
        "argo_cli": "argo_cli",
        "ARGO_HOME": "ARGO_HOME",
        "ARGO_": "ARGO_",
        "Argo": "Argo",
        "ARGO": "ARGO",
        "argo": "argo",
    }
    for from_, to_ in expected.items():
        assert mapping_dict.get(from_) == to_, (
            f"Mapping {from_!r} -> expected {to_!r}, got {mapping_dict.get(from_)!r}"
        )


def test_exceptions_contains_shepherd(config: RenameConfig) -> None:
    """exceptions must contain the .shepherd/** entry."""
    paths = {rule.path for rule in config.exceptions}
    assert ".shepherd/**" in paths, (
        f".shepherd/** not in exceptions paths: {paths}"
    )


def test_exceptions_contains_rename_yaml(config: RenameConfig) -> None:
    """exceptions must contain argo-rename.yaml (self-protection)."""
    paths = {rule.path for rule in config.exceptions}
    assert "argo-rename.yaml" in paths, (
        f"argo-rename.yaml not in exceptions paths: {paths}"
    )


def test_exceptions_contains_bootstrap_script(config: RenameConfig) -> None:
    """exceptions must contain bin/argo-bootstrap.py."""
    paths = {rule.path for rule in config.exceptions}
    assert "bin/argo-bootstrap.py" in paths, (
        f"bin/argo-bootstrap.py not in exceptions paths: {paths}"
    )


def test_skip_contexts_non_empty(config: RenameConfig) -> None:
    """skip_contexts must contain at least the URL and hash patterns."""
    assert len(config.skip_contexts) >= 2, (
        f"Expected >= 2 skip_contexts, got {len(config.skip_contexts)}"
    )
    # At least one pattern should handle URLs
    url_patterns = [p for p in config.skip_contexts if "http" in p]
    assert url_patterns, "No URL-matching skip_context found"


def test_longer_argo_agent_before_shorter_argo(config: RenameConfig) -> None:
    """'argo_agent' must appear before 'argo' in the sorted mapping list."""
    froms = [f for f, _ in config.mappings]
    assert "argo_agent" in froms, "argo_agent not in mappings"
    assert "argo" in froms, "argo not in mappings"
    assert froms.index("argo_agent") < froms.index("argo"), (
        "argo_agent must come before argo in the sorted order"
    )


def test_argo_home_before_argo_bare(config: RenameConfig) -> None:
    """'ARGO_HOME' must appear before bare 'ARGO' entry."""
    froms = [f for f, _ in config.mappings]
    assert froms.index("ARGO_HOME") < froms.index("ARGO"), (
        "ARGO_HOME must come before ARGO in sorted order"
    )
