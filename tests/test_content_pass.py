"""Tests for argo_sync.passes.content.ContentPass."""

from __future__ import annotations

from pathlib import Path

import pytest

from argo_sync.config import RenameConfig
from argo_sync.passes.content import ContentPass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    mappings: list[tuple[str, str]],
    exceptions: list[dict[str, str]] | None = None,
    skip_contexts: list[str] | None = None,
    cfg_dir: Path | None = None,
) -> RenameConfig:
    """Build a RenameConfig, writing the YAML to *cfg_dir*.

    *cfg_dir* must be separate from the ``root`` directory that
    ``ContentPass.run(root)`` will walk, so the config file itself is not
    processed as a fixture file.
    """
    import yaml

    data = {
        "mappings": [{"from": f, "to": t} for f, t in mappings],
        "exceptions": exceptions or [],
        "skip_contexts": skip_contexts or [],
    }
    assert cfg_dir is not None, "_make_config requires cfg_dir"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_file = cfg_dir / "rename.yaml"
    cfg_file.write_text(yaml.dump(data), encoding="utf-8")
    return RenameConfig.load(cfg_file)


def _setup(
    tmp_path: Path,
    mappings: list[tuple[str, str]],
    exceptions: list[dict[str, str]] | None = None,
    skip_contexts: list[str] | None = None,
) -> tuple[RenameConfig, Path]:
    """Return (config, root) where root is a subdirectory for fixture files.

    The config YAML lives in ``tmp_path/_cfg/`` and the tree under test lives
    in ``tmp_path/root/``, so the pass never walks the config file.
    """
    cfg = _make_config(
        mappings,
        exceptions=exceptions,
        skip_contexts=skip_contexts,
        cfg_dir=tmp_path / "_cfg",
    )
    root = tmp_path / "root"
    root.mkdir()
    return cfg, root


# ---------------------------------------------------------------------------
# 1. Simple text file — content changes, path returned
# ---------------------------------------------------------------------------


def test_simple_mapping_applied(tmp_path: Path) -> None:
    cfg, root = _setup(tmp_path, [("old-name", "new-name")])
    target = root / "sample.txt"
    target.write_text("Replace old-name here.", encoding="utf-8")

    result = ContentPass(cfg).run(root)

    assert target in result
    assert target.read_text(encoding="utf-8") == "Replace new-name here."


# ---------------------------------------------------------------------------
# 2. Multiple files in nested dirs — all renamed
# ---------------------------------------------------------------------------


def test_nested_dirs_all_renamed(tmp_path: Path) -> None:
    cfg, root = _setup(tmp_path, [("Foo", "Bar")])

    (root / "sub").mkdir()
    f1 = root / "a.txt"
    f2 = root / "sub" / "b.txt"
    f1.write_text("Foo in root", encoding="utf-8")
    f2.write_text("Foo in subdir", encoding="utf-8")

    result = ContentPass(cfg).run(root)

    assert set(result) == {f1, f2}
    assert f1.read_text(encoding="utf-8") == "Bar in root"
    assert f2.read_text(encoding="utf-8") == "Bar in subdir"


# ---------------------------------------------------------------------------
# 3. File matching an exception glob is NOT touched
# ---------------------------------------------------------------------------


def test_exception_glob_not_touched(tmp_path: Path) -> None:
    cfg, root = _setup(
        tmp_path,
        [("old-name", "new-name")],
        exceptions=[{"path": "skip/**", "why": "Test exception."}],
    )
    (root / "skip").mkdir()
    skipped = root / "skip" / "file.txt"
    skipped.write_text("old-name inside exception", encoding="utf-8")
    normal = root / "normal.txt"
    normal.write_text("old-name outside exception", encoding="utf-8")

    result = ContentPass(cfg).run(root)

    assert skipped not in result
    assert skipped.read_text(encoding="utf-8") == "old-name inside exception"
    assert normal in result
    assert normal.read_text(encoding="utf-8") == "new-name outside exception"


# ---------------------------------------------------------------------------
# 4. Binary file (contains NUL byte) is NOT touched
# ---------------------------------------------------------------------------


def test_binary_file_not_touched(tmp_path: Path) -> None:
    cfg, root = _setup(tmp_path, [("old-name", "new-name")])
    binary = root / "data.bin"
    binary.write_bytes(b"old-name\x00binary")

    result = ContentPass(cfg).run(root)

    assert binary not in result
    assert binary.read_bytes() == b"old-name\x00binary"


# ---------------------------------------------------------------------------
# 5. Files in skipped directories (.git, .venv, .argo, __pycache__, node_modules)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "skip_dir",
    [".git", ".venv", ".argo", "__pycache__", "node_modules"],
)
def test_skipped_directories_not_touched(tmp_path: Path, skip_dir: str) -> None:
    cfg, root = _setup(tmp_path, [("old-name", "new-name")])
    d = root / skip_dir
    d.mkdir()
    f = d / "file.txt"
    f.write_text("old-name in skipped dir", encoding="utf-8")

    result = ContentPass(cfg).run(root)

    assert f not in result
    assert f.read_text(encoding="utf-8") == "old-name in skipped dir"


# ---------------------------------------------------------------------------
# 6. Mapping ordering: longest-first wins — no double-replace
# ---------------------------------------------------------------------------


def test_longest_key_wins_no_double_replace(tmp_path: Path) -> None:
    # "longest-key" is 11 chars; "longest" is 7 chars.
    # The config loader sorts longest-first, so "longest-key" is applied
    # first.  Without this guarantee, "longest-key" → "partial-key" and then
    # no second pass would catch it, or worse it would be left as "partial-key".
    cfg, root = _setup(
        tmp_path,
        [("longest", "partial"), ("longest-key", "full-match")],
    )
    f = root / "test.txt"
    f.write_text("longest-key and longest", encoding="utf-8")

    ContentPass(cfg).run(root)

    # longest-key → full-match first (no partial corruption); longest → partial
    assert f.read_text(encoding="utf-8") == "full-match and partial"


# ---------------------------------------------------------------------------
# 7. skip_contexts: key inside a URL is NOT renamed; elsewhere IS renamed
# ---------------------------------------------------------------------------


def test_skip_contexts_url_not_renamed(tmp_path: Path) -> None:
    cfg, root = _setup(
        tmp_path,
        [("old-name", "new-name")],
        skip_contexts=[r"https?://[^\s]*"],
    )
    f = root / "doc.md"
    # "old-name" appears twice: once in a URL (skip), once in plain text (rename)
    f.write_text(
        "See https://example.com/old-name/path for details. Also old-name rocks.",
        encoding="utf-8",
    )

    ContentPass(cfg).run(root)

    content = f.read_text(encoding="utf-8")
    # URL is preserved
    assert "https://example.com/old-name/path" in content
    # Plain text is renamed
    assert "Also new-name rocks." in content


# ---------------------------------------------------------------------------
# 8. Unchanged file (no mappings hit) is NOT in the returned list
# ---------------------------------------------------------------------------


def test_unchanged_file_not_returned(tmp_path: Path) -> None:
    cfg, root = _setup(tmp_path, [("old-name", "new-name")])
    f = root / "untouched.txt"
    f.write_text("nothing to replace here", encoding="utf-8")

    result = ContentPass(cfg).run(root)

    assert f not in result


# ---------------------------------------------------------------------------
# 9. UTF-8 file with non-ASCII characters is preserved correctly
# ---------------------------------------------------------------------------


def test_utf8_non_ascii_preserved(tmp_path: Path) -> None:
    cfg, root = _setup(tmp_path, [("old-name", "new-name")])
    f = root / "unicode.txt"
    original = "Héllo wörld — old-name 🎉"
    f.write_text(original, encoding="utf-8")

    ContentPass(cfg).run(root)

    assert f.read_text(encoding="utf-8") == "Héllo wörld — new-name 🎉"


# ---------------------------------------------------------------------------
# 10. Empty file is handled without error
# ---------------------------------------------------------------------------


def test_empty_file_no_error(tmp_path: Path) -> None:
    cfg, root = _setup(tmp_path, [("old-name", "new-name")])
    f = root / "empty.txt"
    f.write_text("", encoding="utf-8")

    result = ContentPass(cfg).run(root)

    assert f not in result
    assert f.read_text(encoding="utf-8") == ""
